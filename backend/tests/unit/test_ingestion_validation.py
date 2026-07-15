from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

from bi_system.ingestion.template_contracts import ImportTemplateDefinition
from bi_system.ingestion.validation import QualityEvaluator


def definition_with_rules(*rules: Mapping[str, object]) -> ImportTemplateDefinition:
    return ImportTemplateDefinition.model_validate(
        {
            "file_kind": "csv",
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
                {
                    "source_key": "column_3",
                    "source_name": "日期",
                    "target_name": "report_date",
                    "data_type": "date",
                },
                {
                    "source_key": "column_4",
                    "source_name": "启用",
                    "target_name": "enabled",
                    "data_type": "boolean",
                },
            ],
            "business_key": ["city", "report_date"],
            "quality_rules": list(rules),
        },
    )


def test_evaluator_converts_supported_types() -> None:
    evaluator = QualityEvaluator(definition_with_rules(), warnings_confirmed=False)

    evaluated = evaluator.evaluate(
        ("北京", "12.50", "2026-07-15", "yes"),
        row_number=2,
    )

    assert evaluated.accepted is True
    assert evaluated.issues == ()
    assert evaluated.values == {
        "city": "北京",
        "amount": Decimal("12.50"),
        "report_date": date(2026, 7, 15),
        "enabled": True,
    }


def test_evaluator_reports_required_and_type_errors() -> None:
    evaluator = QualityEvaluator(definition_with_rules(), warnings_confirmed=True)

    evaluated = evaluator.evaluate(("", "not-number", "bad-date", "maybe"), row_number=3)

    assert evaluated.accepted is False
    assert [issue.code for issue in evaluated.issues] == [
        "required",
        "invalid_type",
        "invalid_type",
        "invalid_type",
    ]


def test_warning_requires_confirmation_before_row_is_accepted() -> None:
    range_rule: Mapping[str, object] = {
        "name": "金额范围",
        "rule_type": "range",
        "severity": "warning",
        "column_name": "amount",
        "parameters": {"maximum": 100},
    }
    definition = definition_with_rules(range_rule)

    blocked = QualityEvaluator(definition, warnings_confirmed=False).evaluate(
        ("北京", "200", "2026-07-15", "true"),
        row_number=2,
    )
    accepted = QualityEvaluator(definition, warnings_confirmed=True).evaluate(
        ("北京", "200", "2026-07-15", "true"),
        row_number=2,
    )

    assert blocked.accepted is False
    assert blocked.issues[0].severity.value == "warning"
    assert accepted.accepted is True


def test_evaluator_applies_length_enum_and_regex_rules() -> None:
    rules: tuple[Mapping[str, object], ...] = (
        {
            "name": "城市长度",
            "rule_type": "length",
            "severity": "error",
            "column_name": "city",
            "parameters": {"maximum": 2},
        },
        {
            "name": "城市枚举",
            "rule_type": "enum",
            "severity": "error",
            "column_name": "city",
            "parameters": {"values": ["北京", "上海"]},
        },
        {
            "name": "城市格式",
            "rule_type": "regex",
            "severity": "error",
            "column_name": "city",
            "parameters": {"pattern": "北京|上海"},
        },
    )
    evaluator = QualityEvaluator(definition_with_rules(*rules), warnings_confirmed=True)

    evaluated = evaluator.evaluate(("广州市", "10", "2026-07-15", "true"), row_number=2)

    assert evaluated.accepted is False
    assert [issue.code for issue in evaluated.issues] == ["length", "enum", "regex"]


def test_evaluator_detects_unique_and_business_key_duplicates() -> None:
    unique_rule: Mapping[str, object] = {
        "name": "城市唯一",
        "rule_type": "unique",
        "severity": "error",
        "column_name": "city",
        "parameters": {},
    }
    evaluator = QualityEvaluator(definition_with_rules(unique_rule), warnings_confirmed=True)
    row = ("北京", "10", datetime(2026, 7, 15), "true")

    first = evaluator.evaluate(row, row_number=2)
    second = evaluator.evaluate(row, row_number=3)

    assert first.accepted is True
    assert second.accepted is False
    assert [issue.code for issue in second.issues] == ["unique", "business_key_duplicate"]


def test_issue_raw_value_is_bounded() -> None:
    regex_rule: Mapping[str, object] = {
        "name": "格式",
        "rule_type": "regex",
        "severity": "error",
        "column_name": "city",
        "parameters": {"pattern": "北京"},
    }
    evaluator = QualityEvaluator(definition_with_rules(regex_rule), warnings_confirmed=True)

    evaluated = evaluator.evaluate(("x" * 1000, "10", "2026-07-15", "true"), row_number=2)

    assert evaluated.issues[0].raw_value is not None
    assert len(evaluated.issues[0].raw_value) == 500
