# pyright: reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false
from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

try:
    from bi_system.dashboards.contracts import SaveDashboardVersion
except ModuleNotFoundError as error:
    if error.name != "bi_system.dashboards.service":
        raise
    pytest.skip("M3-R1 dashboard service is not available yet", allow_module_level=True)


def _valid_version_payload() -> dict[str, Any]:
    page_id = str(uuid4())
    component_id = str(uuid4())
    desktop_item = {
        "component_id": component_id,
        "x": 0,
        "y": 0,
        "width": 6,
        "height": 4,
        "min_width": 2,
        "min_height": 2,
    }
    return {
        "base_version": 1,
        "expected_revision": 1,
        "pages": [{"page_id": page_id, "title": "经营总览", "ordinal": 0}],
        "components": [
            {
                "component_id": component_id,
                "page_id": page_id,
                "component_type": "rich_text",
                "config_version": 1,
                "config": {"schema_version": 1, "content": []},
            }
        ],
        "layouts": [
            {"profile": "desktop", "items": [desktop_item]},
            {
                "profile": "mobile",
                "items": [
                    {
                        **desktop_item,
                        "width": 4,
                        "min_width": 1,
                    }
                ],
            },
        ],
    }


def test_dashboard_version_schema_accepts_complete_aggregate() -> None:
    request = SaveDashboardVersion.model_validate(_valid_version_payload())

    assert request.base_version == 1
    assert request.expected_revision == 1
    assert {layout.profile for layout in request.layouts} == {"desktop", "mobile"}


def test_dashboard_version_schema_rejects_unknown_component_config_version() -> None:
    payload = _valid_version_payload()
    payload["components"][0]["config_version"] = 2

    with pytest.raises(ValidationError, match="config_version"):
        SaveDashboardVersion.model_validate(payload)


def test_dashboard_version_schema_rejects_duplicate_layout_profile() -> None:
    payload = _valid_version_payload()
    payload["layouts"][1] = deepcopy(payload["layouts"][0])

    with pytest.raises(ValidationError, match="profile"):
        SaveDashboardVersion.model_validate(payload)


def test_dashboard_version_schema_rejects_duplicate_layout_item() -> None:
    payload = _valid_version_payload()
    desktop_items = payload["layouts"][0]["items"]
    desktop_items.append(deepcopy(desktop_items[0]))

    with pytest.raises(ValidationError, match="duplicate component"):
        SaveDashboardVersion.model_validate(payload)


def test_dashboard_version_schema_rejects_dangling_page_reference() -> None:
    payload = _valid_version_payload()
    payload["components"][0]["page_id"] = str(uuid4())

    with pytest.raises(ValidationError, match="unknown page"):
        SaveDashboardVersion.model_validate(payload)


def test_dashboard_version_schema_rejects_dangling_component_reference() -> None:
    payload = _valid_version_payload()
    payload["layouts"][0]["items"][0]["component_id"] = str(uuid4())

    with pytest.raises(ValidationError, match="exactly match components"):
        SaveDashboardVersion.model_validate(payload)
