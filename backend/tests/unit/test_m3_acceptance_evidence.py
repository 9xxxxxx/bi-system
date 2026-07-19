from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import collect_m3_acceptance_evidence as collector

EXPECTED_MATRIX_IDS = {
    *(f"M3-C{index:02d}" for index in range(1, 7)),
    *(f"M3-DB{index:02d}" for index in range(1, 5)),
    *(f"M3-P{index:02d}" for index in range(1, 6)),
    *(f"M3-PERF{index:02d}" for index in range(1, 6)),
    *(f"M3-UI{index:02d}" for index in range(1, 12)),
    *(f"M3-D{index:02d}" for index in range(1, 4)),
    *(f"M3-R{index:02d}" for index in range(1, 7)),
}


def _passing_result(spec: collector.CommandSpec, _repository_root: Path) -> collector.CommandResult:
    return collector.CommandResult(
        key=spec.key,
        command=" ".join(spec.argv),
        cwd=spec.cwd,
        started_at="2026-07-19T00:00:00+00:00",
        duration_seconds=0.01,
        exit_code=0,
        stdout="passed",
        stderr="",
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _runtime_query_payload(
    *,
    dialect: str,
    concurrency: int,
    samples: int,
    scenario_p95_ms: float | None,
) -> dict[str, object]:
    scenario_results = [
        {
            "scenario_name": scenario_name,
            "sample_count": samples,
            "stable": True,
            "fingerprints": [f"fingerprint-{scenario_name}"],
        }
        for scenario_name in (
            "full_kpi",
            "category_bar",
            "category_region_stacked",
            "month_trend",
            "top_2",
            "global_page_component_filters",
            "restricted_viewer_same_group",
        )
    ]
    payload: dict[str, object] = {
        "git_sha": "producer-git-sha",
        "producer_provenance": {
            "head_sha": "producer-git-sha",
            "worktree_state": "clean",
            "source_content_sha256": {"benchmark": "a" * 64},
        },
        "dialect": dialect,
        "rows": 100_000,
        "concurrency": concurrency,
        "iterations": 30 if concurrency == 1 else 3,
        "warmups": 5,
        "warmups_completed": 5,
        "queries_per_request": 7,
        "completed": samples,
        "error_count": 0,
        "timeouts": 0,
        "p95_ms": 6_100 if concurrency == 20 else 3_000,
        "samples": [{"sample_index": index} for index in range(samples)],
        "principal_names": ["administrator", "editor", "restricted_viewer"],
        "scenario_names": [
            "full_kpi",
            "category_bar",
            "category_region_stacked",
            "month_trend",
            "top_2",
            "global_page_component_filters",
            "restricted_viewer_same_group",
        ],
        "scenario_results": scenario_results,
        "rls_isolation": {
            "evaluated": True,
            "isolated": True,
            "fixture_oracle": {
                "trusted": True,
                "canonical_rows_match": True,
            },
        },
        "run_validation": {"valid": True, "issues": []},
        "acceptance": {
            "status": "pass",
            "run_evidence_valid": True,
            "performance_gate_status": "pass",
        },
    }
    if scenario_p95_ms is not None:
        payload["performance_gate"] = {
            "metric": "maximum_representative_scenario_client_p95_ms",
            "observed_ms": scenario_p95_ms,
            "threshold_ms": 5_000,
            "representative_scenario_count": 7,
            "evaluated_scenario_count": 7,
            "missing_scenarios": [],
            "passed": scenario_p95_ms <= 5_000,
        }
    return payload


def _runtime_statuses(index: dict[str, Any]) -> dict[str, str]:
    return {entry["matrix_id"]: entry["status"] for entry in index["artifacts"]}


def test_redact_secrets_covers_urls_headers_and_key_values() -> None:
    source = (
        "postgresql://alice:password123@localhost/db\n"
        "Authorization: Bearer header-token\n"
        "Authorization: Basic dXNlcjpwYXNz\n"
        "https://alice:web-password@example.test/path\n"
        "OPENAI_API_KEY=sk-secret access_token=abc123\n"
        '"refresh_token": "quoted token value"\n'
        "cookie=session-value token=abc secret: xyz password = hidden value"
    )

    redacted = collector.redact_secrets(source)

    assert "password123" not in redacted
    assert "header-token" not in redacted
    assert "dXNlcjpwYXNz" not in redacted
    assert "web-password" not in redacted
    assert "sk-secret" not in redacted
    assert "abc123" not in redacted
    assert "quoted token value" not in redacted
    assert "session-value" not in redacted
    assert "abc" not in redacted
    assert "xyz" not in redacted
    assert "hidden value" not in redacted
    assert "***" in redacted
    assert redacted.count("\n") == source.count("\n")


def test_matrix_ids_cover_the_complete_architecture_acceptance_matrix(tmp_path: Path) -> None:
    index = collector.collect_evidence(
        tmp_path,
        repository_root=collector.REPOSITORY_ROOT,
        specs=(),
        runner=_passing_result,
        git_sha="4a932a5-test",
    )

    assert set(collector.MATRIX_IDS) == EXPECTED_MATRIX_IDS
    assert {artifact["matrix_id"] for artifact in index["artifacts"]} == EXPECTED_MATRIX_IDS


def test_collect_keeps_unexported_values_partial_or_missing(tmp_path: Path) -> None:
    index = collector.collect_evidence(
        tmp_path,
        repository_root=collector.REPOSITORY_ROOT,
        specs=collector.command_specs(),
        runner=_passing_result,
        git_sha="4a932a5-test",
    )

    entries = {entry["matrix_id"]: entry for entry in index["artifacts"]}
    compiler = json.loads((tmp_path / "compiler-golden.json").read_text(encoding="utf-8"))
    parity = json.loads((tmp_path / "db-parity.json").read_text(encoding="utf-8"))

    assert entries["M3-C01"]["status"] == "pass"
    assert entries["M3-C03"]["status"] == "partial"
    assert entries["M3-DB03"]["status"] == "missing"
    assert entries["M3-R06"]["status"] == "pass"
    assert compiler["contains_exported_rows_or_values"] is False
    assert compiler["case_ids"]
    assert parity["status"] == "missing"
    assert index["overall_status"] == "incomplete"
    assert index["security"]["credentials_exported"] is False
    assert index["security"]["output_redaction"] is True
    assert index["security"]["scanned_files"] > 0
    assert index["provenance"]["worktree_state"] in {"clean", "dirty"}
    if index["provenance"]["worktree_state"] == "dirty":
        assert index["provenance"]["worktree_diff_sha256"]
    assert all((tmp_path / entry["artifact"]).exists() for entry in index["artifacts"])
    assert "baseline" in json.loads((tmp_path / "bundle-m3.json").read_text(encoding="utf-8"))
    dependency = json.loads(
        (tmp_path / "dependency-lock-admission.json").read_text(encoding="utf-8")
    )
    assert dependency["production_dependencies"]["gridstack_present"] is False
    assert "command_key=backend_pytest" in (tmp_path / "regression-m0.log").read_text(
        encoding="utf-8"
    )


def test_artifact_digest_binds_all_command_output_and_dual_database_logs(
    tmp_path: Path,
) -> None:
    def collect(target: Path, postgresql_stdout: str) -> dict[str, Any]:
        def runner(
            spec: collector.CommandSpec,
            repository_root: Path,
        ) -> collector.CommandResult:
            result = _passing_result(spec, repository_root)
            if spec.key != "postgresql_runner":
                return result
            return collector.CommandResult(
                key=result.key,
                command=result.command,
                cwd=result.cwd,
                started_at=result.started_at,
                duration_seconds=result.duration_seconds,
                exit_code=result.exit_code,
                stdout=postgresql_stdout,
                stderr=result.stderr,
            )

        index = collector.collect_evidence(
            target,
            repository_root=collector.REPOSITORY_ROOT,
            specs=collector.command_specs(),
            runner=runner,
            git_sha="4a932a5-test",
        )
        return next(entry for entry in index["artifacts"] if entry["matrix_id"] == "M3-DB04")

    first = collect(tmp_path / "first", "postgresql proof one")
    second = collect(tmp_path / "second", "postgresql proof two")

    assert first["sha256"] != second["sha256"]
    assert {item["path"] for item in first["artifact_files"]} == {
        "migration-sqlite.log",
        "migration-postgresql.log",
    }
    assert first["command_results_sha256"] != second["command_results_sha256"]


def test_collect_redacts_runner_output_and_derives_security_scan(tmp_path: Path) -> None:
    def runner(spec: collector.CommandSpec, repository_root: Path) -> collector.CommandResult:
        result = _passing_result(spec, repository_root)
        return collector.CommandResult(
            key=result.key,
            command=f"{result.command} --access_token=command-secret",
            cwd=result.cwd,
            started_at=result.started_at,
            duration_seconds=result.duration_seconds,
            exit_code=result.exit_code,
            stdout="OPENAI_API_KEY=stdout-secret",
            stderr="Authorization: Basic c3RkZXJyOnNlY3JldA==",
        )

    index = collector.collect_evidence(
        tmp_path,
        repository_root=collector.REPOSITORY_ROOT,
        specs=collector.command_specs(),
        runner=runner,
        git_sha="4a932a5-test",
    )
    exported = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tmp_path.iterdir()
        if path.is_file() and path.suffix in {".json", ".log", ".csv"}
    )

    assert "command-secret" not in exported
    assert "stdout-secret" not in exported
    assert "c3RkZXJyOnNlY3JldA==" not in exported
    assert index["security"]["credentials_exported"] is False
    assert index["security"]["output_redaction"] is True


def test_collect_rejects_nonempty_output_directory(tmp_path: Path) -> None:
    existing = tmp_path / "existing.txt"
    existing.write_text("preserve me", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        collector.collect_evidence(
            tmp_path,
            repository_root=collector.REPOSITORY_ROOT,
            specs=(),
            runner=_passing_result,
            git_sha="4a932a5-test",
        )

    assert existing.read_text(encoding="utf-8") == "preserve me"


def test_failed_command_is_not_reported_as_partial(tmp_path: Path) -> None:
    def runner(spec: collector.CommandSpec, repository_root: Path) -> collector.CommandResult:
        result = _passing_result(spec, repository_root)
        if spec.key not in {"compiler_golden", "sqlite_portability"}:
            return result
        return collector.CommandResult(
            key=result.key,
            command=result.command,
            cwd=result.cwd,
            started_at=result.started_at,
            duration_seconds=result.duration_seconds,
            exit_code=1,
            stdout="failed",
            stderr="assertion failure",
        )

    index = collector.collect_evidence(
        tmp_path,
        repository_root=collector.REPOSITORY_ROOT,
        specs=collector.command_specs(),
        runner=runner,
        git_sha="4a932a5-test",
    )
    statuses = {entry["matrix_id"]: entry["status"] for entry in index["artifacts"]}

    assert statuses["M3-C02"] == "partial"
    assert statuses["M3-C03"] == "fail"
    assert statuses["M3-C04"] == "fail"
    assert statuses["M3-DB01"] == "fail"
    assert statuses["M3-P02"] == "fail"


def test_failed_command_takes_precedence_over_missing_command(tmp_path: Path) -> None:
    spec = collector.CommandSpec("sqlite_migrations", ("test",))

    def runner(
        command: collector.CommandSpec,
        _repository_root: Path,
    ) -> collector.CommandResult:
        return collector.CommandResult(
            key=command.key,
            command="test",
            cwd=".",
            started_at="2026-07-19T00:00:00+00:00",
            duration_seconds=0.01,
            exit_code=1,
            stdout="",
            stderr="failed",
        )

    index = collector.collect_evidence(
        tmp_path,
        repository_root=collector.REPOSITORY_ROOT,
        specs=(spec,),
        runner=runner,
        git_sha="4a932a5-test",
    )
    statuses = {entry["matrix_id"]: entry["status"] for entry in index["artifacts"]}

    assert statuses["M3-DB04"] == "fail"


def test_skipped_command_group_is_missing(tmp_path: Path) -> None:
    specs = collector.command_specs(
        include_postgresql=False,
        include_backend_quality=False,
        include_frontend_quality=False,
    )

    index = collector.collect_evidence(
        tmp_path,
        repository_root=collector.REPOSITORY_ROOT,
        specs=specs,
        runner=_passing_result,
        git_sha="4a932a5-test",
    )
    statuses = {entry["matrix_id"]: entry["status"] for entry in index["artifacts"]}

    assert statuses["M3-DB02"] == "missing"
    assert statuses["M3-R04"] == "missing"
    assert statuses["M3-R05"] == "missing"
    assert statuses["M3-R06"] == "missing"
    assert "status=missing" in (tmp_path / "quality-postgresql.log").read_text(encoding="utf-8")


def test_frontend_quality_uses_local_node_24_and_npm_without_npx() -> None:
    specs = collector.command_specs(
        include_postgresql=False,
        include_backend_quality=False,
        include_frontend_quality=True,
    )
    frontend = [spec for spec in specs if spec.key.startswith("frontend_")]
    bundled_root = collector.REPOSITORY_ROOT / ".tmp/m3-node24-npm11/node_modules"
    bundled_node = bundled_root / "node/bin/node.exe"
    bundled_npm = bundled_root / "npm/bin/npm-cli.js"

    assert frontend[0].key == "frontend_node24"
    assert all("npx" not in argument.lower() for spec in frontend for argument in spec.argv)
    if bundled_node.is_file() and bundled_npm.is_file():
        assert frontend[0].argv[0] == str(bundled_node)
        assert all(spec.argv[0] == str(bundled_node) for spec in frontend)
        assert all(spec.argv[1] == str(bundled_npm) for spec in frontend[1:])
    else:
        assert frontend[0].argv[0].lower().startswith("node")
        assert all(spec.argv[0].lower().startswith(("node", "npm")) for spec in frontend)


def test_dependency_evidence_binds_versions_lock_build_and_commit(tmp_path: Path) -> None:
    index = collector.collect_evidence(
        tmp_path,
        repository_root=collector.REPOSITORY_ROOT,
        specs=(),
        runner=_passing_result,
        git_sha="4a932a5-test",
    )
    statuses = {entry["matrix_id"]: entry["status"] for entry in index["artifacts"]}
    dependency = json.loads(
        (tmp_path / "dependency-lock-admission.json").read_text(encoding="utf-8")
    )

    assert statuses["M3-D01"] == "pass"
    assert statuses["M3-D02"] in {"pass", "partial"}
    assert statuses["M3-D03"] in {"pass", "partial"}
    assert dependency["lockfile_versions"] == {
        "echarts": "6.1.0",
        "react-grid-layout": "2.2.3",
        "gridstack": None,
    }
    assert dependency["independent_commit_proof"]["commit_sha"].startswith("f99962b")
    if statuses["M3-D03"] == "pass":
        assert dependency["independent_commit_proof"]["verified"] is True


def test_parse_args_accepts_optional_runtime_evidence_root(tmp_path: Path) -> None:
    evidence_root = tmp_path / "source"
    output_dir = tmp_path / "output"

    args = collector.parse_args(
        ["--output-dir", str(output_dir), "--evidence-root", str(evidence_root)]
    )

    assert args.evidence_root == evidence_root


def test_runtime_performance_ingest_preserves_source_provenance_and_truthful_statuses(
    tmp_path: Path,
) -> None:
    evidence_root = tmp_path / "source"
    performance = evidence_root / "performance"
    page = {
        "git_sha": "source-page-sha",
        "case_id": "M3-PERF01",
        "browser": "Chrome 150.0.0.0",
        "viewport": {"width": 1280, "height": 720, "dpr": 1},
        "warmups": 5,
        "samples": 30,
        "cache_state": "cold-http-cache-per-sample",
        "threshold_ms": 2_000,
        "raw_samples_ms": [900] * 30,
        "p95_ms": 900,
        "status": "pass",
    }
    cached = {
        **page,
        "case_id": "M3-PERF02",
        "cache_state": "warm-static-assets-and-repeated-governed-backend-queries",
        "server_result_cache_claimed": False,
        "threshold_ms": 3_000,
        "final_state": {
            "component_count": 14,
            "loading_count": 0,
            "fallback_count": 0,
            "chart_error_visible": False,
        },
    }
    _write_json(performance / "perf-page-chrome.json", page)
    _write_json(performance / "perf-dashboard-cached-chrome.json", cached)
    _write_json(
        performance / "perf-query-sqlite-100000-c1-final.json",
        _runtime_query_payload(
            dialect="sqlite",
            concurrency=1,
            samples=30,
            scenario_p95_ms=4_000,
        ),
    )
    _write_json(
        performance / "perf-query-postgresql-100000-c1-final.json",
        _runtime_query_payload(
            dialect="postgresql",
            concurrency=1,
            samples=30,
            scenario_p95_ms=4_000,
        ),
    )
    _write_json(
        performance / "perf-query-postgresql-100000-c20-final.json",
        _runtime_query_payload(
            dialect="postgresql",
            concurrency=20,
            samples=60,
            scenario_p95_ms=None,
        ),
    )
    source_bytes = (performance / "perf-page-chrome.json").read_bytes()

    output_dir = tmp_path / "output"
    index = collector.collect_evidence(
        output_dir,
        repository_root=collector.REPOSITORY_ROOT,
        evidence_root=evidence_root,
        specs=(),
        runner=_passing_result,
        git_sha="collector-worktree-sha",
    )
    statuses = _runtime_statuses(index)
    page_summary = json.loads((output_dir / "perf-page-browser.json").read_text(encoding="utf-8"))
    cached_summary = json.loads(
        (output_dir / "perf-dashboard-cached-browser.json").read_text(encoding="utf-8")
    )
    source_artifact = page_summary["runtime_evidence"]["source_artifacts"][0]
    query_summary = json.loads(
        (output_dir / "perf-query-dialects-100000-c1.json").read_text(encoding="utf-8")
    )
    query_source = query_summary["runtime_evidence"]["source_artifacts"][0]

    assert statuses["M3-PERF01"] == "pass"
    assert statuses["M3-PERF02"] == "partial"
    assert statuses["M3-PERF03"] == "pass"
    assert statuses["M3-PERF04"] == "partial"
    assert statuses["M3-PERF05"] == "missing"
    assert source_artifact["source_git_sha"] == "source-page-sha"
    assert source_artifact["source_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert query_source["source_git_sha"] == "producer-git-sha"
    assert query_source["producer_provenance"] == {
        "head_sha": "producer-git-sha",
        "worktree_state": "clean",
        "source_content_sha256": {"benchmark": "a" * 64},
    }
    assert page_summary["limitation"] is None
    assert cached_summary["limitation"]
    assert "No complete structured evidence" not in cached_summary["limitation"]
    assert page_summary["git_sha"] == "collector-worktree-sha"
    assert (performance / "perf-page-chrome.json").read_bytes() == source_bytes


def test_runtime_performance_rejects_threshold_failure_and_downgrades_missing_fields(
    tmp_path: Path,
) -> None:
    missing_root = tmp_path / "missing-source"
    forged_page = {
        "git_sha": "source-sha",
        "case_id": "M3-PERF01",
        "browser": "Chrome 150",
        "viewport": {"width": 1280, "height": 720, "dpr": 1},
        "warmups": 5,
        "samples": 30,
        "threshold_ms": 2_000,
        "raw_samples_ms": [900],
        "p95_ms": 900,
        "status": "pass",
    }
    _write_json(missing_root / "performance/perf-page-chrome.json", forged_page)
    missing_index = collector.collect_evidence(
        tmp_path / "missing-output",
        repository_root=collector.REPOSITORY_ROOT,
        evidence_root=missing_root,
        specs=(),
        runner=_passing_result,
        git_sha="collector-sha",
    )

    failing_root = tmp_path / "failing-source"
    _write_json(
        failing_root / "performance/perf-query-postgresql-100000-c20-final.json",
        _runtime_query_payload(
            dialect="postgresql",
            concurrency=20,
            samples=60,
            scenario_p95_ms=5_001,
        ),
    )
    failing_index = collector.collect_evidence(
        tmp_path / "failing-output",
        repository_root=collector.REPOSITORY_ROOT,
        evidence_root=failing_root,
        specs=(),
        runner=_passing_result,
        git_sha="collector-sha",
    )

    assert _runtime_statuses(missing_index)["M3-PERF01"] == "partial"
    assert _runtime_statuses(failing_index)["M3-PERF04"] == "fail"


def test_runtime_query_rejects_cross_dialect_mismatch_c1_threshold_and_unstable_scenario(
    tmp_path: Path,
) -> None:
    def collect_case(
        name: str,
        sqlite: dict[str, object],
        postgres: dict[str, object],
        c20: dict[str, object],
    ) -> dict[str, str]:
        evidence_root = tmp_path / f"{name}-source"
        performance = evidence_root / "performance"
        _write_json(performance / "perf-query-sqlite-100000-c1-final.json", sqlite)
        _write_json(performance / "perf-query-postgresql-100000-c1-final.json", postgres)
        _write_json(performance / "perf-query-postgresql-100000-c20-final.json", c20)
        index = collector.collect_evidence(
            tmp_path / f"{name}-output",
            repository_root=collector.REPOSITORY_ROOT,
            evidence_root=evidence_root,
            specs=(),
            runner=_passing_result,
            git_sha="collector-sha",
        )
        return _runtime_statuses(index)

    sqlite = _runtime_query_payload(
        dialect="sqlite", concurrency=1, samples=30, scenario_p95_ms=4_000
    )
    postgres = _runtime_query_payload(
        dialect="postgresql", concurrency=1, samples=30, scenario_p95_ms=4_000
    )
    c20 = _runtime_query_payload(
        dialect="postgresql", concurrency=20, samples=60, scenario_p95_ms=4_000
    )
    c20["rounds"] = [{"expected_workers": 20, "complete": True} for _ in range(3)]

    mismatched_postgres = json.loads(json.dumps(postgres))
    mismatched_postgres["scenario_results"][0]["fingerprints"] = ["forged"]
    mismatch_statuses = collect_case("mismatch", sqlite, mismatched_postgres, c20)

    slow_sqlite = json.loads(json.dumps(sqlite))
    slow_sqlite["performance_gate"]["observed_ms"] = 5_001
    slow_sqlite["performance_gate"]["passed"] = False
    slow_statuses = collect_case("slow", slow_sqlite, postgres, c20)

    unstable_c20 = json.loads(json.dumps(c20))
    unstable_c20["scenario_results"][0]["stable"] = False
    unstable_c20["scenario_results"][0]["fingerprints"] = ["one", "two"]
    unstable_statuses = collect_case("unstable", sqlite, postgres, unstable_c20)

    assert mismatch_statuses["M3-PERF03"] == "fail"
    assert slow_statuses["M3-PERF03"] == "fail"
    assert unstable_statuses["M3-PERF04"] == "fail"


def test_runtime_browser_evidence_maps_only_fully_proven_cases_to_pass(tmp_path: Path) -> None:
    evidence_root = tmp_path / "source"
    browser = evidence_root / "browser"
    browser_matrix = {
        "git_sha": "browser-source-sha",
        "chrome": {
            "desktop_dpr1": {
                "viewport": [1440, 900],
                "component_count": 14,
                "overlap_count": 0,
                "horizontal_overflow": 0,
                "canvas_count": 7,
                "nonblank_canvas_count": 7,
                "conflict_detail_gets_before_confirm": 0,
                "conflict_detail_gets_after_confirm": 1,
                "components_after_recovery": 14,
                "status": "passed",
            },
            "mobile_dpr2": {
                "viewport": [390, 844],
                "device_pixel_ratio": 2,
                "document_width": [390, 390],
                "overlap_count": 0,
                "horizontal_overflow": 0,
                "canvas_count": 7,
                "nonblank_canvas_count": 7,
                "canvas_backing_ratio": 2,
                "png_pixel_size": [780, 1688],
                "visible_resize_handles": 0,
                "edit_control_count": 0,
                "filter_query_count": 12,
                "status": "passed",
            },
        },
        "edge": {
            "desktop_dpr1": {
                "viewport": [1440, 900],
                "component_count": 14,
                "overlap_count": 0,
                "horizontal_overflow": 0,
                "canvas_count": 7,
                "nonblank_canvas_count": 7,
                "status": "passed",
            },
            "lifecycle": {
                "instantiate_status": 201,
                "save_version_status": 201,
                "configured_component_persisted_after_reopen": True,
                "status": "passed",
            },
            "mobile_dpr1": {
                "viewport": [390, 844],
                "device_pixel_ratio": 1,
                "document_width": [390, 390],
                "overlap_count": 0,
                "horizontal_overflow": 0,
                "canvas_count": 7,
                "nonblank_canvas_count": 7,
                "visible_resize_handles": 0,
                "edit_control_count": 0,
                "filter_query_count": 12,
                "status": "passed",
            },
            "mobile_dpr2": {
                "viewport": [390, 844],
                "device_pixel_ratio": 2,
                "canvas_count": 7,
                "nonblank_canvas_count": 7,
                "canvas_backing_ratio": 2,
                "png_pixel_size": [780, 1688],
                "status": "passed",
            },
        },
    }
    accessibility = {
        name: {
            "canvas_name": "dashboard canvas",
            "unnamed_button_count": 0,
            "accessible_data_table_count": 12 if "desktop" in name else 0,
            "filter_button_name": "filter" if "mobile" in name else None,
        }
        for name in ("chrome_desktop", "edge_desktop", "chrome_mobile", "edge_mobile")
    }
    console = {
        "chrome_desktop_business": {"errors": 0, "warnings": 0},
        "chrome_desktop_controlled_conflict": {
            "errors": 1,
            "warnings": 0,
            "expected": "HTTP 409",
        },
        "chrome_mobile_dpr2": {"errors": 0, "warnings": 0},
        "edge_desktop_business": {"errors": 0, "warnings": 0},
        "edge_desktop_controlled_conflict": {
            "errors": 1,
            "warnings": 0,
            "expected": "HTTP 409",
        },
        "edge_mobile_dpr1": {"errors": 0, "warnings": 0},
        "edge_mobile_dpr2": {"errors": 0, "warnings": 0},
    }
    _write_json(browser / "browser-matrix.json", browser_matrix)
    _write_json(browser / "accessibility-matrix.json", accessibility)
    _write_json(browser / "console-matrix.json", console)
    for name in (
        "browser-chrome-desktop.trace",
        "browser-chrome-desktop-clean.png",
        "browser-chrome-desktop-conflict.png",
        "browser-chrome-mobile-dpr2.trace",
        "browser-chrome-mobile-dpr2.png",
        "browser-edge-desktop.trace",
        "browser-edge-desktop-clean.png",
        "browser-edge-desktop-conflict.png",
        "browser-edge-mobile-dpr1.trace",
        "browser-edge-mobile-dpr1.png",
        "browser-edge-mobile-dpr2.png",
    ):
        (browser / name).write_bytes(b"runtime-evidence")

    index = collector.collect_evidence(
        tmp_path / "output",
        repository_root=collector.REPOSITORY_ROOT,
        evidence_root=evidence_root,
        specs=(),
        runner=_passing_result,
        git_sha="collector-sha",
    )
    statuses = _runtime_statuses(index)

    assert statuses["M3-UI01"] == "partial"
    assert statuses["M3-UI02"] == "partial"
    assert statuses["M3-UI03"] == "pass"
    assert statuses["M3-UI04"] == "missing"
    assert statuses["M3-UI05"] == "missing"
    assert statuses["M3-UI06"] == "pass"
    assert statuses["M3-UI07"] == "pass"
    assert statuses["M3-UI08"] == "missing"
    assert statuses["M3-UI09"] == "partial"
    assert statuses["M3-UI10"] == "partial"
    assert statuses["M3-UI11"] == "partial"
