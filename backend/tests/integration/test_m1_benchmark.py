from pathlib import Path

from scripts.benchmark_m1_ingestion import run_benchmark


def test_m1_benchmark_uses_real_worker_and_readiness_probe(tmp_path: Path) -> None:
    result = run_benchmark(tmp_path, rows=250, chunk_rows=50)

    assert result.final_status == "succeeded"
    assert result.valid_rows == 250
    assert result.readiness_checks > 0
    assert result.readiness_failures == 0
    assert result.file_bytes > 0
    assert result.database_bytes > 0
