from decimal import Decimal
from uuid import uuid4

import pytest
from bi_system.modeling.metric_contracts import CreateMetric, CreateMetricVersion
from pydantic import ValidationError


def aggregate(field_id: object | None = None) -> dict[str, object]:
    return {
        "op": "aggregate",
        "function": "sum",
        "field_id": field_id or uuid4(),
    }


def metric_payload() -> dict[str, object]:
    return {
        "dataset_id": uuid4(),
        "code": "net_sales",
        "name": " 净销售额 ",
        "description": " 销售额扣除退款后的统一口径 ",
        "formula": aggregate(),
        "unit": " 元 ",
        "dimension_field_ids": [uuid4()],
    }


def test_metric_contract_normalizes_text_and_forbids_extra_input() -> None:
    request = CreateMetric.model_validate(metric_payload())

    assert request.name == "净销售额"
    assert request.description == "销售额扣除退款后的统一口径"
    assert request.unit == "元"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CreateMetric.model_validate({**metric_payload(), "sql": "select secret from raw"})


def test_metric_contract_accepts_safe_division_and_finite_literals() -> None:
    payload = metric_payload()
    payload["formula"] = {
        "op": "safe_divide",
        "numerator": aggregate(),
        "denominator": {
            "op": "aggregate",
            "function": "count_distinct",
            "field_id": uuid4(),
        },
        "fallback": Decimal("0"),
    }

    request = CreateMetric.model_validate(payload)

    assert request.formula.op == "safe_divide"


@pytest.mark.parametrize("operation", ["add", "subtract", "multiply"])
def test_metric_contract_accepts_arithmetic_operations(operation: str) -> None:
    payload = metric_payload()
    payload["formula"] = {
        "op": operation,
        "left": aggregate(),
        "right": {"op": "literal", "value": "1.25"},
    }

    request = CreateMetric.model_validate(payload)

    assert request.formula.op == operation


@pytest.mark.parametrize(
    ("formula", "message"),
    [
        ({"op": "literal", "value": 1}, "must contain at least one aggregate"),
        (
            {
                "op": "safe_divide",
                "numerator": aggregate(),
                "denominator": {"op": "literal", "value": "NaN"},
            },
            "finite number",
        ),
        ({"op": "raw_sql", "sql": "count(*)"}, "Input tag 'raw_sql'"),
    ],
)
def test_metric_contract_rejects_unsafe_or_incomplete_formulas(
    formula: dict[str, object],
    message: str,
) -> None:
    payload = metric_payload()
    payload["formula"] = formula

    with pytest.raises(ValidationError, match=message):
        CreateMetric.model_validate(payload)


def test_metric_contract_rejects_duplicate_dimensions_and_invalid_codes() -> None:
    dimension_id = uuid4()
    payload = metric_payload()
    payload["dimension_field_ids"] = [dimension_id, dimension_id]
    with pytest.raises(ValidationError, match="dimensions must be unique"):
        CreateMetric.model_validate(payload)

    payload = metric_payload()
    payload["code"] = "Net-Sales"
    with pytest.raises(ValidationError, match="String should match pattern"):
        CreateMetric.model_validate(payload)


def test_metric_version_is_partial_but_still_validates_formula() -> None:
    assert CreateMetricVersion().formula is None
    with pytest.raises(ValidationError, match="must contain at least one aggregate"):
        CreateMetricVersion.model_validate({"formula": {"op": "literal", "value": 1}})
