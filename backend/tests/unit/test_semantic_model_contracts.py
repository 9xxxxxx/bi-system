from uuid import uuid4

import pytest
from bi_system.modeling.model_contracts import CreateSemanticModel
from pydantic import ValidationError


def source(alias: str, role: str = "dimension") -> dict[str, object]:
    return {"target_id": str(uuid4()), "alias": alias, "role": role}


def join(left: str, right: str) -> dict[str, object]:
    return {
        "left_source": left,
        "right_source": right,
        "join_type": "left",
        "cardinality": "many_to_one",
        "keys": [{"left_column_id": str(uuid4()), "right_column_id": str(uuid4())}],
    }


def test_contract_accepts_single_fact_and_compound_join_keys() -> None:
    payload = {
        "name": " Sales model ",
        "sources": [source("sales", "fact"), source("city")],
        "joins": [
            {
                **join("sales", "city"),
                "keys": [
                    {"left_column_id": str(uuid4()), "right_column_id": str(uuid4())},
                    {"left_column_id": str(uuid4()), "right_column_id": str(uuid4())},
                ],
            },
        ],
    }

    request = CreateSemanticModel.model_validate(payload)

    assert request.name == "Sales model"
    assert len(request.joins[0].keys) == 2


@pytest.mark.parametrize(
    "sources",
    [
        [source("sales"), source("city")],
        [source("sales", "fact"), source("city", "fact")],
    ],
)
def test_contract_requires_exactly_one_fact(sources: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError, match="exactly one fact"):
        CreateSemanticModel.model_validate(
            {"name": "Invalid", "sources": sources, "joins": [join("sales", "city")]},
        )


def test_contract_rejects_disconnected_cycle_and_unknown_alias() -> None:
    sources = [
        source("fact", "fact"),
        source("city"),
        source("product"),
        source("channel"),
    ]
    with pytest.raises(ValidationError, match="connected acyclic"):
        CreateSemanticModel.model_validate(
            {
                "name": "Disconnected",
                "sources": sources,
                "joins": [
                    join("fact", "city"),
                    join("city", "product"),
                    join("product", "fact"),
                ],
            },
        )

    with pytest.raises(ValidationError, match="must exist"):
        CreateSemanticModel.model_validate(
            {
                "name": "Unknown alias",
                "sources": [source("fact", "fact"), source("city")],
                "joins": [join("fact", "missing")],
            },
        )


def test_contract_limits_sources_to_eight() -> None:
    sources = [source("fact", "fact"), *[source(f"dim_{index}") for index in range(8)]]

    with pytest.raises(ValidationError):
        CreateSemanticModel.model_validate({"name": "Too wide", "sources": sources})
