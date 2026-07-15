import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from bi_system.ingestion.domain import FileDataType, QualitySeverity
from bi_system.ingestion.template_contracts import (
    BusinessKeyRule,
    DataTypeRule,
    EnumRule,
    ImportColumnMapping,
    ImportTemplateDefinition,
    LengthRule,
    QualityRuleDefinition,
    RangeRule,
    RegexRule,
    RequiredRule,
    UniqueRule,
)

ConvertedValue = str | int | Decimal | bool | date | datetime | None


@dataclass(frozen=True, slots=True)
class RowIssue:
    row_number: int
    column_name: str | None
    severity: QualitySeverity
    code: str
    message: str
    raw_value: str | None


@dataclass(frozen=True, slots=True)
class EvaluatedRow:
    row_number: int
    values: dict[str, ConvertedValue]
    issues: tuple[RowIssue, ...]
    accepted: bool


class QualityEvaluator:
    def __init__(
        self,
        definition: ImportTemplateDefinition,
        *,
        warnings_confirmed: bool,
    ) -> None:
        self.definition = definition
        self.warnings_confirmed = warnings_confirmed
        self._unique_values: dict[str, set[object]] = {}
        self._business_keys: dict[str, set[tuple[object, ...]]] = {}

    def evaluate(self, row: tuple[object, ...], *, row_number: int) -> EvaluatedRow:
        raw_values = {
            column.target_name: _source_value(row, column) for column in self.definition.columns
        }
        converted_values: dict[str, ConvertedValue] = {}
        issues: list[RowIssue] = []

        for column in self.definition.columns:
            raw_value = raw_values[column.target_name]
            if _is_blank(raw_value):
                converted_values[column.target_name] = None
                if not column.nullable:
                    issues.append(
                        _issue(
                            row_number,
                            column.target_name,
                            QualitySeverity.ERROR,
                            "required",
                            f"{column.source_name} is required",
                            raw_value,
                        ),
                    )
                continue

            try:
                converted_values[column.target_name] = _convert_value(raw_value, column.data_type)
            except (TypeError, ValueError, InvalidOperation):
                converted_values[column.target_name] = None
                issues.append(
                    _issue(
                        row_number,
                        column.target_name,
                        QualitySeverity.ERROR,
                        "invalid_type",
                        f"{column.source_name} is not a valid {column.data_type.value}",
                        raw_value,
                    ),
                )

        for rule in self.definition.quality_rules:
            issues.extend(
                self._evaluate_rule(
                    rule,
                    row_number=row_number,
                    raw_values=raw_values,
                    converted_values=converted_values,
                ),
            )

        if self.definition.business_key:
            issues.extend(
                self._evaluate_business_key(
                    self.definition.business_key,
                    row_number=row_number,
                    raw_values=raw_values,
                    converted_values=converted_values,
                ),
            )

        deduplicated_issues = tuple(
            {(issue.column_name, issue.severity, issue.code): issue for issue in issues}.values(),
        )
        has_error = any(issue.severity is QualitySeverity.ERROR for issue in deduplicated_issues)
        has_unconfirmed_warning = not self.warnings_confirmed and any(
            issue.severity is QualitySeverity.WARNING for issue in deduplicated_issues
        )
        return EvaluatedRow(
            row_number=row_number,
            values=converted_values,
            issues=deduplicated_issues,
            accepted=not has_error and not has_unconfirmed_warning,
        )

    def _evaluate_rule(
        self,
        rule: QualityRuleDefinition,
        *,
        row_number: int,
        raw_values: dict[str, object],
        converted_values: dict[str, ConvertedValue],
    ) -> list[RowIssue]:
        if isinstance(rule, BusinessKeyRule):
            return self._evaluate_business_key(
                rule.parameters.columns,
                row_number=row_number,
                raw_values=raw_values,
                converted_values=converted_values,
                severity=rule.severity,
                code="business_key_duplicate",
                rule_name=rule.name,
                tracker_name=f"rule:{rule.name}",
            )

        column_name = rule.column_name
        if column_name is None:
            return []
        raw_value = raw_values[column_name]
        converted_value = converted_values[column_name]
        if (
            converted_value is None
            and not _is_blank(raw_value)
            and isinstance(rule, (DataTypeRule, RangeRule, EnumRule, UniqueRule))
        ):
            return []

        if isinstance(rule, RequiredRule):
            failed = _is_blank(raw_value)
        elif isinstance(rule, DataTypeRule):
            failed = not _is_blank(raw_value) and not _matches_type(
                converted_value,
                rule.parameters.expected_type,
            )
        elif isinstance(rule, LengthRule):
            length = len(str(raw_value)) if not _is_blank(raw_value) else None
            failed = length is not None and (
                (rule.parameters.minimum is not None and length < rule.parameters.minimum)
                or (rule.parameters.maximum is not None and length > rule.parameters.maximum)
            )
        elif isinstance(rule, RangeRule):
            failed = _outside_range(
                converted_value,
                minimum=rule.parameters.minimum,
                maximum=rule.parameters.maximum,
            )
        elif isinstance(rule, EnumRule):
            failed = not _is_blank(raw_value) and converted_value not in rule.parameters.values
        elif isinstance(rule, RegexRule):
            failed = (
                not _is_blank(raw_value)
                and re.fullmatch(
                    rule.parameters.pattern,
                    str(raw_value),
                )
                is None
            )
        else:
            failed = self._is_duplicate(rule.name, converted_value)

        if not failed:
            return []
        return [
            _issue(
                row_number,
                column_name,
                rule.severity,
                rule.rule_type,
                f"Quality rule failed: {rule.name}",
                raw_value,
            ),
        ]

    def _is_duplicate(self, rule_name: str, value: ConvertedValue) -> bool:
        if value is None:
            return False
        seen = self._unique_values.setdefault(rule_name, set())
        if value in seen:
            return True
        seen.add(value)
        return False

    def _evaluate_business_key(
        self,
        columns: list[str],
        *,
        row_number: int,
        raw_values: dict[str, object],
        converted_values: dict[str, ConvertedValue],
        severity: QualitySeverity = QualitySeverity.ERROR,
        code: str = "business_key_duplicate",
        rule_name: str = "business key",
        tracker_name: str = "definition",
    ) -> list[RowIssue]:
        key = tuple(converted_values[column] for column in columns)
        if any(value is None for value in key):
            return []
        seen_keys = self._business_keys.setdefault(tracker_name, set())
        if key not in seen_keys:
            seen_keys.add(key)
            return []
        raw_value = " | ".join(str(raw_values[column]) for column in columns)
        return [
            _issue(
                row_number,
                ",".join(columns),
                severity,
                code,
                f"Quality rule failed: {rule_name}",
                raw_value,
            ),
        ]


def _source_value(row: tuple[object, ...], column: ImportColumnMapping) -> object:
    index = int(column.source_key.removeprefix("column_")) - 1
    return row[index] if index < len(row) else None


def _convert_value(value: object, data_type: FileDataType) -> ConvertedValue:
    if data_type is FileDataType.STRING:
        return str(value)
    if data_type is FileDataType.INTEGER:
        if isinstance(value, bool):
            raise TypeError
        if isinstance(value, int):
            return value
        normalized = str(value).strip()
        if re.fullmatch(r"[+-]?(?:0|[1-9]\d*)", normalized) is None:
            raise ValueError
        return int(normalized)
    if data_type is FileDataType.DECIMAL:
        if isinstance(value, bool):
            raise TypeError
        return Decimal(str(value).strip())
    if data_type is FileDataType.BOOLEAN:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
        raise ValueError
    if data_type is FileDataType.DATE:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value).strip())
    if data_type is FileDataType.DATETIME:
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        return datetime.fromisoformat(str(value).strip())
    raise ValueError


def _matches_type(value: ConvertedValue, expected_type: FileDataType) -> bool:
    if value is None:
        return False
    if expected_type is FileDataType.STRING:
        return isinstance(value, str)
    if expected_type is FileDataType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type is FileDataType.DECIMAL:
        return isinstance(value, Decimal)
    if expected_type is FileDataType.BOOLEAN:
        return isinstance(value, bool)
    if expected_type is FileDataType.DATE:
        return isinstance(value, date) and not isinstance(value, datetime)
    return isinstance(value, datetime)


def _outside_range(
    value: ConvertedValue,
    *,
    minimum: float | None,
    maximum: float | None,
) -> bool:
    if value is None or isinstance(value, (str, bool, date)):
        return False
    numeric_value = Decimal(value) if isinstance(value, int) else value
    return (minimum is not None and numeric_value < Decimal(str(minimum))) or (
        maximum is not None and numeric_value > Decimal(str(maximum))
    )


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _issue(
    row_number: int,
    column_name: str | None,
    severity: QualitySeverity,
    code: str,
    message: str,
    raw_value: object,
) -> RowIssue:
    serialized_value = None if raw_value is None else str(raw_value)[:500]
    return RowIssue(
        row_number=row_number,
        column_name=column_name,
        severity=severity,
        code=code,
        message=message,
        raw_value=serialized_value,
    )
