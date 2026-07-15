from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from bi_system.db.models import FileBlob
from bi_system.ingestion.storage import LocalContentAddressedStorage, StorageBoundaryError


@dataclass(frozen=True, slots=True)
class CleanupResult:
    temporary_files: int
    orphan_blobs: int
    bytes_reclaimed: int


def cleanup_ingestion_storage(
    session: Session,
    storage: LocalContentAddressedStorage,
    *,
    older_than: datetime,
    dry_run: bool = False,
) -> CleanupResult:
    if older_than.tzinfo is None:
        raise ValueError("older_than must be timezone-aware")
    cutoff_timestamp = older_than.astimezone(UTC).timestamp()
    temporary_files = 0
    orphan_blobs = 0
    bytes_reclaimed = 0

    for directory_name in (".tmp", ".reports"):
        directory = storage.root / directory_name
        if not directory.exists():
            continue
        for path in directory.glob("*.part"):
            if path.stat().st_mtime >= cutoff_timestamp:
                continue
            size = path.stat().st_size
            _safe_unlink(storage, path, dry_run=dry_run)
            temporary_files += 1
            bytes_reclaimed += size

    referenced_keys = set(session.scalars(select(FileBlob.storage_key)).all())
    blob_root = storage.root / "sha256"
    if blob_root.exists():
        for path in blob_root.rglob("*"):
            if not path.is_file() or len(path.name) != 64:
                continue
            relative_key = path.relative_to(storage.root).as_posix()
            if relative_key in referenced_keys or path.stat().st_mtime >= cutoff_timestamp:
                continue
            size = path.stat().st_size
            _safe_unlink(storage, path, dry_run=dry_run)
            orphan_blobs += 1
            bytes_reclaimed += size

    return CleanupResult(
        temporary_files=temporary_files,
        orphan_blobs=orphan_blobs,
        bytes_reclaimed=bytes_reclaimed,
    )


def _safe_unlink(
    storage: LocalContentAddressedStorage,
    path: Path,
    *,
    dry_run: bool,
) -> None:
    try:
        relative_key = path.resolve().relative_to(storage.root).as_posix()
    except ValueError as exc:
        raise StorageBoundaryError("Cleanup path is outside the configured root") from exc
    verified_path = storage.path_for(relative_key)
    if verified_path != path.resolve():
        raise StorageBoundaryError("Cleanup path does not match its verified path")
    if not dry_run:
        verified_path.unlink()
