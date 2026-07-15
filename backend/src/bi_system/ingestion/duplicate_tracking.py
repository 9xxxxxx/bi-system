import json
import sqlite3
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol


class DuplicateTracker(Protocol):
    def is_duplicate(self, namespace: str, values: tuple[object, ...]) -> bool: ...


class InMemoryDuplicateTracker:
    def __init__(self) -> None:
        self._seen: dict[str, set[tuple[object, ...]]] = {}

    def is_duplicate(self, namespace: str, values: tuple[object, ...]) -> bool:
        seen = self._seen.setdefault(namespace, set())
        if values in seen:
            return True
        seen.add(values)
        return False


class SqliteDuplicateTracker:
    def __init__(self, temporary_directory: Path, *, prefix: str) -> None:
        temporary_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=prefix,
            suffix=".part",
            dir=temporary_directory,
            delete=False,
        ) as temporary_file:
            self.path = Path(temporary_file.name)
        self._connection = sqlite3.connect(self.path)
        self._connection.execute("PRAGMA journal_mode=OFF")
        self._connection.execute("PRAGMA synchronous=OFF")
        self._connection.execute("PRAGMA locking_mode=EXCLUSIVE")
        self._connection.execute("PRAGMA cache_size=-4096")
        self._connection.execute(
            "CREATE TABLE seen (namespace TEXT, value TEXT, PRIMARY KEY (namespace, value)) "
            "WITHOUT ROWID",
        )
        self._connection.execute("BEGIN")

    def is_duplicate(self, namespace: str, values: tuple[object, ...]) -> bool:
        serialized = json.dumps(
            [_typed_value(value) for value in values],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        cursor = self._connection.execute(
            "INSERT OR IGNORE INTO seen (namespace, value) VALUES (?, ?)",
            (namespace, serialized),
        )
        return cursor.rowcount == 0

    def close(self) -> None:
        try:
            self._connection.close()
        finally:
            self.path.unlink(missing_ok=True)


def _typed_value(value: object) -> tuple[str, object]:
    if isinstance(value, Decimal):
        return ("decimal", str(value))
    if isinstance(value, datetime):
        return ("datetime", value.isoformat())
    if isinstance(value, date):
        return ("date", value.isoformat())
    return (type(value).__name__, value)
