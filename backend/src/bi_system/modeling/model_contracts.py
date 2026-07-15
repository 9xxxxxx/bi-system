from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModelContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRole(StrEnum):
    FACT = "fact"
    DIMENSION = "dimension"


class JoinType(StrEnum):
    INNER = "inner"
    LEFT = "left"


class JoinCardinality(StrEnum):
    ONE_TO_ONE = "one_to_one"
    MANY_TO_ONE = "many_to_one"


class SemanticModelSourceInput(StrictModelContract):
    target_id: UUID
    alias: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    role: SourceRole


class SemanticModelJoinKeyInput(StrictModelContract):
    left_column_id: UUID
    right_column_id: UUID


class SemanticModelJoinInput(StrictModelContract):
    left_source: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    right_source: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    join_type: JoinType
    cardinality: JoinCardinality
    keys: list[SemanticModelJoinKeyInput] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_join(self) -> SemanticModelJoinInput:
        if self.left_source == self.right_source:
            raise ValueError("Join sources must be different")
        key_pairs = [(key.left_column_id, key.right_column_id) for key in self.keys]
        if len(set(key_pairs)) != len(key_pairs):
            raise ValueError("Join key pairs must be unique")
        return self


class CreateSemanticModel(StrictModelContract):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    series_id: UUID | None = None
    sources: list[SemanticModelSourceInput] = Field(min_length=1, max_length=8)
    joins: list[SemanticModelJoinInput] = Field(default_factory=list, max_length=7)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Semantic model name must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_graph(self) -> CreateSemanticModel:
        aliases = [source.alias for source in self.sources]
        alias_set = set(aliases)
        if len(alias_set) != len(aliases):
            raise ValueError("Source aliases must be unique")
        fact_count = sum(source.role is SourceRole.FACT for source in self.sources)
        if fact_count != 1:
            raise ValueError("Semantic model must contain exactly one fact source")

        expected_join_count = len(self.sources) - 1
        if len(self.joins) != expected_join_count:
            raise ValueError("Semantic model joins must form one connected acyclic graph")

        edges: set[frozenset[str]] = set()
        adjacency = {alias: set[str]() for alias in aliases}
        for join in self.joins:
            if join.left_source not in alias_set or join.right_source not in alias_set:
                raise ValueError("Join source aliases must exist in the model")
            edge = frozenset((join.left_source, join.right_source))
            if edge in edges:
                raise ValueError("A source pair may be joined only once")
            edges.add(edge)
            adjacency[join.left_source].add(join.right_source)
            adjacency[join.right_source].add(join.left_source)

        visited: set[str] = set()
        pending = [aliases[0]]
        while pending:
            alias = pending.pop()
            if alias in visited:
                continue
            visited.add(alias)
            pending.extend(adjacency[alias] - visited)
        if visited != alias_set:
            raise ValueError("Semantic model joins must form one connected acyclic graph")
        return self
