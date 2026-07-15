from uuid import uuid4

import pytest
from bi_system.modeling.contracts import QueryRequest
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
