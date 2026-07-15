# pyright: reportAny=false, reportUnknownMemberType=false
import argparse
import csv
import json
import tempfile
import threading
import time
import tracemalloc
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

from bi_system.api.routes import health
from bi_system.core.config import Settings
from bi_system.db.base import Base
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.ingestion.batch_contracts import CreateImportBatch
from bi_system.ingestion.batches import create_import_batch
from bi_system.ingestion.domain import ImportMode
from bi_system.ingestion.files import register_source_file
from bi_system.ingestion.storage import LocalContentAddressedStorage
from bi_system.ingestion.template_contracts import ImportTemplateDefinition
from bi_system.ingestion.worker import run_next_import_batch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.engine import Engine


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    rows: int
    file_bytes: int
    generation_seconds: float
    registration_seconds: float
    import_seconds: float
    rows_per_second: float
    python_heap_peak_mb: float
    readiness_checks: int
    readiness_failures: int
    readiness_max_latency_ms: float
    final_status: str
    valid_rows: int
    database_bytes: int


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark the complete M1 CSV import path")
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--chunk-rows", type=int, default=2_000)
    parser.add_argument("--output", type=Path)
    return parser


def generate_csv(path: Path, rows: int) -> float:
    started = time.perf_counter()
    regions = ("华东", "华南", "华北", "西南")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("order_id", "region", "amount", "order_date"))
        for index in range(1, rows + 1):
            writer.writerow(
                (
                    f"ORD{index:09d}",
                    regions[index % len(regions)],
                    f"{(index % 100_000) / 100:.2f}",
                    f"2026-07-{(index % 28) + 1:02d}",
                ),
            )
    return time.perf_counter() - started


def benchmark_definition() -> ImportTemplateDefinition:
    return ImportTemplateDefinition.model_validate(
        {
            "file_kind": "csv",
            "columns": [
                {
                    "source_key": "column_1",
                    "source_name": "order_id",
                    "target_name": "order_id",
                    "data_type": "string",
                    "nullable": False,
                },
                {
                    "source_key": "column_2",
                    "source_name": "region",
                    "target_name": "region",
                    "data_type": "string",
                    "nullable": False,
                },
                {
                    "source_key": "column_3",
                    "source_name": "amount",
                    "target_name": "amount",
                    "data_type": "decimal",
                    "nullable": False,
                },
                {
                    "source_key": "column_4",
                    "source_name": "order_date",
                    "target_name": "order_date",
                    "data_type": "date",
                    "nullable": False,
                },
            ],
            "business_key": ["order_id"],
            "quality_rules": [
                {
                    "name": "order_id_required",
                    "rule_type": "required",
                    "severity": "error",
                    "column_name": "order_id",
                    "parameters": {},
                },
            ],
        },
    )


def _readiness_application(engine: Engine) -> FastAPI:
    application = FastAPI()
    application.state.engine = engine
    application.include_router(health.router, prefix="/api/v1/health")
    return application


def _probe_readiness(
    client: TestClient,
    stop: threading.Event,
    latencies: list[float],
    failures: list[str],
) -> None:
    while not stop.is_set():
        started = time.perf_counter()
        try:
            response = cast(Response, client.get("/api/v1/health/ready"))
            if response.status_code != 200:
                failures.append(str(response.status_code))
        except Exception as exc:  # Probe errors are evidence, not benchmark crashes.
            failures.append(type(exc).__name__)
        latencies.append((time.perf_counter() - started) * 1_000)
        stop.wait(0.05)


def run_benchmark(workspace: Path, *, rows: int, chunk_rows: int) -> BenchmarkResult:
    if rows <= 0 or chunk_rows <= 0:
        raise ValueError("rows and chunk_rows must be positive")

    workspace.mkdir(parents=True, exist_ok=True)
    source_path = workspace / "m1-scale.csv"
    database_path = workspace / "m1-scale.db"
    storage_root = workspace / "uploads"
    generation_seconds = generate_csv(source_path, rows)

    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(engine)
    settings = Settings(
        database_url=database_url,
        storage_root=storage_root,
        upload_max_bytes=100 * 1024 * 1024,
        import_max_rows=rows,
        import_chunk_rows=chunk_rows,
        preview_max_rows=min(100, chunk_rows),
        import_issue_sample_limit=1_000,
        import_worker_lease_seconds=120,
        workspace_id=uuid4(),
    )
    storage = LocalContentAddressedStorage(storage_root, max_bytes=settings.upload_max_bytes)

    registration_started = time.perf_counter()
    with source_path.open("rb") as source_stream, session_factory() as session:
        registered = register_source_file(
            session,
            storage,
            workspace_id=settings.workspace_id,
            original_name=source_path.name,
            stream=source_stream,
            xlsx_max_uncompressed_bytes=settings.xlsx_max_uncompressed_bytes,
            xlsx_max_compression_ratio=settings.xlsx_max_compression_ratio,
        )
        stored = create_import_batch(
            session,
            workspace_id=settings.workspace_id,
            request=CreateImportBatch(
                source_file_id=registered.source_file.id,
                definition=benchmark_definition(),
                target_name="M1 scale benchmark",
                mode=ImportMode.APPEND,
            ),
        )
        batch_id = stored.batch.id
    registration_seconds = time.perf_counter() - registration_started

    latencies: list[float] = []
    failures: list[str] = []
    stop = threading.Event()
    application = _readiness_application(engine)
    tracemalloc.start()
    import_started = time.perf_counter()
    try:
        with TestClient(application) as client:
            probe = threading.Thread(
                target=_probe_readiness,
                args=(client, stop, latencies, failures),
                daemon=True,
            )
            probe.start()
            result = run_next_import_batch(
                engine,
                session_factory,
                storage,
                settings,
                worker_id="m1-benchmark",
            )
            stop.set()
            probe.join(timeout=5)
    finally:
        stop.set()
    import_seconds = time.perf_counter() - import_started
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    if result is None or result.id != batch_id:
        raise RuntimeError("Benchmark worker did not process the expected batch")
    benchmark = BenchmarkResult(
        rows=rows,
        file_bytes=source_path.stat().st_size,
        generation_seconds=round(generation_seconds, 3),
        registration_seconds=round(registration_seconds, 3),
        import_seconds=round(import_seconds, 3),
        rows_per_second=round(rows / import_seconds, 1),
        python_heap_peak_mb=round(peak_bytes / 1024 / 1024, 2),
        readiness_checks=len(latencies),
        readiness_failures=len(failures),
        readiness_max_latency_ms=round(max(latencies, default=0), 2),
        final_status=result.status,
        valid_rows=result.valid_rows,
        database_bytes=database_path.stat().st_size,
    )
    engine.dispose()
    return benchmark


def main(argv: Sequence[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    temp_root = Path(".tmp")
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="m1-benchmark-", dir=temp_root) as directory:
        result = run_benchmark(Path(directory), rows=args.rows, chunk_rows=args.chunk_rows)
    payload = json.dumps(asdict(result), ensure_ascii=False, indent=2)
    print(payload)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if result.final_status == "succeeded" and result.readiness_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
