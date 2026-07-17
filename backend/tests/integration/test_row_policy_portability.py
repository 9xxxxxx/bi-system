import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from bi_system.db.models import (
    Dataset,
    DatasetField,
    Role,
    RowPolicy,
    SemanticModel,
    User,
)
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.modeling.row_policies import (
    activate_row_policy,
    create_row_policy,
    create_row_policy_version,
    replace_row_policy_bindings,
)
from bi_system.modeling.row_policy_contracts import (
    CreateRowPolicy,
    CreateRowPolicyVersion,
    ReplaceRowPolicyBindings,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


def test_row_policy_version_and_activation_are_serialized_on_postgres() -> None:
    database_url = os.environ.get("BI_DATABASE_URL")
    if database_url is None:
        pytest.skip("BI_DATABASE_URL is required for row policy portability checks")
    engine = create_database_engine(database_url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.skip("PostgreSQL is required for row policy concurrency checks")

    session_factory = create_session_factory(engine)
    workspace_id = uuid4()
    try:
        owner_id, role_id, dataset_id, field_id = _seed_resources(
            session_factory,
            workspace_id=workspace_id,
        )
        with session_factory() as session:
            first = create_row_policy(
                session,
                workspace_id=workspace_id,
                actor_user_id=owner_id,
                request=CreateRowPolicy.model_validate(
                    {
                        "dataset_id": dataset_id,
                        "name": f"Portable policy {uuid4().hex}",
                        "expression": {
                            "kind": "comparison",
                            "field_id": field_id,
                            "operator": "eq",
                            "value": "east",
                        },
                    }
                ),
            )
            replace_row_policy_bindings(
                session,
                workspace_id=workspace_id,
                row_policy_id=first.id,
                request=ReplaceRowPolicyBindings(role_ids=[role_id]),
            )
            second = create_row_policy_version(
                session,
                workspace_id=workspace_id,
                actor_user_id=owner_id,
                row_policy_id=first.id,
                request=CreateRowPolicyVersion(),
            )

        create_barrier = Barrier(2)

        def create_concurrently(source_id: UUID) -> tuple[UUID, int]:
            with session_factory() as session:
                create_barrier.wait()
                created = create_row_policy_version(
                    session,
                    workspace_id=workspace_id,
                    actor_user_id=owner_id,
                    row_policy_id=source_id,
                    request=CreateRowPolicyVersion(),
                )
                return created.id, created.version

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(create_concurrently, first.id),
                pool.submit(create_concurrently, second.id),
            ]
            created_versions = [future.result(timeout=20) for future in futures]
        assert {version for _, version in created_versions} == {3, 4}

        activate_barrier = Barrier(2)

        def activate_concurrently(policy_id: UUID) -> None:
            with session_factory() as session:
                activate_barrier.wait()
                activate_row_policy(
                    session,
                    workspace_id=workspace_id,
                    row_policy_id=policy_id,
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(activate_concurrently, policy_id) for policy_id, _ in created_versions
            ]
            for future in futures:
                future.result(timeout=20)

        with session_factory() as session:
            policies = session.scalars(
                select(RowPolicy).where(RowPolicy.series_id == first.series_id)
            ).all()
            assert sum(policy.status == "active" for policy in policies) == 1
    finally:
        engine.dispose()


def _seed_resources(
    session_factory: sessionmaker[Session],
    *,
    workspace_id: UUID,
) -> tuple[UUID, UUID, UUID, UUID]:
    with session_factory.begin() as session:
        owner = User(
            workspace_id=workspace_id,
            username=f"policy-{uuid4().hex}",
            display_name="Row policy portability owner",
            password_hash="not-used-in-test",
        )
        role = Role(
            workspace_id=workspace_id,
            code=f"portable-{uuid4().hex}",
            name=f"Portable role {uuid4().hex}",
            permissions=[],
        )
        session.add_all([owner, role])
        session.flush()
        model = SemanticModel(
            workspace_id=workspace_id,
            name=f"Policy model {uuid4().hex}",
            version=1,
            status="active",
            created_by_user_id=owner.id,
        )
        session.add(model)
        session.flush()
        dataset = Dataset(
            workspace_id=workspace_id,
            semantic_model_id=model.id,
            name=f"Policy dataset {uuid4().hex}",
            version=1,
            status="active",
            created_by_user_id=owner.id,
        )
        session.add(dataset)
        session.flush()
        field = DatasetField(
            dataset_id=dataset.id,
            name="region",
            label="Region",
            field_kind="calculated",
            field_role="dimension",
            data_type="string",
            expression={"op": "literal", "value": ""},
            ordinal=0,
        )
        session.add(field)
        session.flush()
        return owner.id, role.id, dataset.id, field.id
