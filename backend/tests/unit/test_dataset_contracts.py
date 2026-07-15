from uuid import uuid4

import pytest
from bi_system.modeling.dataset_contracts import (
    CreateDataset,
    CreateDatasetVersion,
    SourceDatasetField,
)
from pydantic import ValidationError


def source_field(*, name: str = "amount") -> SourceDatasetField:
    return SourceDatasetField(
        model_source_id=uuid4(),
        source_column_id=uuid4(),
        name=name,
        label="销售金额",
        role="measure",
    )


def test_create_dataset_normalizes_text_and_rejects_extra_input() -> None:
    request = CreateDataset(
        semantic_model_id=uuid4(),
        name="  销售数据集  ",
        description="  月度经营口径  ",
        fields=[source_field()],
    )

    assert request.name == "销售数据集"
    assert request.description == "月度经营口径"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CreateDataset.model_validate(
            {
                **request.model_dump(),
                "sql": "select * from hidden_table",
            }
        )


def test_dataset_contract_rejects_duplicate_names_and_source_columns() -> None:
    first = source_field()
    duplicate_name = source_field(name=first.name)
    with pytest.raises(ValidationError, match="field names must be unique"):
        CreateDataset(
            semantic_model_id=uuid4(),
            name="销售数据集",
            fields=[first, duplicate_name],
        )

    duplicate_column = source_field(name="net_amount").model_copy(
        update={"source_column_id": first.source_column_id}
    )
    with pytest.raises(ValidationError, match="source columns must be unique"):
        CreateDataset(
            semantic_model_id=uuid4(),
            name="销售数据集",
            fields=[first, duplicate_column],
        )


def test_dataset_version_can_copy_or_replace_fields() -> None:
    assert CreateDatasetVersion().fields is None
    replacement = source_field(name="net_amount")
    assert CreateDatasetVersion(fields=[replacement]).fields == [replacement]
