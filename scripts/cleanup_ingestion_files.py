import argparse
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from bi_system.core.config import get_settings
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.ingestion.cleanup import cleanup_ingestion_storage
from bi_system.ingestion.storage import LocalContentAddressedStorage


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean stale ingestion files safely")
    parser.add_argument("--older-hours", type=float, default=24.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    if args.older_hours <= 0:
        raise ValueError("--older-hours must be positive")

    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    storage = LocalContentAddressedStorage(
        settings.storage_root,
        max_bytes=settings.upload_max_bytes,
    )
    cutoff = datetime.now(UTC) - timedelta(hours=args.older_hours)

    try:
        with session_factory() as session:
            result = cleanup_ingestion_storage(
                session,
                storage,
                older_than=cutoff,
                dry_run=args.dry_run,
            )
        print(
            f"temporary_files={result.temporary_files} "
            f"orphan_blobs={result.orphan_blobs} "
            f"bytes_reclaimed={result.bytes_reclaimed}",
        )
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
