import os
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

from bi_system.db.base import Base
from bi_system.db.models import FileBlob
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.ingestion.cleanup import cleanup_ingestion_storage
from bi_system.ingestion.storage import LocalContentAddressedStorage


def make_old(path: Path) -> None:
    timestamp = (datetime.now(UTC) - timedelta(days=2)).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_cleanup_removes_only_stale_unreferenced_files(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{(tmp_path / 'cleanup.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    storage = LocalContentAddressedStorage(tmp_path / "uploads", max_bytes=10_000)

    referenced = storage.store(BytesIO(b"referenced"))
    orphan = storage.store(BytesIO(b"orphan"))
    temporary = storage.path_for(".tmp/stale.part")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_bytes(b"temporary")
    fresh = storage.path_for(".reports/fresh.part")
    fresh.parent.mkdir(parents=True, exist_ok=True)
    fresh.write_bytes(b"fresh")
    make_old(storage.path_for(referenced.storage_key))
    make_old(storage.path_for(orphan.storage_key))
    make_old(temporary)

    try:
        with session_factory.begin() as session:
            session.add(
                FileBlob(
                    sha256=referenced.sha256,
                    size_bytes=referenced.size_bytes,
                    media_type="text/csv",
                    storage_key=referenced.storage_key,
                ),
            )
        with session_factory() as session:
            result = cleanup_ingestion_storage(
                session,
                storage,
                older_than=datetime.now(UTC) - timedelta(days=1),
            )

        assert result.temporary_files == 1
        assert result.orphan_blobs == 1
        assert result.bytes_reclaimed == len(b"temporary") + len(b"orphan")
        assert storage.path_for(referenced.storage_key).exists()
        assert not storage.path_for(orphan.storage_key).exists()
        assert fresh.exists()
    finally:
        engine.dispose()


def test_cleanup_dry_run_reports_without_deleting(tmp_path: Path) -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    storage = LocalContentAddressedStorage(tmp_path / "uploads", max_bytes=10_000)
    orphan = storage.store(BytesIO(b"orphan"))
    orphan_path = storage.path_for(orphan.storage_key)
    make_old(orphan_path)

    try:
        with session_factory() as session:
            result = cleanup_ingestion_storage(
                session,
                storage,
                older_than=datetime.now(UTC) - timedelta(days=1),
                dry_run=True,
            )
        assert result.orphan_blobs == 1
        assert orphan_path.exists()
    finally:
        engine.dispose()
