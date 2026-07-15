from enum import StrEnum


class FileKind(StrEnum):
    CSV = "csv"
    XLSX = "xlsx"


class ImportMode(StrEnum):
    APPEND = "append"
    UPSERT = "upsert"
    REPLACE = "replace"


class ImportBatchStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QualitySeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class FileDataType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"


class QualityRuleType(StrEnum):
    REQUIRED = "required"
    UNIQUE = "unique"
    DATA_TYPE = "data_type"
    LENGTH = "length"
    RANGE = "range"
    ENUM = "enum"
    REGEX = "regex"
    BUSINESS_KEY = "business_key"


class InvalidImportBatchTransition(ValueError):
    pass


ALLOWED_IMPORT_BATCH_TRANSITIONS: dict[ImportBatchStatus, frozenset[ImportBatchStatus]] = {
    ImportBatchStatus.PENDING: frozenset(
        {ImportBatchStatus.PROCESSING, ImportBatchStatus.CANCELLED},
    ),
    ImportBatchStatus.PROCESSING: frozenset(
        {
            ImportBatchStatus.SUCCEEDED,
            ImportBatchStatus.PARTIALLY_SUCCEEDED,
            ImportBatchStatus.FAILED,
            ImportBatchStatus.CANCELLED,
        },
    ),
    ImportBatchStatus.FAILED: frozenset(
        {ImportBatchStatus.PENDING, ImportBatchStatus.CANCELLED},
    ),
    ImportBatchStatus.SUCCEEDED: frozenset(),
    ImportBatchStatus.PARTIALLY_SUCCEEDED: frozenset(),
    ImportBatchStatus.CANCELLED: frozenset(),
}


def validate_import_batch_transition(
    current: ImportBatchStatus,
    target: ImportBatchStatus,
) -> None:
    if target not in ALLOWED_IMPORT_BATCH_TRANSITIONS[current]:
        msg = f"Import batch cannot transition from {current.value} to {target.value}"
        raise InvalidImportBatchTransition(msg)


def is_terminal_import_batch_status(status: ImportBatchStatus) -> bool:
    return not ALLOWED_IMPORT_BATCH_TRANSITIONS[status]
