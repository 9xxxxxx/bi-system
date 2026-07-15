from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO
from uuid import UUID
from zipfile import BadZipFile, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from bi_system.db.models import FileBlob, SourceFile
from bi_system.ingestion.domain import FileKind
from bi_system.ingestion.storage import LocalContentAddressedStorage

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MEDIA_TYPE = "text/csv"


class SourceFileError(ValueError):
    """Base error for source file registration and inspection."""


class InvalidSourceFilenameError(SourceFileError):
    pass


class UnsupportedSourceFileError(SourceFileError):
    pass


class InvalidSourceContentError(SourceFileError):
    pass


@dataclass(frozen=True, slots=True)
class RegisteredSourceFile:
    source_file: SourceFile
    blob: FileBlob
    duplicate: bool


def register_source_file(
    session: Session,
    storage: LocalContentAddressedStorage,
    *,
    workspace_id: UUID,
    original_name: str | None,
    stream: BinaryIO,
    xlsx_max_uncompressed_bytes: int,
    xlsx_max_compression_ratio: float,
) -> RegisteredSourceFile:
    safe_name = normalize_source_filename(original_name)
    file_kind = source_file_kind(safe_name)
    validate_source_content(
        stream,
        file_kind=file_kind,
        xlsx_max_uncompressed_bytes=xlsx_max_uncompressed_bytes,
        xlsx_max_compression_ratio=xlsx_max_compression_ratio,
    )
    stream.seek(0)
    stored_blob = storage.store(stream)

    with session.begin():
        blob = session.scalar(select(FileBlob).where(FileBlob.sha256 == stored_blob.sha256))
        if blob is None:
            blob = FileBlob(
                sha256=stored_blob.sha256,
                size_bytes=stored_blob.size_bytes,
                media_type=source_file_media_type(file_kind),
                storage_key=stored_blob.storage_key,
            )
            session.add(blob)
            session.flush()

        source_file = session.scalar(
            select(SourceFile).where(
                SourceFile.workspace_id == workspace_id,
                SourceFile.blob_id == blob.id,
            ),
        )
        duplicate = source_file is not None
        if source_file is None:
            source_file = SourceFile(
                workspace_id=workspace_id,
                blob_id=blob.id,
                original_name=safe_name,
                file_kind=file_kind.value,
                status="ready",
            )
            session.add(source_file)
            session.flush()

    return RegisteredSourceFile(source_file=source_file, blob=blob, duplicate=duplicate)


def get_source_file(
    session: Session,
    *,
    workspace_id: UUID,
    source_file_id: UUID,
) -> tuple[SourceFile, FileBlob] | None:
    source_file = session.get(SourceFile, source_file_id)
    if source_file is None or source_file.workspace_id != workspace_id:
        return None
    blob = session.get(FileBlob, source_file.blob_id)
    if blob is None:
        return None
    return source_file, blob


def normalize_source_filename(original_name: str | None) -> str:
    if original_name is None:
        raise InvalidSourceFilenameError("A source filename is required")
    normalized = original_name.replace("\\", "/")
    safe_name = PurePosixPath(normalized).name.strip()
    if not safe_name or safe_name in {".", ".."}:
        raise InvalidSourceFilenameError("A valid source filename is required")
    if len(safe_name) > 255:
        raise InvalidSourceFilenameError("Source filename exceeds 255 characters")
    return safe_name


def source_file_kind(filename: str) -> FileKind:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".csv":
        return FileKind.CSV
    if suffix == ".xlsx":
        return FileKind.XLSX
    if suffix in {".xls", ".xlsm"}:
        raise UnsupportedSourceFileError(
            "Legacy or macro-enabled Excel files must be converted to .xlsx",
        )
    raise UnsupportedSourceFileError("Only .csv and .xlsx source files are supported")


def source_file_media_type(file_kind: FileKind) -> str:
    if file_kind is FileKind.CSV:
        return CSV_MEDIA_TYPE
    return XLSX_MEDIA_TYPE


def validate_source_content(
    stream: BinaryIO,
    *,
    file_kind: FileKind,
    xlsx_max_uncompressed_bytes: int,
    xlsx_max_compression_ratio: float,
) -> None:
    stream.seek(0)
    try:
        if file_kind is FileKind.CSV:
            sample = stream.read(8192)
            if b"\x00" in sample:
                raise InvalidSourceContentError("CSV content contains binary null bytes")
            return

        _validate_xlsx_archive(
            stream,
            max_uncompressed_bytes=xlsx_max_uncompressed_bytes,
            max_compression_ratio=xlsx_max_compression_ratio,
        )
    finally:
        stream.seek(0)


def _validate_xlsx_archive(
    stream: BinaryIO,
    *,
    max_uncompressed_bytes: int,
    max_compression_ratio: float,
) -> None:
    try:
        with ZipFile(stream) as archive:
            entries = archive.infolist()
            names = {entry.filename for entry in entries}
            required = {"[Content_Types].xml", "xl/workbook.xml"}
            if not required.issubset(names):
                raise InvalidSourceContentError("XLSX workbook structure is incomplete")
            if "xl/vbaProject.bin" in names:
                raise InvalidSourceContentError("Macro-enabled workbooks are not supported")
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise InvalidSourceContentError("Encrypted workbooks are not supported")

            uncompressed_bytes = sum(entry.file_size for entry in entries)
            compressed_bytes = sum(entry.compress_size for entry in entries)
            if uncompressed_bytes > max_uncompressed_bytes:
                raise InvalidSourceContentError("XLSX expanded size exceeds the configured limit")
            compression_ratio = uncompressed_bytes / max(compressed_bytes, 1)
            if compression_ratio > max_compression_ratio:
                raise InvalidSourceContentError("XLSX compression ratio exceeds the safe limit")
    except BadZipFile as exc:
        raise InvalidSourceContentError("XLSX content is not a valid ZIP workbook") from exc
