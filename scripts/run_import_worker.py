import argparse
import os
import socket
import time
from collections.abc import Sequence

from bi_system.core.config import get_settings
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.ingestion.storage import LocalContentAddressedStorage
from bi_system.ingestion.worker import run_next_import_batch


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the durable import worker")
    parser.add_argument("--once", action="store_true", help="Process at most one batch")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-{os.getpid()}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    if args.poll_seconds <= 0:
        raise ValueError("--poll-seconds must be positive")

    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    storage = LocalContentAddressedStorage(
        settings.storage_root,
        max_bytes=settings.upload_max_bytes,
    )

    try:
        while True:
            batch = run_next_import_batch(
                engine,
                session_factory,
                storage,
                settings,
                worker_id=args.worker_id,
            )
            if batch is not None:
                print(f"batch={batch.id} status={batch.status}", flush=True)
            if args.once:
                return 0
            if batch is None:
                time.sleep(args.poll_seconds)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
