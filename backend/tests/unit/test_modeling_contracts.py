from uuid import uuid4

import pytest
from bi_system.modeling.contracts import DatasetQueryRequest, QueryRequest
from pydantic import ValidationError


def test_query_contract_rejects_raw_sql_and_unknown_operators() -> None:
    field_id = uuid4()

    with pytest.raises(ValidationError):
        QueryRequest.model_validate(
            {
                "source_id": str(uuid4()),
                "selections": [{"field_id": str(field_id), "output_name": "city"}],
                "raw_sql": "DROP TABLE data",
            },
        )

    with pytest.raises(ValidationError):
        QueryRequest.model_validate(
            {
                "source_id": str(uuid4()),
                "selections": [{"field_id": str(field_id), "output_name": "city"}],
                "filter": {
                    "kind": "comparison",
                    "field_id": str(field_id),
                    "operator": "execute",
                    "value": "x",
                },
            },
        )


def test_aggregate_query_requires_exact_group_fields() -> None:
    city_id = uuid4()
    amount_id = uuid4()

    with pytest.raises(ValidationError, match="exactly match group fields"):
        QueryRequest.model_validate(
            {
                "source_id": str(uuid4()),
                "selections": [
                    {"field_id": str(city_id), "output_name": "city"},
                    {
                        "field_id": str(amount_id),
                        "output_name": "total_amount",
                        "aggregate": "sum",
                    },
                ],
            },
        )


def test_sort_expression_must_be_selected() -> None:
    with pytest.raises(ValidationError, match="must also be selected"):
        QueryRequest.model_validate(
            {
                "source_id": str(uuid4()),
                "selections": [{"field_id": str(uuid4()), "output_name": "city"}],
                "order_by": [{"field_id": str(uuid4()), "direction": "desc"}],
            },
        )


def test_dataset_query_accepts_metrics_only_and_grouped_metrics() -> None:
    dataset_id = uuid4()
    metric_id = uuid4()
    city_id = uuid4()

    metrics_only = DatasetQueryRequest.model_validate(
        {
            "dataset_id": dataset_id,
            "metrics": [{"metric_id": metric_id, "output_name": "total_sales"}],
        }
    )
    grouped = DatasetQueryRequest.model_validate(
        {
            "dataset_id": dataset_id,
            "selections": [{"field_id": city_id, "output_name": "city"}],
            "metrics": [{"metric_id": metric_id, "output_name": "total_sales"}],
            "group_by": [city_id],
        }
    )

    assert metrics_only.selections == []
    assert grouped.group_by == [city_id]


def test_dataset_query_requires_output_and_global_unique_names() -> None:
    with pytest.raises(ValidationError, match="at least one field or metric"):
        DatasetQueryRequest(dataset_id=uuid4())

    output_name = "total_sales"
    with pytest.raises(ValidationError, match="output names must be unique"):
        DatasetQueryRequest.model_validate(
            {
                "dataset_id": uuid4(),
                "selections": [{"field_id": uuid4(), "output_name": output_name}],
                "metrics": [{"metric_id": uuid4(), "output_name": output_name}],
                "group_by": [],
            }
        )


def test_dataset_query_rejects_duplicate_metrics_and_metric_sort_shape() -> None:
    metric_id = uuid4()
    with pytest.raises(ValidationError, match="metrics must be unique"):
        DatasetQueryRequest.model_validate(
            {
                "dataset_id": uuid4(),
                "metrics": [
                    {"metric_id": metric_id, "output_name": "metric_one"},
                    {"metric_id": metric_id, "output_name": "metric_two"},
                ],
            }
        )

    with pytest.raises(ValidationError):
        DatasetQueryRequest.model_validate(
            {
                "dataset_id": uuid4(),
                "metrics": [{"metric_id": metric_id, "output_name": "metric_one"}],
                "order_by": [{"metric_id": metric_id, "direction": "desc"}],
            }
        )


def test_grouped_metric_requires_group_fields_as_selections() -> None:
    with pytest.raises(ValidationError, match="exactly match group fields"):
        DatasetQueryRequest.model_validate(
            {
                "dataset_id": uuid4(),
                "metrics": [{"metric_id": uuid4(), "output_name": "total_sales"}],
                "group_by": [uuid4()],
            }
        )
