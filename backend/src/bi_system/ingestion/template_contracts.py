import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bi_system.ingestion.domain import FileDataType, FileKind, QualitySeverity

PHYSICAL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyRuleParameters(StrictModel):
    pass


class DataTypeRuleParameters(StrictModel):
    expected_type: FileDataType


class LengthRuleParameters(StrictModel):
    minimum: int | None = Field(default=None, ge=0)
    maximum: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "LengthRuleParameters":
        if self.minimum is None and self.maximum is None:
            raise ValueError("Length rule requires minimum or maximum")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Length minimum must not exceed maximum")
        return self


class RangeRuleParameters(StrictModel):
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "RangeRuleParameters":
        if self.minimum is None and self.maximum is None:
            raise ValueError("Range rule requires minimum or maximum")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Range minimum must not exceed maximum")
        return self


EnumValue = str | int | float | bool


class EnumRuleParameters(StrictModel):
    values: list[EnumValue] = Field(min_length=1, max_length=1000)

    @field_validator("values")
    @classmethod
    def validate_unique_values(cls, values: list[EnumValue]) -> list[EnumValue]:
        serialized = {(type(value).__name__, str(value)) for value in values}
        if len(serialized) != len(values):
            raise ValueError("Enum values must be unique")
        return values


class RegexRuleParameters(StrictModel):
    pattern: str = Field(min_length=1, max_length=256)

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError("Regex pattern is invalid") from exc
        return pattern


class BusinessKeyRuleParameters(StrictModel):
    columns: list[str] = Field(min_length=1, max_length=16)


class QualityRuleBase(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    severity: QualitySeverity
    column_name: str | None = Field(default=None, max_length=63)


class RequiredRule(QualityRuleBase):
    rule_type: Literal["required"]
    parameters: EmptyRuleParameters = Field(default_factory=EmptyRuleParameters)


class UniqueRule(QualityRuleBase):
    rule_type: Literal["unique"]
    parameters: EmptyRuleParameters = Field(default_factory=EmptyRuleParameters)


class DataTypeRule(QualityRuleBase):
    rule_type: Literal["data_type"]
    parameters: DataTypeRuleParameters


class LengthRule(QualityRuleBase):
    rule_type: Literal["length"]
    parameters: LengthRuleParameters


class RangeRule(QualityRuleBase):
    rule_type: Literal["range"]
    parameters: RangeRuleParameters


class EnumRule(QualityRuleBase):
    rule_type: Literal["enum"]
    parameters: EnumRuleParameters


class RegexRule(QualityRuleBase):
    rule_type: Literal["regex"]
    parameters: RegexRuleParameters


class BusinessKeyRule(QualityRuleBase):
    rule_type: Literal["business_key"]
    parameters: BusinessKeyRuleParameters

    @model_validator(mode="after")
    def validate_no_single_column(self) -> "BusinessKeyRule":
        if self.column_name is not None:
            raise ValueError("Business key rules use parameter columns")
        return self


QualityRuleDefinition = Annotated[
    RequiredRule
    | UniqueRule
    | DataTypeRule
    | LengthRule
    | RangeRule
    | EnumRule
    | RegexRule
    | BusinessKeyRule,
    Field(discriminator="rule_type"),
]


class ImportColumnMapping(StrictModel):
    source_key: str = Field(pattern=r"^column_[1-9]\d*$")
    source_name: str = Field(min_length=1, max_length=128)
    target_name: str = Field(min_length=1, max_length=63)
    data_type: FileDataType
    nullable: bool = True

    @field_validator("target_name")
    @classmethod
    def validate_target_name(cls, target_name: str) -> str:
        if PHYSICAL_NAME_PATTERN.fullmatch(target_name) is None:
            raise ValueError("Target name must use lowercase English snake_case")
        return target_name


class ImportTemplateDefinition(StrictModel):
    file_kind: FileKind
    sheet_name: str | None = Field(default=None, max_length=128)
    header_row: int = Field(default=1, ge=1, le=50)
    columns: list[ImportColumnMapping] = Field(min_length=1, max_length=500)
    business_key: list[str] = Field(default_factory=list, max_length=16)
    quality_rules: list[QualityRuleDefinition] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_definition(self) -> "ImportTemplateDefinition":
        if self.file_kind is FileKind.CSV and self.sheet_name is not None:
            raise ValueError("CSV templates cannot select a worksheet")

        source_keys = [column.source_key for column in self.columns]
        target_names = [column.target_name for column in self.columns]
        if len(set(source_keys)) != len(source_keys):
            raise ValueError("Template source keys must be unique")
        if len(set(target_names)) != len(target_names):
            raise ValueError("Template target names must be unique")

        target_name_set = set(target_names)
        if len(set(self.business_key)) != len(self.business_key):
            raise ValueError("Business key columns must be unique")
        missing_business_keys = set(self.business_key) - target_name_set
        if missing_business_keys:
            raise ValueError("Business key columns must exist in template columns")

        rule_names = [rule.name for rule in self.quality_rules]
        if len(set(rule_names)) != len(rule_names):
            raise ValueError("Quality rule names must be unique")
        for rule in self.quality_rules:
            if not isinstance(rule, BusinessKeyRule) and rule.column_name is None:
                raise ValueError(f"Quality rule {rule.name!r} must select a mapped column")
            if rule.column_name is not None and rule.column_name not in target_name_set:
                raise ValueError(f"Quality rule column {rule.column_name!r} is not mapped")
            if isinstance(rule, BusinessKeyRule):
                missing_rule_keys = set(rule.parameters.columns) - target_name_set
                if missing_rule_keys:
                    raise ValueError("Business key rule columns must be mapped")

        return self


class CreateImportTemplate(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    definition: ImportTemplateDefinition
