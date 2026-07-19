# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from typing import Any, cast
from uuid import uuid4

import pytest
from bi_system.dashboards.contracts import (
    CreateDashboardTemplateVersion,
    InstantiateDashboardTemplate,
    SaveDashboardVersion,
)
from pydantic import ValidationError


def valid_payload() -> dict[str, Any]:
    page_id = uuid4()
    component_id = uuid4()
    item = {
        "component_id": component_id,
        "x": 0,
        "y": 0,
        "width": 4,
        "height": 3,
        "min_width": 2,
        "min_height": 2,
    }
    return {
        "base_version": 1,
        "expected_revision": 1,
        "pages": [{"page_id": page_id, "title": "Overview", "ordinal": 0}],
        "components": [
            {
                "component_id": component_id,
                "page_id": page_id,
                "component_type": "kpi",
                "config_version": 1,
                "config": {"schema_version": 1},
            }
        ],
        "layouts": [
            {"profile": "desktop", "items": [item]},
            {"profile": "mobile", "items": [{**item, "width": 4}]},
        ],
    }


def test_dashboard_version_contract_accepts_complete_aggregate() -> None:
    request = SaveDashboardVersion.model_validate(valid_payload())

    assert request.base_version == 1
    assert {layout.profile for layout in request.layouts} == {"desktop", "mobile"}
    assert request.layouts[0].resolved_columns == 12


def test_dashboard_version_contract_rejects_unknown_config_version() -> None:
    payload = valid_payload()
    components = payload["components"]
    assert isinstance(components, list)
    components[0]["config_version"] = 2

    with pytest.raises(ValidationError):
        SaveDashboardVersion.model_validate(payload)


def test_dashboard_version_contract_rejects_duplicate_profiles_and_items() -> None:
    duplicate_profile = valid_payload()
    layouts = duplicate_profile["layouts"]
    assert isinstance(layouts, list)
    layouts[1]["profile"] = "desktop"
    with pytest.raises(ValidationError, match="profiles must be unique"):
        SaveDashboardVersion.model_validate(duplicate_profile)

    duplicate_item = valid_payload()
    layouts = duplicate_item["layouts"]
    assert isinstance(layouts, list)
    items = layouts[0]["items"]
    assert isinstance(items, list)
    items.append(dict(cast(dict[str, Any], items[0])))
    with pytest.raises(ValidationError, match="duplicate component"):
        SaveDashboardVersion.model_validate(duplicate_item)


def test_dashboard_version_contract_rejects_dangling_references() -> None:
    missing_page = valid_payload()
    components = missing_page["components"]
    assert isinstance(components, list)
    components[0]["page_id"] = uuid4()
    with pytest.raises(ValidationError, match="unknown page"):
        SaveDashboardVersion.model_validate(missing_page)

    missing_component = valid_payload()
    layouts = missing_component["layouts"]
    assert isinstance(layouts, list)
    layouts[0]["items"] = []
    with pytest.raises(ValidationError, match="exactly match components"):
        SaveDashboardVersion.model_validate(missing_component)


def test_dashboard_version_contract_rejects_overlap_and_executable_config() -> None:
    overlap = valid_payload()
    pages = overlap["pages"]
    components = overlap["components"]
    layouts = overlap["layouts"]
    assert isinstance(pages, list)
    assert isinstance(components, list)
    assert isinstance(layouts, list)
    second_component = uuid4()
    components.append(
        {
            "component_id": second_component,
            "page_id": pages[0]["page_id"],
            "component_type": "kpi",
            "config_version": 1,
            "config": {},
        }
    )
    for layout in layouts:
        items = layout["items"]
        assert isinstance(items, list)
        items.append({**items[0], "component_id": second_component})
    with pytest.raises(ValidationError, match="must not overlap"):
        SaveDashboardVersion.model_validate(overlap)

    injection = valid_payload()
    components = injection["components"]
    assert isinstance(components, list)
    components[0]["config"] = {"raw_sql": "DROP TABLE dashboards"}
    with pytest.raises(ValidationError, match="forbidden key"):
        SaveDashboardVersion.model_validate(injection)


def test_template_version_and_instantiation_contracts_require_explicit_versions() -> None:
    source_version_id = uuid4()
    template_version_id = uuid4()

    version = CreateDashboardTemplateVersion.model_validate(
        {
            "source_dashboard_version_id": source_version_id,
            "expected_revision": 2,
        }
    )
    instance = InstantiateDashboardTemplate.model_validate(
        {
            "name": "  Regional dashboard  ",
            "description": "  Independent copy  ",
            "template_version_id": template_version_id,
        }
    )

    assert version.source_dashboard_version_id == source_version_id
    assert version.expected_revision == 2
    assert instance.name == "Regional dashboard"
    assert instance.description == "Independent copy"
    assert instance.template_version_id == template_version_id

    with pytest.raises(ValidationError):
        InstantiateDashboardTemplate.model_validate({"name": "Missing version"})
    with pytest.raises(ValidationError):
        CreateDashboardTemplateVersion.model_validate(
            {
                "source_dashboard_version_id": source_version_id,
                "expected_revision": 0,
            }
        )
