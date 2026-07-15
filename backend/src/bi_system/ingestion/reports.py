import csv
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from bi_system.db.models import FileBlob, ImportBatch
from bi_system.ingestion.storage import LocalContentAddressedStorage
from bi_system.ingestion.validation import EvaluatedRow

QUALITY_REPORT_MEDIA_TYPE = "text/csv"


class QualityReportWriter:
    def __init__(self, storage: LocalContentAddressedStorage, batch_id: UUID) -> None:
        report_directory = storage.root / ".reports"
        report_directory.mkdir(parents=True, exist_ok=True)
        self.path = storage.path_for(f".reports/{batch_id}.csv.part")
        self.issue_count = 0
        self._file = self.path.open("w", encoding="utf-8-sig", newline="")
        self._writer = csv.writer(self._file)
        self._writer.writerow(
            ["row_number", "column_name", "severity", "code", "message", "raw_value"],
        )

    def write_row(self, row: EvaluatedRow) -> None:
        for issue in row.issues:
            self._writer.writerow(
                [
                    issue.row_number,
                    issue.column_name or "",
                    issue.severity.value,
                    issue.code,
                    issue.message,
                    issue.raw_value or "",
                ],
            )
            self.issue_count += 1

    def close(self) -> None:
        if not self._file.closed:
            self._file.flush()
            self._file.close()

    def discard(self) -> None:
        self.close()
        if self.path.exists():
            self.path.unlink()


def attach_quality_report(
    session: Session,
    storage: LocalContentAddressedStorage,
    *,
    batch_id: UUID,
    report_path: Path,
    max_bytes: int,
) -> FileBlob:
    with report_path.open("rb") as report_file:
        stored = storage.store(report_file, max_bytes=max_bytes)

    with session.begin():
        blob = session.scalar(select(FileBlob).where(FileBlob.sha256 == stored.sha256))
        if blob is None:
            blob = FileBlob(
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                media_type=QUALITY_REPORT_MEDIA_TYPE,
                storage_key=stored.storage_key,
            )
            session.add(blob)
            session.flush()
        batch = session.get(ImportBatch, batch_id)
        if batch is None:
            raise ValueError("Import batch was not found while attaching report")
        batch.error_report_blob_id = blob.id
        batch.updated_at = datetime.now(UTC)
    return blob
