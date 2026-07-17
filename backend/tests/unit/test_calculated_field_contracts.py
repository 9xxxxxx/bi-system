from decimal import Decimal
from uuid import uuid4

import pytest
from bi_system.modeling.calculated_field_contracts import (
    CreateCalculatedField,
    calculated_expression_field_ids,
    rewrite_calculated_expression_fields,
)
from pydantic import ValidationError


def request_payload() -> dict[str, object]:
    amount_id = uuid4()
    target_id = uuid4()
    return {
        "name": "achievement_rate",
        "label": " Achievement rate ",
        "role": "measure",
        "data_type": "decimal",
        "hidden": False,
        "expression": {
            "op": "case",
            "when": {
                "kind": "comparison",
                "field_id": str(target_id),
                "operator": "gt",
                "value": 0,
            },
            "then": {
                "op": "safe_divide",
                "numerator": {"op": "field", "field_id": str(amount_id)},
                "denominator": {"op": "field", "field_id": str(target_id)},
                "fallback": 0,
            },
            "else": {"op": "literal", "value": None},
        },
    }


def test_calculated_field_contract_accepts_frozen_case_shape() -> None:
    request = CreateCalculatedField.model_validate(request_payload())

    assert request.label == "Achievement rate"
    assert request.expression.op == "case"
    serialized = request.expression.model_dump(mode="json", by_alias=True)
    assert "else" in serialized
    assert "else_" not in serialized
    assert len(calculated_expression_field_ids(request.expression)) == 2


@pytest.mark.parametrize(
    "expression",
    [
        {"op": "sql", "value": "select secret from raw"},
        {"op": "function", "name": "random", "arguments": []},
        {"op": "literal", "value": Decimal("NaN")},
    ],
)
def test_calculated_field_contract_rejects_sql_functions_and_nonfinite_values(
    expression: dict[str, object],
) -> None:
    payload = request_payload()
    payload["expression"] = expression

    with pytest.raises(ValidationError):
        CreateCalculatedField.model_validate(payload)


def test_calculated_field_contract_limits_depth_and_nodes() -> None:
    expression: dict[str, object] = {"op": "field", "field_id": str(uuid4())}
    for _index in range(8):
        expression = {
            "op": "add",
            "left": expression,
            "right": {"op": "literal", "value": 1},
        }
    payload = request_payload()
    payload["expression"] = expression

    with pytest.raises(ValidationError, match="8 levels"):
        CreateCalculatedField.model_validate(payload)

    leaves: list[dict[str, object]] = [
        {"op": "field", "field_id": str(uuid4())} for _index in range(26)
    ]
    while len(leaves) > 1:
        left = leaves.pop()
        right = leaves.pop()
        leaves.insert(0, {"op": "add", "left": left, "right": right})
    payload["expression"] = leaves[0]
    with pytest.raises(ValidationError, match="50 nodes"):
        CreateCalculatedField.model_validate(payload)


def test_rewrite_updates_expression_and_case_condition_field_ids() -> None:
    request = CreateCalculatedField.model_validate(request_payload())
    source_ids = calculated_expression_field_ids(request.expression)
    field_id_map = {field_id: uuid4() for field_id in source_ids}

    rewritten = rewrite_calculated_expression_fields(request.expression, field_id_map)

    assert calculated_expression_field_ids(rewritten) == frozenset(field_id_map.values())
    with pytest.raises(ValueError, match="missing field"):
        rewrite_calculated_expression_fields(request.expression, {})
