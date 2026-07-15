import pytest
from bi_system.ingestion.domain import (
    ImportBatchStatus,
    InvalidImportBatchTransition,
    is_terminal_import_batch_status,
    validate_import_batch_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ImportBatchStatus.PENDING, ImportBatchStatus.PROCESSING),
        (ImportBatchStatus.PENDING, ImportBatchStatus.CANCELLED),
        (ImportBatchStatus.PROCESSING, ImportBatchStatus.SUCCEEDED),
        (ImportBatchStatus.PROCESSING, ImportBatchStatus.PARTIALLY_SUCCEEDED),
        (ImportBatchStatus.PROCESSING, ImportBatchStatus.FAILED),
        (ImportBatchStatus.FAILED, ImportBatchStatus.PENDING),
    ],
)
def test_import_batch_accepts_supported_transitions(
    current: ImportBatchStatus,
    target: ImportBatchStatus,
) -> None:
    validate_import_batch_transition(current, target)


def test_import_batch_rejects_transition_from_terminal_status() -> None:
    with pytest.raises(InvalidImportBatchTransition, match="succeeded to pending"):
        validate_import_batch_transition(
            ImportBatchStatus.SUCCEEDED,
            ImportBatchStatus.PENDING,
        )


def test_import_batch_terminal_statuses_are_explicit() -> None:
    assert is_terminal_import_batch_status(ImportBatchStatus.SUCCEEDED)
    assert is_terminal_import_batch_status(ImportBatchStatus.PARTIALLY_SUCCEEDED)
    assert is_terminal_import_batch_status(ImportBatchStatus.CANCELLED)
    assert not is_terminal_import_batch_status(ImportBatchStatus.FAILED)
