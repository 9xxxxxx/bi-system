from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from bi_system.ingestion.domain import ImportMode
from bi_system.ingestion.template_contracts import ImportTemplateDefinition, StrictModel


class CreateImportBatch(StrictModel):
    source_file_id: UUID
    template_id: UUID | None = None
    definition: ImportTemplateDefinition | None = None
    target_id: UUID | None = None
    target_name: str | None = Field(default=None, min_length=1, max_length=128)
    mode: ImportMode
    encoding: Literal["utf-8", "utf-8-sig", "gb18030"] = "utf-8-sig"
    warnings_confirmed: bool = False

    @field_validator("target_name")
    @classmethod
    def normalize_target_name(cls, target_name: str | None) -> str | None:
        if target_name is None:
            return None
        normalized = target_name.strip()
        if not normalized:
            raise ValueError("Target name must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_references(self) -> "CreateImportBatch":
        if (self.template_id is None) == (self.definition is None):
            raise ValueError("Provide exactly one of template_id or definition")
        if (self.target_id is None) == (self.target_name is None):
            raise ValueError("Provide exactly one of target_id or target_name")
        if (
            self.definition is not None
            and self.mode is ImportMode.UPSERT
            and not self.definition.business_key
        ):
            raise ValueError("Upsert imports require a business key")
        return self
