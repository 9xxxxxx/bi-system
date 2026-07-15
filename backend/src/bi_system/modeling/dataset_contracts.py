from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictDatasetModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDatasetField(StrictDatasetModel):
    model_source_id: UUID
    source_column_id: UUID
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    label: str = Field(min_length=1, max_length=128)
    role: Literal["dimension", "measure"]
    hidden: bool = False

    @field_validator("label")
    @classmethod
    def strip_label(cls, label: str) -> str:
        stripped = label.strip()
        if not stripped:
            raise ValueError("Field label must not be blank")
        return stripped


class DatasetFieldsMixin(StrictDatasetModel):
    @staticmethod
    def validate_fields(fields: list[SourceDatasetField]) -> list[SourceDatasetField]:
        names = [field.name for field in fields]
        if len(set(names)) != len(names):
            raise ValueError("Dataset field names must be unique")
        source_columns = [field.source_column_id for field in fields]
        if len(set(source_columns)) != len(source_columns):
            raise ValueError("Dataset source columns must be unique")
        return fields


class CreateDataset(DatasetFieldsMixin):
    semantic_model_id: UUID
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    fields: list[SourceDatasetField] = Field(min_length=1, max_length=500)

    @field_validator("name")
    @classmethod
    def strip_name(cls, name: str) -> str:
        stripped = name.strip()
        if not stripped:
            raise ValueError("Dataset name must not be blank")
        return stripped

    @field_validator("description")
    @classmethod
    def strip_description(cls, description: str | None) -> str | None:
        if description is None:
            return None
        stripped = description.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_dataset_fields(self) -> "CreateDataset":
        self.validate_fields(self.fields)
        return self


class CreateDatasetVersion(DatasetFieldsMixin):
    fields: list[SourceDatasetField] | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_dataset_fields(self) -> "CreateDatasetVersion":
        if self.fields is not None:
            self.validate_fields(self.fields)
        return self
