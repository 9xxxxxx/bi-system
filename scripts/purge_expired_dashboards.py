from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID

from bi_system.core.config import get_settings
from bi_system.dashboards.errors import DashboardServiceError
from bi_system.dashboards.service import DashboardPurgeResult, purge_expired_dashboards
from bi_system.db.session import create_database_engine, create_session_factory
from bi_system.identity import QueryPrincipal
from sqlalchemy.engine import Engine

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def positive_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if not 1 <= parsed <= 1000:
        raise argparse.ArgumentTypeError("limit must be between 1 and 1000")
    return parsed


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Purge expired dashboards in a bounded, workspace-scoped batch",
    )
    parser.add_argument("--workspace-id", type=UUID, required=True)
    parser.add_argument("--actor-user-id", type=UUID, required=True)
    parser.add_argument("--limit", type=positive_limit, default=100)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Permanently delete eligible dashboards; the default is dry-run",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = argument_parser().parse_args(argv)
    engine: Engine | None = None
    try:
        settings = get_settings()
        engine = create_database_engine(settings.database_url)
        session_factory = create_session_factory(engine)
        principal = QueryPrincipal(
            user_id=args.actor_user_id,
            workspace_id=args.workspace_id,
            is_system_admin=True,
        )
        with session_factory() as session:
            result = purge_expired_dashboards(
                session,
                principal=principal,
                limit=args.limit,
                dry_run=not args.execute,
            )
        print(_stable_json(_result_payload(result)))
        return 0
    except DashboardServiceError as exc:
        print(
            _stable_json(
                {
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                    }
                }
            ),
            file=sys.stderr,
        )
        return 1
    except Exception:
        print(
            _stable_json(
                {
                    "error": {
                        "code": "dashboard_purge_failed",
                        "message": "Dashboard purge failed",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


def _result_payload(result: DashboardPurgeResult) -> dict[str, object]:
    return {
        "cutoff": result.cutoff,
        "dry_run": result.dry_run,
        "candidate_ids": result.candidate_ids,
        "eligible_ids": result.eligible_ids,
        "purged_ids": result.purged_ids,
        "blocked": result.blocked,
    }


def _stable_json(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_value(value: object) -> JsonValue:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(nested)
            for key, nested in cast(Mapping[object, object], value).items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(nested) for nested in cast(Sequence[object], value)]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"Unsupported JSON value type: {type(value).__name__}")


if __name__ == "__main__":
    raise SystemExit(main())
