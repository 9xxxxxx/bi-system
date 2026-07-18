from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictDashboardModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateDashboard(StrictDashboardModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    template_version_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Dashboard name must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class DashboardPageInput(StrictDashboardModel):
    page_id: UUID
    title: str = Field(min_length=1, max_length=128)
    ordinal: int = Field(ge=0)
    page_filter: dict[str, object] | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Dashboard page title must not be blank")
        return normalized


class DashboardComponentInput(StrictDashboardModel):
    component_id: UUID
    page_id: UUID
    component_type: Literal[
        "kpi",
        "trend_indicator",
        "target_progress",
        "detail_table",
        "ranking_table",
        "bar",
        "horizontal_bar",
        "stacked_bar",
        "line",
        "area",
        "pie",
        "donut",
        "rich_text",
        "image",
    ]
    config_version: Literal[1]
    config: dict[str, object] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def reject_executable_configuration(cls, value: dict[str, object]) -> dict[str, object]:
        forbidden = _find_forbidden_key(value)
        if forbidden is not None:
            raise ValueError(f"Dashboard component config contains forbidden key {forbidden!r}")
        return value


class DashboardLayoutItemInput(StrictDashboardModel):
    component_id: UUID
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    min_width: int = Field(default=1, ge=1)
    min_height: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_minimum_size(self) -> DashboardLayoutItemInput:
        if self.min_width > self.width or self.min_height > self.height:
            raise ValueError("Layout item minimum size must not exceed its current size")
        return self


class DashboardLayoutInput(StrictDashboardModel):
    schema_version: Literal[1] = 1
    profile: Literal["desktop", "mobile"]
    columns: int | None = Field(default=None, ge=1, le=24)
    row_height: int = Field(default=44, ge=1, le=200)
    items: list[DashboardLayoutItemInput] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_items(self) -> DashboardLayoutInput:
        component_ids = [item.component_id for item in self.items]
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("Layout profile contains duplicate component identifiers")
        columns = self.resolved_columns
        if any(item.x + item.width > columns for item in self.items):
            raise ValueError("Layout item exceeds the profile column boundary")
        return self

    @property
    def resolved_columns(self) -> int:
        return (
            self.columns if self.columns is not None else (12 if self.profile == "desktop" else 4)
        )


class SaveDashboardVersion(StrictDashboardModel):
    base_version: int = Field(ge=1)
    expected_revision: int = Field(ge=1)
    global_filter: dict[str, object] | None = None
    pages: list[DashboardPageInput] = Field(max_length=50)
    components: list[DashboardComponentInput] = Field(max_length=100)
    layouts: list[DashboardLayoutInput] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_aggregate_references(self) -> SaveDashboardVersion:
        page_ids = [page.page_id for page in self.pages]
        if len(set(page_ids)) != len(page_ids):
            raise ValueError("Dashboard pages must have unique identifiers")
        ordinals = [page.ordinal for page in self.pages]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("Dashboard pages must have unique ordinals")
        if sorted(ordinals) != list(range(len(ordinals))):
            raise ValueError("Dashboard page ordinals must be contiguous from zero")

        component_ids = [component.component_id for component in self.components]
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("Dashboard components must have unique identifiers")
        known_pages = set(page_ids)
        if any(component.page_id not in known_pages for component in self.components):
            raise ValueError("Dashboard component references an unknown page")

        profiles = [layout.profile for layout in self.layouts]
        if len(set(profiles)) != len(profiles):
            raise ValueError("Dashboard layout profiles must be unique")
        if set(profiles) != {"desktop", "mobile"}:
            raise ValueError("Dashboard versions require desktop and mobile layout profiles")

        expected_components = set(component_ids)
        page_by_component = {
            component.component_id: component.page_id for component in self.components
        }
        for layout in self.layouts:
            layout_components = {item.component_id for item in layout.items}
            if layout_components != expected_components:
                raise ValueError("Dashboard layout references must exactly match components")
            _validate_layout_collisions(layout, page_by_component)
        return self


class DashboardPermissionInput(StrictDashboardModel):
    subject_type: Literal["user", "role", "workspace"]
    subject_id: UUID
    capability: Literal["view", "edit", "share", "export"]


class ReplaceDashboardPermissions(StrictDashboardModel):
    permissions: list[DashboardPermissionInput] = Field(default_factory=list, max_length=500)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_unique_permissions(self) -> ReplaceDashboardPermissions:
        signatures = [
            (item.subject_type, item.subject_id, item.capability) for item in self.permissions
        ]
        if len(set(signatures)) != len(signatures):
            raise ValueError("Dashboard permission grants must be unique")
        return self


class DashboardRevisionRequest(StrictDashboardModel):
    expected_revision: int = Field(ge=1)


class CreateDashboardTemplate(StrictDashboardModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    source_dashboard_version_id: UUID
    visibility: Literal["private", "workspace"] = "private"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Dashboard template name must not be blank")
        return normalized


def _find_forbidden_key(value: object) -> str | None:
    forbidden_keys = {
        "sql",
        "raw_sql",
        "table_name",
        "column_name",
        "physical_table_name",
        "physical_column_name",
        "function",
    }
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        for key, nested in mapping.items():
            if not isinstance(key, str):
                continue
            if key.lower() in forbidden_keys:
                return key
            found = _find_forbidden_key(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in cast(list[object], value):
            found = _find_forbidden_key(nested)
            if found is not None:
                return found
    return None


def _validate_layout_collisions(
    layout: DashboardLayoutInput,
    page_by_component: dict[UUID, UUID],
) -> None:
    for index, left in enumerate(layout.items):
        for right in layout.items[index + 1 :]:
            if page_by_component[left.component_id] != page_by_component[right.component_id]:
                continue
            separated = (
                left.x + left.width <= right.x
                or right.x + right.width <= left.x
                or left.y + left.height <= right.y
                or right.y + right.height <= left.y
            )
            if not separated:
                raise ValueError("Dashboard layout items must not overlap within a page")
