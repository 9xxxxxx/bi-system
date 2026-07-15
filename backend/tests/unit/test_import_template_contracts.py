from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest
from bi_system.ingestion.template_contracts import CreateImportTemplate
from pydantic import ValidationError


def valid_template_payload() -> dict[str, Any]:
    return {
        "name": "城市月报",
        "definition": {
            "file_kind": "csv",
            "header_row": 1,
            "columns": [
                {
                    "source_key": "column_1",
                    "source_name": "城市",
                    "target_name": "city",
                    "data_type": "string",
                    "nullable": False,
                },
                {
                    "source_key": "column_2",
                    "source_name": "金额",
                    "target_name": "amount",
                    "data_type": "decimal",
                },
            ],
            "business_key": ["city"],
            "quality_rules": [
                {
                    "name": "城市必填",
                    "rule_type": "required",
                    "severity": "error",
                    "column_name": "city",
                    "parameters": {},
                },
                {
                    "name": "金额范围",
                    "rule_type": "range",
                    "severity": "warning",
                    "column_name": "amount",
                    "parameters": {"minimum": 0, "maximum": 1000000},
                },
            ],
        },
    }


def set_invalid_physical_name(payload: dict[str, Any]) -> None:
    payload["definition"]["columns"][0]["target_name"] = "城市"


def set_csv_worksheet(payload: dict[str, Any]) -> None:
    payload["definition"]["sheet_name"] = "Sheet1"


def set_missing_business_key(payload: dict[str, Any]) -> None:
    payload["definition"]["business_key"] = ["missing"]


def set_duplicate_target_name(payload: dict[str, Any]) -> None:
    payload["definition"]["columns"][1]["target_name"] = "city"


def test_template_contract_accepts_typed_quality_rules() -> None:
    template = CreateImportTemplate.model_validate(valid_template_payload())

    assert template.name == "城市月报"
    assert template.definition.columns[0].target_name == "city"
    parameters = template.definition.quality_rules[1].parameters.model_dump()
    assert parameters["maximum"] == 1000000


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (set_invalid_physical_name, "snake_case"),
        (set_csv_worksheet, "cannot select a worksheet"),
        (set_missing_business_key, "must exist"),
        (set_duplicate_target_name, "must be unique"),
    ],
    ids=["physical-name", "csv-sheet", "business-key", "duplicate-target"],
)
def test_template_contract_rejects_invalid_mapping(
    mutator: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    payload = deepcopy(valid_template_payload())
    mutator(payload)

    with pytest.raises(ValidationError, match=message):
        CreateImportTemplate.model_validate(payload)


def test_template_contract_rejects_unknown_rule_parameters() -> None:
    payload = valid_template_payload()
    rules = payload["definition"]["quality_rules"]
    rules[0]["parameters"] = {"python": "exec('unsafe')"}

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CreateImportTemplate.model_validate(payload)


def test_template_contract_rejects_invalid_regex() -> None:
    payload = valid_template_payload()
    payload["definition"]["quality_rules"] = [
        {
            "name": "坏正则",
            "rule_type": "regex",
            "severity": "error",
            "column_name": "city",
            "parameters": {"pattern": "["},
        },
    ]

    with pytest.raises(ValidationError, match="Regex pattern is invalid"):
        CreateImportTemplate.model_validate(payload)


def test_template_contract_requires_column_for_field_rule() -> None:
    payload = valid_template_payload()
    payload["definition"]["quality_rules"][0]["column_name"] = None

    with pytest.raises(ValidationError, match="must select a mapped column"):
        CreateImportTemplate.model_validate(payload)
