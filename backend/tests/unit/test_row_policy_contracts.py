from uuid import uuid4

import pytest
from bi_system.modeling.row_policy_contracts import (
    CreateRowPolicy,
    CreateRowPolicyVersion,
    ReplaceRowPolicyBindings,
)
from pydantic import ValidationError


def _expression() -> dict[str, object]:
    return {
        "kind": "comparison",
        "field_id": uuid4(),
        "operator": "eq",
        "value": "华东",
    }


def test_row_policy_contract_normalizes_name_and_forbids_extra_input() -> None:
    request = CreateRowPolicy.model_validate(
        {
            "dataset_id": uuid4(),
            "name": " 华东数据范围 ",
            "effect": "allow",
            "expression": _expression(),
        }
    )

    assert request.name == "华东数据范围"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CreateRowPolicy.model_validate(
            {
                "dataset_id": uuid4(),
                "name": "危险策略",
                "expression": _expression(),
                "sql": "region = current_user",
            }
        )


def test_row_policy_version_is_partial_and_cannot_set_status() -> None:
    assert CreateRowPolicyVersion().expression is None
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CreateRowPolicyVersion.model_validate({"status": "active"})


def test_row_policy_bindings_require_unique_principals() -> None:
    user_id = uuid4()
    role_id = uuid4()

    with pytest.raises(ValidationError, match="users must be unique"):
        ReplaceRowPolicyBindings(user_ids=[user_id, user_id])
    with pytest.raises(ValidationError, match="roles must be unique"):
        ReplaceRowPolicyBindings(role_ids=[role_id, role_id])
