from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bi_system.modeling.expression import FilterExpression, predicate_count


class StrictRowPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRowPolicy(StrictRowPolicyModel):
    dataset_id: UUID
    name: str = Field(min_length=1, max_length=128)
    effect: Literal["allow", "deny"] = "allow"
    expression: FilterExpression

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Row policy name must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_complexity(self) -> "CreateRowPolicy":
        if predicate_count(self.expression) > 50:
            raise ValueError("Row policy may contain at most 50 predicates")
        return self


class CreateRowPolicyVersion(StrictRowPolicyModel):
    effect: Literal["allow", "deny"] | None = None
    expression: FilterExpression | None = None

    @model_validator(mode="after")
    def validate_complexity(self) -> "CreateRowPolicyVersion":
        if self.expression is not None and predicate_count(self.expression) > 50:
            raise ValueError("Row policy may contain at most 50 predicates")
        return self


class ReplaceRowPolicyBindings(StrictRowPolicyModel):
    user_ids: list[UUID] = Field(default_factory=list, max_length=500)
    role_ids: list[UUID] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_unique_principals(self) -> "ReplaceRowPolicyBindings":
        if len(set(self.user_ids)) != len(self.user_ids):
            raise ValueError("Row policy users must be unique")
        if len(set(self.role_ids)) != len(self.role_ids):
            raise ValueError("Row policy roles must be unique")
        return self
