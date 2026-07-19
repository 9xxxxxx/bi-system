from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from bi_system.dashboards.errors import DashboardForbiddenError
from sqlalchemy.exc import SQLAlchemyError

from scripts import purge_expired_dashboards as purge_cli

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000002")
CANDIDATE_ID = UUID("00000000-0000-0000-0000-000000000003")
ELIGIBLE_ID = UUID("00000000-0000-0000-0000-000000000004")
BLOCKED_ID = UUID("00000000-0000-0000-0000-000000000005")
TEMPLATE_ID = UUID("00000000-0000-0000-0000-000000000006")
TEMPLATE_VERSION_ID = UUID("00000000-0000-0000-0000-000000000007")
CUTOFF = datetime(2026, 6, 19, 10, 30, tzinfo=UTC)
REQUIRED_ARGUMENTS = (
    "--workspace-id",
    str(WORKSPACE_ID),
    "--actor-user-id",
    str(ACTOR_ID),
)


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    template_id: UUID
    template_name: str
    template_version_id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class BlockResult:
    dashboard_id: UUID
    references: tuple[ReferenceResult, ...]


@dataclass(frozen=True, slots=True)
class PurgeResult:
    cutoff: datetime
    dry_run: bool
    candidate_ids: tuple[UUID, ...]
    eligible_ids: tuple[UUID, ...]
    purged_ids: tuple[UUID, ...]
    blocked: tuple[BlockResult, ...]


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def install_runtime(
    monkeypatch: pytest.MonkeyPatch,
    service: Any,
) -> tuple[FakeEngine, object]:
    engine = FakeEngine()
    session = object()
    monkeypatch.setattr(
        purge_cli,
        "get_settings",
        lambda: SimpleNamespace(database_url="sqlite+pysqlite:///:memory:"),
    )

    def create_engine(_url: str) -> FakeEngine:
        return engine

    def create_factory(_engine: object) -> Any:
        return lambda: nullcontext(session)

    monkeypatch.setattr(purge_cli, "create_database_engine", create_engine)
    monkeypatch.setattr(
        purge_cli,
        "create_session_factory",
        create_factory,
    )
    monkeypatch.setattr(purge_cli, "purge_expired_dashboards", service)
    return engine, session


def test_default_is_dry_run_and_outputs_stable_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def service(session: object, **kwargs: object) -> PurgeResult:
        captured.update(kwargs)
        captured["session"] = session
        return PurgeResult(
            cutoff=CUTOFF,
            dry_run=True,
            candidate_ids=(CANDIDATE_ID, BLOCKED_ID),
            eligible_ids=(ELIGIBLE_ID,),
            purged_ids=(),
            blocked=(
                BlockResult(
                    dashboard_id=BLOCKED_ID,
                    references=(
                        ReferenceResult(
                            template_id=TEMPLATE_ID,
                            template_name="销售模板",
                            template_version_id=TEMPLATE_VERSION_ID,
                            version=3,
                        ),
                    ),
                ),
            ),
        )

    engine, session = install_runtime(monkeypatch, service)

    assert purge_cli.main(REQUIRED_ARGUMENTS) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {
        "blocked": [
            {
                "dashboard_id": str(BLOCKED_ID),
                "references": [
                    {
                        "template_id": str(TEMPLATE_ID),
                        "template_name": "销售模板",
                        "template_version_id": str(TEMPLATE_VERSION_ID),
                        "version": 3,
                    }
                ],
            }
        ],
        "candidate_ids": [str(CANDIDATE_ID), str(BLOCKED_ID)],
        "cutoff": CUTOFF.isoformat(),
        "dry_run": True,
        "eligible_ids": [str(ELIGIBLE_ID)],
        "purged_ids": [],
    }
    assert captured["session"] is session
    assert captured["limit"] == 100
    assert captured["dry_run"] is True
    principal = captured["principal"]
    assert isinstance(principal, purge_cli.QueryPrincipal)
    assert principal.user_id == ACTOR_ID
    assert principal.workspace_id == WORKSPACE_ID
    assert principal.is_system_admin is True
    assert engine.disposed is True


def test_execute_passes_bounded_delete_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def service(_session: object, **kwargs: object) -> PurgeResult:
        captured.update(kwargs)
        return PurgeResult(
            cutoff=CUTOFF,
            dry_run=False,
            candidate_ids=(ELIGIBLE_ID,),
            eligible_ids=(ELIGIBLE_ID,),
            purged_ids=(ELIGIBLE_ID,),
            blocked=(),
        )

    engine, _session = install_runtime(monkeypatch, service)

    assert purge_cli.main([*REQUIRED_ARGUMENTS, "--limit", "7", "--execute"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert captured["limit"] == 7
    assert captured["dry_run"] is False
    assert output["dry_run"] is False
    assert output["purged_ids"] == [str(ELIGIBLE_ID)]
    assert engine.disposed is True


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_message"),
    [
        (
            DashboardForbiddenError("dashboard_purge_forbidden", "Purge denied"),
            "dashboard_purge_forbidden",
            "Purge denied",
        ),
        (RuntimeError("internal detail"), "dashboard_purge_failed", "Dashboard purge failed"),
        (SQLAlchemyError("sql detail"), "dashboard_purge_failed", "Dashboard purge failed"),
    ],
)
def test_service_and_runtime_errors_return_one_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    expected_code: str,
    expected_message: str,
) -> None:
    def service(_session: object, **_kwargs: object) -> PurgeResult:
        raise error

    engine, _session = install_runtime(monkeypatch, service)

    assert purge_cli.main(REQUIRED_ARGUMENTS) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": {"code": expected_code, "message": expected_message}}
    assert "internal detail" not in output.err
    assert "sql detail" not in output.err
    assert engine.disposed is True


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--workspace-id", str(WORKSPACE_ID)],
        [
            "--workspace-id",
            "not-a-uuid",
            "--actor-user-id",
            str(ACTOR_ID),
        ],
        [*REQUIRED_ARGUMENTS, "--limit", "0"],
        [*REQUIRED_ARGUMENTS, "--limit", "1001"],
    ],
)
def test_invalid_arguments_exit_with_argparse_code_two(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as captured:
        purge_cli.main(arguments)
    assert captured.value.code == 2
