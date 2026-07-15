from pathlib import Path

from bi_system.ingestion.duplicate_tracking import SqliteDuplicateTracker


def test_sqlite_duplicate_tracker_is_disk_backed_and_cleans_up(tmp_path: Path) -> None:
    tracker = SqliteDuplicateTracker(tmp_path, prefix="duplicates-test-")
    path = tracker.path

    assert tracker.is_duplicate("business", ("A001", 1)) is False
    assert tracker.is_duplicate("business", ("A001", 1)) is True
    assert tracker.is_duplicate("business", ("A001", "1")) is False
    assert path.exists()

    tracker.close()

    assert not path.exists()
