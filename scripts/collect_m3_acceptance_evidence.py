from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, cast

Status = Literal["pass", "partial", "missing", "fail"]
type CommandRunner = Callable[["CommandSpec", Path], "CommandResult"]

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = Path("spikes/m3/quality/fixture/v2")
VERIFICATION_ROOT = Path("docs/verification")
MATRIX_IDS = (
    *(f"M3-C{index:02d}" for index in range(1, 7)),
    *(f"M3-DB{index:02d}" for index in range(1, 5)),
    *(f"M3-P{index:02d}" for index in range(1, 6)),
    *(f"M3-PERF{index:02d}" for index in range(1, 6)),
    *(f"M3-UI{index:02d}" for index in range(1, 12)),
    *(f"M3-D{index:02d}" for index in range(1, 4)),
    *(f"M3-R{index:02d}" for index in range(1, 7)),
)
DEPENDENCY_COMMIT = "f99962b"
EXPECTED_DEPENDENCY_VERSIONS = {
    "echarts": "6.1.0",
    "react-grid-layout": "2.2.3",
}
EXPECTED_PRINCIPAL_NAMES = ("administrator", "editor", "restricted_viewer")
EXPECTED_SCENARIO_NAMES = (
    "full_kpi",
    "category_bar",
    "category_region_stacked",
    "month_trend",
    "top_2",
    "global_page_component_filters",
    "restricted_viewer_same_group",
)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    key: str
    argv: tuple[str, ...]
    cwd: str = "."
    timeout_seconds: int = 1_200


@dataclass(frozen=True, slots=True)
class CommandResult:
    key: str
    command: str
    cwd: str
    started_at: str
    duration_seconds: float
    exit_code: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    matrix_id: str
    filename: str
    command_keys: tuple[str, ...]
    success_status: Status
    case_ids: tuple[str, ...]
    limitation: str | None = None
    related_filenames: tuple[str, ...] = ()

    @property
    def filenames(self) -> tuple[str, ...]:
        return (self.filename, *self.related_filenames)


@dataclass(frozen=True, slots=True)
class RuntimeEvidenceCollection:
    statuses: dict[str, Status]
    evaluations: dict[str, dict[str, object]]
    related_filenames: dict[str, tuple[str, ...]]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect structured M3 acceptance evidence without upgrading partial proof"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--skip-postgresql", action="store_true")
    parser.add_argument("--skip-backend-quality", action="store_true")
    parser.add_argument("--skip-frontend-quality", action="store_true")
    return parser.parse_args(argv)


def command_specs(
    *,
    include_postgresql: bool = True,
    include_backend_quality: bool = True,
    include_frontend_quality: bool = True,
) -> tuple[CommandSpec, ...]:
    specs = [
        CommandSpec(
            "fixture_check",
            ("uv", "run", "python", "spikes/m3/quality/fixture_tool.py", "check"),
        ),
        CommandSpec(
            "fixture_tests",
            ("uv", "run", "pytest", "spikes/m3/quality/tests", "-q"),
        ),
        CommandSpec(
            "compiler_negative",
            (
                "uv",
                "run",
                "pytest",
                "spikes/m3/backend/test_chart_query_compiler.py",
                "-q",
            ),
        ),
        CommandSpec(
            "compiler_golden",
            (
                "uv",
                "run",
                "pytest",
                "spikes/m3/backend/test_c1_chart_cases.py",
                "-q",
            ),
        ),
        CommandSpec(
            "sqlite_portability",
            (
                "uv",
                "run",
                "pytest",
                "backend/tests/integration/test_dashboard_chart_query_portability.py",
                "backend/tests/integration/test_dashboard_filter_portability.py",
                "-q",
            ),
        ),
        CommandSpec(
            "sqlite_permissions",
            (
                "uv",
                "run",
                "pytest",
                "backend/tests/integration/test_dashboard_api.py",
                "backend/tests/integration/test_datasets_api.py",
                "backend/tests/unit/test_dashboard_chart_query_service.py",
                "-q",
            ),
        ),
        CommandSpec(
            "sqlite_migrations",
            (
                "uv",
                "run",
                "pytest",
                "backend/tests/integration/test_dashboard_migrations.py",
                "backend/tests/integration/test_dashboard_assets_migration.py",
                "-q",
            ),
        ),
    ]
    if include_postgresql:
        specs.append(
            CommandSpec(
                "postgresql_runner",
                ("uv", "run", "python", "scripts/run_postgres_tests.py"),
                timeout_seconds=1_800,
            )
        )
    if include_backend_quality:
        specs.extend(
            (
                CommandSpec(
                    "backend_pytest",
                    ("uv", "run", "pytest", "backend/tests", "-q", "--cov=bi_system"),
                    timeout_seconds=1_800,
                ),
                CommandSpec("backend_ruff", ("uv", "run", "ruff", "check", "backend", "scripts")),
                CommandSpec(
                    "backend_format",
                    ("uv", "run", "ruff", "format", "--check", "backend", "scripts"),
                ),
                CommandSpec(
                    "backend_pyright",
                    (
                        "uv",
                        "run",
                        "basedpyright",
                        "backend/src",
                        "backend/tests",
                        "scripts",
                    ),
                    timeout_seconds=1_800,
                ),
            )
        )
    if include_frontend_quality:
        node = "node.exe" if os.name == "nt" else "node"
        npm = "npm.cmd" if os.name == "nt" else "npm"
        specs.extend(
            (
                CommandSpec(
                    "frontend_node24",
                    (
                        node,
                        "-e",
                        "if (process.versions.node.split('.')[0] !== '24') process.exit(1)",
                    ),
                ),
                CommandSpec(
                    "frontend_lint",
                    (npm, "--prefix", "frontend", "run", "lint"),
                ),
                CommandSpec(
                    "frontend_format",
                    (npm, "--prefix", "frontend", "run", "format:check"),
                ),
                CommandSpec(
                    "frontend_typecheck",
                    (npm, "--prefix", "frontend", "run", "typecheck"),
                ),
                CommandSpec(
                    "frontend_tests",
                    (
                        npm,
                        "--prefix",
                        "frontend",
                        "run",
                        "test",
                        "--",
                        "--run",
                        "--maxWorkers=1",
                        "--no-file-parallelism",
                    ),
                    timeout_seconds=1_800,
                ),
                CommandSpec(
                    "frontend_build",
                    (npm, "--prefix", "frontend", "run", "build"),
                    timeout_seconds=1_800,
                ),
            )
        )
    return tuple(specs)


def run_command(spec: CommandSpec, repository_root: Path) -> CommandResult:
    started = datetime.now(UTC).isoformat()
    timer = perf_counter()
    cwd = repository_root / spec.cwd
    try:
        completed = subprocess.run(
            spec.argv,
            cwd=cwd,
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=spec.timeout_seconds,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        exit_code = 124
        stdout = _decode_timeout_output(error.stdout)
        stderr = _decode_timeout_output(error.stderr) + "\ncommand timed out"
    except OSError as error:
        exit_code = 127
        stdout = ""
        stderr = f"{type(error).__name__}: {error}"
    return CommandResult(
        key=spec.key,
        command=redact_secrets(subprocess.list2cmdline(spec.argv)),
        cwd=spec.cwd,
        started_at=started,
        duration_seconds=round(perf_counter() - timer, 3),
        exit_code=exit_code,
        stdout=redact_secrets(stdout),
        stderr=redact_secrets(stderr),
    )


def redact_secrets(value: str) -> str:
    redacted = re.sub(
        r"(?i)([a-z][a-z0-9+.-]*://[^:\s/@]+:)([^@\s/]+)(@)",
        r"\1***\3",
        value,
    )
    redacted = re.sub(
        r"(?i)(authorization\s*:\s*(?:bearer|basic)\s+)[^\s]+",
        r"\1***",
        redacted,
    )
    key_patterns = (
        (
            r"(?:password|passwd|secret|cookie|authorization|access_token|"
            r"refresh_token|api_key|access_key|private_key|token)",
            re.IGNORECASE,
        ),
        (r"(?:[A-Z][A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET|_PASSWORD))", 0),
    )
    for key, flags in key_patterns:
        redacted = re.sub(
            rf"([\"']?\b{key}\b[\"']?\s*[:=])(?!\s*\*{{3}})\s*"
            rf"([\"'])(.*?)\2",
            r"\1 \2***\2",
            redacted,
            flags=flags,
        )
        redacted = re.sub(
            rf"([\"']?\b{key}\b[\"']?\s*[:=])(?!\s*\*{{3}})\s*"
            rf".*?(?=\s+[\"']?\b{key}\b[\"']?\s*[:=]|[,;\r\n]|$)",
            r"\1 ***",
            redacted,
            flags=flags,
        )
    return redacted


def _redacted_result(result: CommandResult) -> CommandResult:
    return CommandResult(
        key=result.key,
        command=redact_secrets(result.command),
        cwd=result.cwd,
        started_at=result.started_at,
        duration_seconds=result.duration_seconds,
        exit_code=result.exit_code,
        stdout=redact_secrets(result.stdout),
        stderr=redact_secrets(result.stderr),
    )


def collect_evidence(
    output_dir: Path,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    specs: Sequence[CommandSpec] | None = None,
    runner: CommandRunner = run_command,
    git_sha: str | None = None,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Evidence output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_specs = tuple(specs if specs is not None else command_specs())
    spec_keys = [spec.key for spec in selected_specs]
    if len(spec_keys) != len(set(spec_keys)):
        raise ValueError("Command keys must be unique")
    provenance = _git_provenance(repository_root, git_sha=git_sha)
    resolved_git_sha = cast(str, provenance["git_sha"])
    fixture = _fixture_metadata(repository_root)
    chart_case_ids = tuple(fixture["chart_case_ids"])
    filter_case_ids = tuple(fixture["filter_case_ids"])
    results = {spec.key: _redacted_result(runner(spec, repository_root)) for spec in selected_specs}
    runtime_evidence = _collect_runtime_evidence(evidence_root, output_dir)

    _write_json(
        output_dir / "environment.json",
        _environment_payload(resolved_git_sha, provenance=provenance),
    )
    _copy_fixture_manifest(repository_root, output_dir)
    _write_commands_log(output_dir / "commands.log", results.values())
    _write_command_log(
        output_dir / "fixture-check.log", results, ("fixture_check", "fixture_tests")
    )
    _write_command_log(output_dir / "migration-sqlite.log", results, ("sqlite_migrations",))
    _write_command_log(output_dir / "migration-postgresql.log", results, ("postgresql_runner",))
    backend_keys = ("backend_pytest", "backend_ruff", "backend_format", "backend_pyright")
    frontend_keys = (
        "frontend_node24",
        "frontend_lint",
        "frontend_format",
        "frontend_typecheck",
        "frontend_tests",
        "frontend_build",
    )
    _write_command_log(output_dir / "quality-backend.log", results, backend_keys)
    _write_command_log(output_dir / "quality-frontend.log", results, frontend_keys)
    _write_command_log(output_dir / "quality-postgresql.log", results, ("postgresql_runner",))
    _write_command_log(output_dir / "regression-m0.log", results, (*backend_keys, *frontend_keys))
    _write_command_log(output_dir / "regression-m1.log", results, (*backend_keys, *frontend_keys))
    _write_command_log(
        output_dir / "regression-m2.log", results, (*backend_keys, "postgresql_runner")
    )

    dependency_status = _collect_dependency_evidence(repository_root, output_dir)
    static_statuses = {**dependency_status, **runtime_evidence.statuses}
    artifacts = _artifact_specs(
        chart_case_ids,
        filter_case_ids,
        runtime_related_filenames=runtime_evidence.related_filenames,
    )
    entries: list[dict[str, Any]] = []
    for artifact in artifacts:
        runtime_evaluation = runtime_evidence.evaluations.get(artifact.matrix_id)
        static_status = cast(Status | None, static_statuses.get(artifact.matrix_id))
        status = _artifact_status(artifact, results, static_status=static_status)
        limitation = artifact.limitation
        if runtime_evaluation is not None and "limitation" in runtime_evaluation:
            limitation = cast(str | None, runtime_evaluation["limitation"])
        payload = _artifact_payload(
            artifact,
            status=status,
            git_sha=resolved_git_sha,
            fixture=fixture,
            results=results,
            provenance=provenance,
            runtime_evaluation=runtime_evaluation,
            limitation=limitation,
        )
        artifact_path = output_dir / artifact.filename
        if artifact_path.suffix == ".json" and artifact.matrix_id not in {
            "M3-D02",
            "M3-D03",
        }:
            _write_json(artifact_path, payload)
        artifact_files = [
            {
                "path": filename,
                "sha256": _sha256(output_dir / filename)
                if (output_dir / filename).is_file()
                else None,
            }
            for filename in artifact.filenames
        ]
        command_results_sha256 = _command_results_sha256(artifact.command_keys, results)
        entries.append(
            {
                "matrix_id": artifact.matrix_id,
                "status": status,
                "artifact": artifact.filename,
                "artifact_files": artifact_files,
                "sha256": _artifact_evidence_sha256(
                    output_dir,
                    artifact.filenames,
                    artifact.command_keys,
                    results,
                ),
                "command_results_sha256": command_results_sha256,
                "command_keys": list(artifact.command_keys),
                "limitation": limitation,
            }
        )

    indexed_ids = [entry["matrix_id"] for entry in entries]
    if len(indexed_ids) != len(set(indexed_ids)):
        raise RuntimeError("artifact specification contains duplicate matrix IDs")
    if set(indexed_ids) != set(MATRIX_IDS):
        missing_ids = sorted(set(MATRIX_IDS) - set(indexed_ids))
        raise RuntimeError(f"artifact specification is incomplete: {missing_ids}")
    counts = {status: sum(entry["status"] == status for entry in entries) for status in _statuses()}
    credential_scan = _scan_exported_credentials(output_dir)
    supporting_artifacts = [
        {
            "path": filename,
            "sha256": _sha256(output_dir / filename),
        }
        for filename in ("environment.json", "fixture-manifest.json", "commands.log")
    ]
    index = {
        "schema_version": 1,
        "git_sha": resolved_git_sha,
        "fixture_version": fixture["fixture_version"],
        "fixture_manifest_sha256": fixture["manifest_sha256"],
        "provenance": provenance,
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": "pass"
        if counts == {"pass": len(entries), "partial": 0, "missing": 0, "fail": 0}
        and not credential_scan["credentials_exported"]
        else "incomplete",
        "counts": counts,
        "artifacts": entries,
        "supporting_artifacts": supporting_artifacts,
        "security": credential_scan,
    }
    _write_json(output_dir / "artifact-index.json", index)
    return index


def _artifact_specs(
    chart_case_ids: tuple[str, ...],
    filter_case_ids: tuple[str, ...],
    *,
    runtime_related_filenames: dict[str, tuple[str, ...]] | None = None,
) -> tuple[ArtifactSpec, ...]:
    portability = ("sqlite_portability", "postgresql_runner")
    permissions = ("sqlite_portability", "sqlite_permissions", "postgresql_runner")
    backend = ("backend_pytest", "backend_ruff", "backend_format", "backend_pyright")
    frontend = (
        "frontend_node24",
        "frontend_lint",
        "frontend_format",
        "frontend_typecheck",
        "frontend_tests",
        "frontend_build",
    )
    return (
        ArtifactSpec(
            "M3-C01",
            "fixture-check.log",
            ("fixture_check", "fixture_tests"),
            "pass",
            ("m3-star-v2",),
        ),
        ArtifactSpec(
            "M3-C02",
            "contract-negative.json",
            ("compiler_negative",),
            "partial",
            ("physical-name", "raw-sql", "function", "unknown-uuid", "bound-filter"),
            "Pytest proves rejection but does not emit each error payload or leakage scan.",
        ),
        ArtifactSpec(
            "M3-C03",
            "compiler-golden.json",
            ("compiler_golden",),
            "partial",
            chart_case_ids,
            "Existing tests compare golden values but do not export compiled AST "
            "and rows per case.",
        ),
        ArtifactSpec(
            "M3-C04",
            "filter-golden.json",
            portability,
            "partial",
            filter_case_ids,
            "Existing tests do not export resolved predicates, row IDs, "
            "and amounts for every case.",
        ),
        ArtifactSpec(
            "M3-C05",
            "type-parity.json",
            portability,
            "partial",
            ("null", "decimal", "boolean", "date", "datetime", "dst"),
            "Dual-database assertions run, but normalized typed values are not "
            "exposed to this collector.",
        ),
        ArtifactSpec(
            "M3-C06",
            "top-n.json",
            portability,
            "partial",
            ("ranking-products-top2-repeat-10",),
            "Stable Top N is asserted, but ten raw ordered results are not exported.",
        ),
        ArtifactSpec(
            "M3-DB01",
            "db-sqlite-golden.json",
            ("sqlite_portability",),
            "partial",
            (*chart_case_ids, *filter_case_ids),
            "SQLite tests pass without exporting the complete normalized golden result set.",
        ),
        ArtifactSpec(
            "M3-DB02",
            "db-postgresql-golden.json",
            ("postgresql_runner",),
            "partial",
            (*chart_case_ids, *filter_case_ids),
            "PostgreSQL tests pass without exporting the complete normalized golden result set.",
        ),
        ArtifactSpec(
            "M3-DB03",
            "db-parity.json",
            (),
            "missing",
            (*chart_case_ids, *filter_case_ids),
            "No existing harness exports both dialect results for field-by-field comparison.",
        ),
        ArtifactSpec(
            "M3-DB04",
            "migration-sqlite.log",
            ("sqlite_migrations", "postgresql_runner"),
            "pass",
            ("upgrade-head", "downgrade-previous", "re-upgrade-head"),
            related_filenames=("migration-postgresql.log",),
        ),
        ArtifactSpec(
            "M3-P01",
            "permission-principals.json",
            permissions,
            "partial",
            ("administrator", "editor", "restricted-viewer"),
            "The current portability context lacks the full same-query editor principal matrix.",
        ),
        ArtifactSpec(
            "M3-P02",
            "permission-rls-preaggregate.json",
            permissions,
            "partial",
            ("viewer-all", "viewer-category", "viewer-top-n"),
            "RLS behavior is asserted, but intermediate cache and tooltip exclusion "
            "are not exported.",
        ),
        ArtifactSpec(
            "M3-P03",
            "permission-forged-filter.json",
            permissions,
            "partial",
            ("restricted-viewer-forged-south", "client-cannot-remove-rls"),
            "Forged South is asserted; no structured proof of the unexpressible "
            "RLS-removal case exists.",
        ),
        ArtifactSpec(
            "M3-P04",
            "permission-cross-workspace.json",
            permissions,
            "partial",
            ("dashboard", "dataset", "field", "query"),
            "Cross-workspace tests are distributed and do not export one "
            "resource-by-resource result.",
        ),
        ArtifactSpec(
            "M3-P05",
            "permission-capabilities.json",
            ("sqlite_permissions", "postgresql_runner"),
            "partial",
            ("editor-dataset-manage", "viewer-dashboard-edit"),
            "403 behavior is asserted separately; atomic no-partial-write state is not exported.",
        ),
        *_missing_runtime_artifacts(runtime_related_filenames or {}),
        ArtifactSpec("M3-D01", "licenses-m3.csv", (), "pass", ("candidate-license-inventory",)),
        ArtifactSpec(
            "M3-D02",
            "bundle-m3.json",
            (),
            "pass",
            ("baseline", "candidate", "route-chunk"),
            related_filenames=("bundle-build.log",),
        ),
        ArtifactSpec(
            "M3-D03",
            "dependency-lock-admission.json",
            (),
            "pass",
            ("echarts@6.1.0", "react-grid-layout@2.2.3"),
        ),
        ArtifactSpec(
            "M3-R01", "regression-m0.log", (*backend, *frontend), "pass", ("m0-full-regression",)
        ),
        ArtifactSpec(
            "M3-R02", "regression-m1.log", (*backend, *frontend), "pass", ("m1-full-regression",)
        ),
        ArtifactSpec(
            "M3-R03",
            "regression-m2.log",
            (*backend, "postgresql_runner"),
            "pass",
            ("m2-full-regression",),
        ),
        ArtifactSpec(
            "M3-R04",
            "quality-backend.log",
            backend,
            "pass",
            ("pytest-coverage", "ruff", "format", "basedpyright"),
        ),
        ArtifactSpec(
            "M3-R05",
            "quality-frontend.log",
            frontend,
            "pass",
            ("lint", "format", "typecheck", "test", "build"),
        ),
        ArtifactSpec(
            "M3-R06",
            "quality-postgresql.log",
            ("postgresql_runner",),
            "pass",
            ("integration", "downgrade", "re-upgrade"),
        ),
    )


def _missing_runtime_artifacts(
    related_filenames: dict[str, tuple[str, ...]],
) -> tuple[ArtifactSpec, ...]:
    limitation = "No complete structured evidence has been collected for this acceptance item."
    specs = (
        ("M3-PERF01", "perf-page-browser.json"),
        ("M3-PERF02", "perf-dashboard-cached-browser.json"),
        ("M3-PERF03", "perf-query-dialects-100000-c1.json"),
        ("M3-PERF04", "perf-query-postgresql-100000-c20.json"),
        ("M3-PERF05", "perf-timeout-recovery.json"),
        ("M3-UI01", "ui-core-chart-spike.json"),
        ("M3-UI02", "ui-desktop-layout.json"),
        ("M3-UI03", "ui-mobile-readonly.json"),
        ("M3-UI04", "ui-core-chart-golden.json"),
        ("M3-UI05", "ui-fixed-dimensions.json"),
        ("M3-UI06", "ui-canvas-accessibility.json"),
        ("M3-UI07", "ui-export-2x.json"),
        ("M3-UI08", "ui-loading-success-empty.json"),
        ("M3-UI09", "ui-error-forbidden-timeout-truncated.json"),
        ("M3-UI10", "ui-error-recovery.json"),
        ("M3-UI11", "ui-full-browser-workflow.json"),
    )
    return tuple(
        ArtifactSpec(
            matrix_id,
            filename,
            (),
            "missing",
            (),
            limitation,
            related_filenames.get(matrix_id, ()),
        )
        for matrix_id, filename in specs
    )


def _artifact_status(
    artifact: ArtifactSpec,
    results: dict[str, CommandResult],
    *,
    static_status: Status | None,
) -> Status:
    if static_status is not None:
        return static_status
    if not artifact.command_keys:
        return artifact.success_status
    selected = [results.get(key) for key in artifact.command_keys]
    if any(result is not None and not result.passed for result in selected):
        return "fail"
    if any(result is None for result in selected):
        return "missing"
    return artifact.success_status


def _artifact_payload(
    artifact: ArtifactSpec,
    *,
    status: Status,
    git_sha: str,
    fixture: dict[str, Any],
    results: dict[str, CommandResult],
    provenance: dict[str, object],
    runtime_evaluation: dict[str, object] | None,
    limitation: str | None,
) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "matrix_id": artifact.matrix_id,
        "status": status,
        "git_sha": git_sha,
        "fixture_version": fixture["fixture_version"],
        "fixture_manifest_sha256": fixture["manifest_sha256"],
        "provenance": provenance,
        "case_ids": list(artifact.case_ids),
        "commands": [
            _command_result_payload(results[key]) for key in artifact.command_keys if key in results
        ],
        "limitation": limitation,
        "contains_exported_rows_or_values": False,
    }
    if runtime_evaluation is not None:
        payload["runtime_evidence"] = runtime_evaluation
    return payload


def _command_result_payload(result: CommandResult) -> dict[str, object]:
    return {
        "key": result.key,
        "command": result.command,
        "cwd": result.cwd,
        "started_at": result.started_at,
        "duration_seconds": result.duration_seconds,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _collect_runtime_evidence(
    evidence_root: Path | None,
    output_dir: Path,
) -> RuntimeEvidenceCollection:
    if evidence_root is None:
        return RuntimeEvidenceCollection({}, {}, {})
    root = evidence_root.resolve()
    if not root.is_dir():
        raise ValueError(f"Runtime evidence root must be an existing directory: {root}")
    if root == output_dir or root in output_dir.parents or output_dir in root.parents:
        raise ValueError("Runtime evidence root and output directory must be independent")

    source_metadata: dict[str, dict[str, object]] = {}

    def ingest(relative_path: str) -> dict[str, object] | None:
        source = root / relative_path
        if not source.is_file():
            return None
        if relative_path not in source_metadata:
            source_metadata[relative_path] = _copy_runtime_source(root, source, output_dir)
        return source_metadata[relative_path]

    statuses: dict[str, Status] = {}
    evaluations: dict[str, dict[str, object]] = {}
    related: dict[str, tuple[str, ...]] = {}

    performance_specs = {
        "M3-PERF01": ("performance/perf-page-chrome.json",),
        "M3-PERF02": ("performance/perf-dashboard-cached-chrome.json",),
        "M3-PERF03": (
            "performance/perf-query-sqlite-100000-c1-final.json",
            "performance/perf-query-postgresql-100000-c1-final.json",
        ),
        "M3-PERF04": ("performance/perf-query-postgresql-100000-c20-final.json",),
        "M3-PERF05": ("performance/perf-timeout-recovery.json",),
    }
    for matrix_id, paths in performance_specs.items():
        metadata = [item for path in paths if (item := ingest(path)) is not None]
        status, details = _evaluate_performance_evidence(matrix_id, root, paths)
        statuses[matrix_id] = status
        evaluations[matrix_id] = {
            "status": status,
            "source_artifacts": metadata,
            "limitation": _runtime_limitation(status, details),
            **details,
        }
        related[matrix_id] = tuple(cast(str, item["copied_path"]) for item in metadata)

    browser_root = root / "browser"
    recognized_browser_paths: list[str] = []
    if browser_root.is_dir():
        for source in sorted(browser_root.iterdir()):
            if not source.is_file():
                continue
            if (
                source.name
                in {
                    "browser-matrix.json",
                    "accessibility-matrix.json",
                    "console-matrix.json",
                }
                or (
                    source.name.startswith("browser-")
                    and source.suffix in {".png", ".trace", ".network", ".json"}
                )
                or "pixel" in source.name
            ):
                relative_path = source.relative_to(root).as_posix()
                recognized_browser_paths.append(relative_path)
                ingest(relative_path)

    browser_statuses, browser_details = _evaluate_browser_evidence(root)
    browser_metadata = [source_metadata[path] for path in recognized_browser_paths]
    browser_related = tuple(cast(str, item["copied_path"]) for item in browser_metadata)
    for matrix_id in (f"M3-UI{index:02d}" for index in range(1, 12)):
        status = browser_statuses[matrix_id]
        statuses[matrix_id] = status
        details = browser_details[matrix_id]
        evaluations[matrix_id] = {
            "status": status,
            "source_artifacts": browser_metadata if status != "missing" else [],
            "limitation": _runtime_limitation(status, details),
            **details,
        }
        related[matrix_id] = browser_related if status != "missing" else ()

    return RuntimeEvidenceCollection(statuses, evaluations, related)


def _runtime_limitation(status: Status, details: dict[str, object]) -> str | None:
    if status == "pass":
        return None
    if status == "missing":
        return "Structured runtime evidence was not provided for this acceptance item."
    issue_paths = _runtime_issue_paths(details.get("checks"), prefix="checks")
    issue_text = ", ".join(issue_paths[:8]) if issue_paths else "runtime contract incomplete"
    if status == "fail":
        return f"Runtime evidence failed acceptance checks: {issue_text}."
    return f"Runtime evidence is incomplete; missing or partial checks: {issue_text}."


def _runtime_issue_paths(value: object, *, prefix: str) -> list[str]:
    if prefix.endswith(".top_level_mix_p95_is_gate"):
        return []
    mapping = _as_object_dict(value)
    if mapping is not None:
        paths: list[str] = []
        for key, nested in mapping.items():
            paths.extend(_runtime_issue_paths(nested, prefix=f"{prefix}.{key}"))
        return paths
    if (
        value is False
        or value is None
        or (isinstance(value, str) and value in {"partial", "missing", "fail"})
    ):
        return [prefix]
    return []


def _copy_runtime_source(root: Path, source: Path, output_dir: Path) -> dict[str, object]:
    relative_path = source.relative_to(root)
    target = output_dir / "runtime" / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    source_sha256 = _sha256(source)
    source_git_sha: str | None = None
    producer_provenance: dict[str, object] | None = None
    if source.suffix in {".json", ".log", ".trace", ".network", ".csv", ".txt"}:
        try:
            content = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copyfile(source, target)
        else:
            if source.suffix == ".json":
                try:
                    payload: object = json.loads(content)
                except json.JSONDecodeError:
                    payload = None
                if isinstance(payload, dict):
                    source_object = cast(dict[str, object], payload)
                    candidate = source_object.get("git_sha", source_object.get("commit"))
                    if isinstance(candidate, str):
                        source_git_sha = candidate
                    producer_provenance = _as_object_dict(source_object.get("producer_provenance"))
            target.write_text(redact_secrets(content), encoding="utf-8")
    else:
        shutil.copyfile(source, target)
    return {
        "source_path": relative_path.as_posix(),
        "source_sha256": source_sha256,
        "source_git_sha": source_git_sha,
        "producer_provenance": producer_provenance,
        "copied_path": target.relative_to(output_dir).as_posix(),
        "copied_sha256": _sha256(target),
    }


def _evaluate_performance_evidence(
    matrix_id: str,
    root: Path,
    relative_paths: tuple[str, ...],
) -> tuple[Status, dict[str, object]]:
    payloads: list[dict[str, Any]] = []
    for relative_path in relative_paths:
        path = root / relative_path
        if not path.is_file():
            continue
        try:
            payloads.append(_read_json(path))
        except (json.JSONDecodeError, ValueError):
            return "fail", {"checks": {"valid_json": False}}
    if not payloads:
        return "missing", {"checks": {"source_present": False}}
    if matrix_id == "M3-PERF01":
        return _evaluate_page_performance(payloads[0], cached=False)
    if matrix_id == "M3-PERF02":
        return _evaluate_page_performance(payloads[0], cached=True)
    if matrix_id == "M3-PERF03":
        if len(payloads) != 2:
            return "partial", {"checks": {"both_dialects_present": False}}
        sqlite_status, sqlite_checks = _evaluate_query_performance(
            payloads[0], dialect="sqlite", concurrency=1, require_scenario_gate=True
        )
        postgres_status, postgres_checks = _evaluate_query_performance(
            payloads[1], dialect="postgresql", concurrency=1, require_scenario_gate=True
        )
        sqlite_fingerprints = sqlite_checks.get("scenario_fingerprints")
        postgres_fingerprints = postgres_checks.get("scenario_fingerprints")
        parity_evaluated = isinstance(sqlite_fingerprints, dict) and isinstance(
            postgres_fingerprints, dict
        )
        fingerprint_parity = parity_evaluated and sqlite_fingerprints == postgres_fingerprints
        combined = _combine_statuses((sqlite_status, postgres_status))
        if parity_evaluated and not fingerprint_parity:
            combined = "fail"
        elif not parity_evaluated and combined == "pass":
            combined = "partial"
        return combined, {
            "checks": {
                "sqlite": sqlite_checks,
                "postgresql": postgres_checks,
                "cross_dialect_scenario_fingerprint_parity": fingerprint_parity,
                "cross_dialect_scenario_fingerprint_parity_evaluated": parity_evaluated,
            }
        }
    if matrix_id == "M3-PERF04":
        status, checks = _evaluate_query_performance(
            payloads[0],
            dialect="postgresql",
            concurrency=20,
            require_scenario_gate=True,
        )
        return status, {"checks": checks}
    return _evaluate_timeout_recovery(payloads[0])


def _evaluate_page_performance(
    payload: dict[str, Any],
    *,
    cached: bool,
) -> tuple[Status, dict[str, object]]:
    expected_threshold = 3_000 if cached else 2_000
    samples = payload.get("samples")
    raw_samples = _numeric_list(payload.get("raw_samples_ms"))
    p95 = payload.get("p95_ms")
    failed = payload.get("status") == "fail" or (
        isinstance(p95, (int, float)) and p95 > expected_threshold
    )
    reported_matches: bool = bool(
        raw_samples is not None
        and raw_samples
        and isinstance(p95, (int, float))
        and _nearest_rank(raw_samples, 0.95) == p95
    )
    viewport = _as_object_dict(payload.get("viewport"))
    complete: bool = bool(
        payload.get("case_id") == ("M3-PERF02" if cached else "M3-PERF01")
        and isinstance(payload.get("browser"), str)
        and "Chrome" in cast(str, payload["browser"])
        and viewport is not None
        and viewport.get("width") == 1280
        and viewport.get("height") == 720
        and payload.get("warmups") == 5
        and samples == 30
        and raw_samples is not None
        and len(raw_samples) == 30
        and payload.get("threshold_ms") == expected_threshold
        and payload.get("status") == "pass"
        and reported_matches
    )
    if cached:
        final_state = _as_object_dict(payload.get("final_state"))
        complete = bool(
            complete
            and payload.get("server_result_cache_claimed") is True
            and final_state is not None
            and final_state.get("loading_count") == 0
            and final_state.get("fallback_count") == 0
            and final_state.get("chart_error_visible") is False
        )
    status: Status = (
        "fail"
        if failed or (raw_samples is not None and not reported_matches)
        else ("pass" if complete else "partial")
    )
    return status, {
        "checks": {
            "threshold_ms": expected_threshold,
            "reported_p95_matches_raw_samples": reported_matches,
            "sample_contract_complete": complete,
            "server_result_cache_observed": (
                payload.get("server_result_cache_claimed") if cached else None
            ),
        }
    }


def _evaluate_query_performance(
    payload: dict[str, Any],
    *,
    dialect: str,
    concurrency: int,
    require_scenario_gate: bool,
) -> tuple[Status, dict[str, object]]:
    expected_samples = 60 if concurrency == 20 else 30
    samples = _object_list(payload.get("samples"))
    rls = _as_object_dict(payload.get("rls_isolation"))
    validation = _as_object_dict(payload.get("run_validation"))
    acceptance = _as_object_dict(payload.get("acceptance"))
    producer_provenance = _as_object_dict(payload.get("producer_provenance"))
    source_content_sha256 = (
        _as_object_dict(producer_provenance.get("source_content_sha256"))
        if producer_provenance is not None
        else None
    )
    source_git_sha = payload.get("git_sha")
    producer_provenance_complete = bool(
        isinstance(source_git_sha, str)
        and producer_provenance is not None
        and producer_provenance.get("head_sha") == source_git_sha
        and producer_provenance.get("worktree_state") in {"clean", "dirty"}
        and source_content_sha256
    )
    performance_gate = _as_object_dict(payload.get("performance_gate"))
    scenario_p95 = performance_gate.get("observed_ms") if performance_gate is not None else None
    scenario_status, scenario_fingerprints = _evaluate_scenario_results(
        payload.get("scenario_results"),
        expected_samples=expected_samples,
    )
    fixture_oracle = _as_object_dict(rls.get("fixture_oracle")) if rls is not None else None
    threshold_failure = performance_gate is not None and (
        performance_gate.get("passed") is False
        or (isinstance(scenario_p95, (int, float)) and scenario_p95 > 5_000)
    )
    execution_failure = (
        payload.get("error_count") not in {0, None}
        or payload.get("timeouts") not in {0, None}
        or (validation is not None and validation.get("valid") is False)
        or (acceptance is not None and acceptance.get("status") == "fail")
    )
    common_complete = (
        payload.get("dialect") == dialect
        and payload.get("rows") == 100_000
        and payload.get("concurrency") == concurrency
        and payload.get("warmups") == 5
        and payload.get("warmups_completed") == 5
        and payload.get("queries_per_request") == 7
        and payload.get("completed") == expected_samples
        and payload.get("error_count") == 0
        and payload.get("timeouts") == 0
        and samples is not None
        and len(samples) == expected_samples
        and tuple(payload.get("principal_names", ())) == EXPECTED_PRINCIPAL_NAMES
        and tuple(payload.get("scenario_names", ())) == EXPECTED_SCENARIO_NAMES
        and rls is not None
        and rls.get("evaluated") is True
        and rls.get("isolated") is True
        and fixture_oracle is not None
        and fixture_oracle.get("trusted") is True
        and fixture_oracle.get("canonical_rows_match") is True
        and validation is not None
        and validation.get("valid") is True
        and acceptance is not None
        and acceptance.get("run_evidence_valid") is True
        and producer_provenance_complete
    )
    rounds_complete = True
    if concurrency == 20:
        rounds = _object_list(payload.get("rounds"))
        rounds_complete = (
            rounds is not None
            and len(rounds) >= 3
            and all(_round_evidence_complete(round_item) for round_item in rounds)
        )
    scenario_gate_complete = not require_scenario_gate or (
        isinstance(scenario_p95, (int, float))
        and performance_gate is not None
        and performance_gate.get("metric") == "maximum_representative_scenario_client_p95_ms"
        and performance_gate.get("threshold_ms") == 5_000
        and performance_gate.get("representative_scenario_count") == 7
        and performance_gate.get("evaluated_scenario_count") == 7
        and performance_gate.get("missing_scenarios") == []
        and performance_gate.get("passed") is True
        and scenario_p95 <= 5_000
    )
    if threshold_failure or execution_failure or scenario_status == "fail":
        status: Status = "fail"
    elif (
        common_complete and rounds_complete and scenario_gate_complete and scenario_status == "pass"
    ):
        status = "pass"
    else:
        status = "partial"
    return status, {
        "common_contract_complete": common_complete,
        "rounds_complete": rounds_complete,
        "scenario_gate_complete": scenario_gate_complete,
        "scenario_results_status": scenario_status,
        "scenario_fingerprints": scenario_fingerprints,
        "threshold_passed": not threshold_failure,
        "execution_passed": not execution_failure,
        "producer_provenance_complete": producer_provenance_complete,
        "max_scenario_client_p95_ms": scenario_p95,
        "threshold_ms": 5_000,
        "top_level_mix_p95_ms": payload.get("p95_ms"),
        "top_level_mix_p95_is_gate": False,
    }


def _evaluate_scenario_results(
    value: object,
    *,
    expected_samples: int,
) -> tuple[Status, dict[str, str] | None]:
    items = _object_list(value)
    if items is None:
        return "partial", None
    if len(items) != len(EXPECTED_SCENARIO_NAMES):
        return "fail", None
    fingerprints: dict[str, str] = {}
    seen: set[str] = set()
    missing_field = False
    for item in items:
        result = _as_object_dict(item)
        if result is None:
            return "fail", None
        scenario_name = result.get("scenario_name")
        if not isinstance(scenario_name, str) or scenario_name not in EXPECTED_SCENARIO_NAMES:
            return "fail", None
        if scenario_name in seen:
            return "fail", None
        seen.add(scenario_name)
        if "sample_count" not in result or "stable" not in result or "fingerprints" not in result:
            missing_field = True
            continue
        if result.get("sample_count") != expected_samples or result.get("stable") is not True:
            return "fail", None
        values = _object_list(result.get("fingerprints"))
        if values is None or len(values) != 1 or not isinstance(values[0], str):
            return "fail", None
        fingerprints[scenario_name] = values[0]
    if missing_field:
        return "partial", None
    if tuple(fingerprints) != EXPECTED_SCENARIO_NAMES:
        return "fail", None
    return "pass", fingerprints


def _evaluate_timeout_recovery(
    payload: dict[str, Any],
) -> tuple[Status, dict[str, object]]:
    threshold = payload.get("timeout_seconds")
    failed = (
        payload.get("status") == "fail"
        or (isinstance(threshold, (int, float)) and threshold > 10)
        or payload.get("retry_succeeded") is False
    )
    complete = (
        payload.get("case_id") == "M3-PERF05"
        and isinstance(threshold, (int, float))
        and threshold <= 10
        and payload.get("progress_visible_before_timeout") is True
        and payload.get("timed_out") is True
        and payload.get("cancel_succeeded") is True
        and payload.get("retry_succeeded") is True
        and payload.get("status") == "pass"
    )
    return ("fail" if failed else "pass" if complete else "partial"), {
        "checks": {"timeout_recovery_contract_complete": complete, "threshold_seconds": 10}
    }


def _combine_statuses(statuses: Sequence[Status]) -> Status:
    if "fail" in statuses:
        return "fail"
    if all(status == "pass" for status in statuses):
        return "pass"
    if all(status == "missing" for status in statuses):
        return "missing"
    return "partial"


def _nearest_rank(values: list[int | float], percentile_value: float) -> int | float:
    ordered = sorted(values)
    index = max(0, int(len(ordered) * percentile_value + 0.999999) - 1)
    return ordered[index]


def _object_list(value: object) -> list[object] | None:
    return cast(list[object], value) if isinstance(value, list) else None


def _numeric_list(value: object) -> list[int | float] | None:
    items = _object_list(value)
    if items is None or not all(isinstance(item, (int, float)) for item in items):
        return None
    return cast(list[int | float], items)


def _round_evidence_complete(value: object) -> bool:
    item = _as_object_dict(value)
    return bool(
        item is not None and item.get("expected_workers") == 20 and item.get("complete") is True
    )


def _evaluate_browser_evidence(
    root: Path,
) -> tuple[dict[str, Status], dict[str, dict[str, object]]]:
    matrix_path = root / "browser/browser-matrix.json"
    accessibility_path = root / "browser/accessibility-matrix.json"
    console_path = root / "browser/console-matrix.json"
    matrix_ids = tuple(f"M3-UI{index:02d}" for index in range(1, 12))
    if not any(path.is_file() for path in (matrix_path, accessibility_path, console_path)):
        return (
            {matrix_id: "missing" for matrix_id in matrix_ids},
            {
                matrix_id: {"checks": {"structured_browser_evidence_present": False}}
                for matrix_id in matrix_ids
            },
        )
    try:
        browser = _read_json(matrix_path) if matrix_path.is_file() else {}
        accessibility = _read_json(accessibility_path) if accessibility_path.is_file() else {}
        console = _read_json(console_path) if console_path.is_file() else {}
    except (json.JSONDecodeError, ValueError):
        return (
            {matrix_id: "fail" for matrix_id in matrix_ids},
            {
                matrix_id: {"checks": {"valid_structured_browser_json": False}}
                for matrix_id in matrix_ids
            },
        )

    chrome = _as_object_dict(browser.get("chrome")) or {}
    edge = _as_object_dict(browser.get("edge")) or {}
    chrome_desktop = _as_object_dict(chrome.get("desktop_dpr1"))
    edge_desktop = _as_object_dict(edge.get("desktop_dpr1"))
    chrome_mobile = _as_object_dict(chrome.get("mobile_dpr2"))
    edge_mobile = _as_object_dict(edge.get("mobile_dpr1"))
    edge_mobile_dpr2 = _as_object_dict(edge.get("mobile_dpr2"))
    desktop_valid = all(
        _desktop_browser_state_valid(state) for state in (chrome_desktop, edge_desktop)
    )
    mobile_valid = all(_mobile_browser_state_valid(state) for state in (chrome_mobile, edge_mobile))
    business_console_clean = all(
        _console_entry_clean(console, key)
        for key in (
            "chrome_desktop_business",
            "chrome_mobile_dpr2",
            "edge_desktop_business",
            "edge_mobile_dpr1",
        )
    )
    browser_failed = any(
        _state_explicitly_failed(state)
        for state in (chrome_desktop, edge_desktop, chrome_mobile, edge_mobile, edge_mobile_dpr2)
    ) or any(
        _console_entry_failed(console, key)
        for key in (
            "chrome_desktop_business",
            "chrome_mobile_dpr2",
            "edge_desktop_business",
            "edge_mobile_dpr1",
        )
    )

    desktop_files = _runtime_files_present(
        root,
        (
            "browser/browser-chrome-desktop.trace",
            "browser/browser-chrome-desktop-clean.png",
            "browser/browser-edge-desktop.trace",
            "browser/browser-edge-desktop-clean.png",
        ),
    )
    mobile_files = _runtime_files_present(
        root,
        (
            "browser/browser-chrome-mobile-dpr2.trace",
            "browser/browser-chrome-mobile-dpr2.png",
            "browser/browser-edge-mobile-dpr1.trace",
            "browser/browser-edge-mobile-dpr1.png",
        ),
    )
    chrome_dpr2_valid = _dpr2_state_valid(chrome_mobile)
    edge_dpr2_valid = _dpr2_state_valid(edge_mobile_dpr2)
    dpr2_files = _runtime_files_present(
        root,
        (
            "browser/browser-chrome-mobile-dpr2.png",
            "browser/browser-edge-mobile-dpr2.png",
        ),
    )
    accessibility_complete = _accessibility_matrix_complete(accessibility)
    controlled_conflicts = all(
        _controlled_conflict_expected(console, key)
        for key in (
            "chrome_desktop_controlled_conflict",
            "edge_desktop_controlled_conflict",
        )
    )
    conflict_files = _runtime_files_present(
        root,
        (
            "browser/browser-chrome-desktop-conflict.png",
            "browser/browser-edge-desktop-conflict.png",
        ),
    )
    recovery_observed = _recovery_observed(chrome, edge)
    lifecycle_complete = all(
        _lifecycle_complete(_as_object_dict(browser_side.get("lifecycle")))
        for browser_side in (chrome, edge)
    )

    stress_profiles = _as_object_dict(browser.get("desktop_stress_profiles"))
    desktop_stress_complete = stress_profiles is not None and all(
        str(count) in stress_profiles for count in (1, 20, 50)
    )
    chart_golden_complete = isinstance(browser.get("chart_golden_cases"), list)
    fixed_dimensions_complete = isinstance(browser.get("fixed_dimension_states"), list)
    view_states_complete = isinstance(browser.get("view_states"), list)

    status_by_id: dict[str, Status] = {
        "M3-UI01": _evidence_status(
            failed=browser_failed,
            complete=False,
            partial=desktop_valid and desktop_files and business_console_clean,
        ),
        "M3-UI02": _evidence_status(
            failed=browser_failed,
            complete=desktop_valid and desktop_files and desktop_stress_complete,
            partial=desktop_valid and desktop_files,
        ),
        "M3-UI03": _evidence_status(
            failed=browser_failed,
            complete=mobile_valid and mobile_files and business_console_clean,
            partial=chrome_mobile is not None or edge_mobile is not None,
        ),
        "M3-UI04": _evidence_status(
            failed=browser_failed,
            complete=chart_golden_complete,
            partial=False,
        ),
        "M3-UI05": _evidence_status(
            failed=browser_failed,
            complete=fixed_dimensions_complete,
            partial=False,
        ),
        "M3-UI06": _evidence_status(
            failed=browser_failed,
            complete=(
                desktop_valid and mobile_valid and accessibility_complete and business_console_clean
            ),
            partial=accessibility_path.is_file(),
        ),
        "M3-UI07": _evidence_status(
            failed=browser_failed,
            complete=chrome_dpr2_valid and edge_dpr2_valid and dpr2_files,
            partial=chrome_mobile is not None or edge_mobile_dpr2 is not None,
        ),
        "M3-UI08": _evidence_status(
            failed=browser_failed,
            complete=view_states_complete,
            partial=False,
        ),
        "M3-UI09": _evidence_status(
            failed=browser_failed,
            complete=False,
            partial=controlled_conflicts and conflict_files,
        ),
        "M3-UI10": _evidence_status(
            failed=browser_failed,
            complete=False,
            partial=recovery_observed,
        ),
        "M3-UI11": _evidence_status(
            failed=browser_failed,
            complete=lifecycle_complete and desktop_files,
            partial=recovery_observed or any("lifecycle" in side for side in (chrome, edge)),
        ),
    }
    shared_checks: dict[str, object] = {
        "desktop_valid": desktop_valid,
        "mobile_readonly_valid": mobile_valid,
        "business_console_clean": business_console_clean,
        "accessibility_complete": accessibility_complete,
        "chrome_dpr2_valid": chrome_dpr2_valid,
        "edge_dpr2_valid": edge_dpr2_valid,
        "desktop_stress_profiles_complete": desktop_stress_complete,
        "chart_golden_complete": chart_golden_complete,
        "fixed_dimensions_complete": fixed_dimensions_complete,
        "view_states_complete": view_states_complete,
        "controlled_conflicts_observed": controlled_conflicts and conflict_files,
        "recovery_observed": recovery_observed,
        "full_lifecycle_both_browsers": lifecycle_complete,
    }
    return status_by_id, {matrix_id: {"checks": shared_checks} for matrix_id in matrix_ids}


def _desktop_browser_state_valid(state: dict[str, object] | None) -> bool:
    return bool(
        state is not None
        and state.get("viewport") == [1440, 900]
        and state.get("component_count") == 14
        and state.get("overlap_count") == 0
        and state.get("horizontal_overflow") == 0
        and state.get("canvas_count") == state.get("nonblank_canvas_count")
        and state.get("canvas_count") == 7
        and state.get("status") == "passed"
    )


def _mobile_browser_state_valid(state: dict[str, object] | None) -> bool:
    return bool(
        state is not None
        and state.get("viewport") == [390, 844]
        and state.get("document_width") == [390, 390]
        and state.get("overlap_count") == 0
        and state.get("horizontal_overflow") == 0
        and state.get("canvas_count") == state.get("nonblank_canvas_count")
        and state.get("visible_resize_handles") == 0
        and state.get("edit_control_count") == 0
        and isinstance(state.get("filter_query_count"), int)
        and cast(int, state["filter_query_count"]) > 0
        and state.get("status") == "passed"
    )


def _dpr2_state_valid(state: dict[str, object] | None) -> bool:
    return bool(
        state is not None
        and state.get("device_pixel_ratio") == 2
        and state.get("canvas_backing_ratio") == 2
        and state.get("png_pixel_size") == [780, 1688]
        and state.get("canvas_count") == state.get("nonblank_canvas_count")
        and state.get("status") == "passed"
    )


def _accessibility_matrix_complete(accessibility: dict[str, Any]) -> bool:
    for name in ("chrome_desktop", "edge_desktop", "chrome_mobile", "edge_mobile"):
        entry = _as_object_dict(accessibility.get(name))
        if (
            entry is None
            or not isinstance(entry.get("canvas_name"), str)
            or entry.get("unnamed_button_count") != 0
        ):
            return False
        if "desktop" in name and not (
            isinstance(entry.get("accessible_data_table_count"), int)
            and cast(int, entry["accessible_data_table_count"]) > 0
        ):
            return False
        if "mobile" in name and entry.get("filter_button_name") != "filter":
            return False
    return True


def _console_entry_clean(console: dict[str, Any], key: str) -> bool:
    entry = _as_object_dict(console.get(key))
    return entry is not None and entry.get("errors") == 0


def _console_entry_failed(console: dict[str, Any], key: str) -> bool:
    entry = _as_object_dict(console.get(key))
    errors = entry.get("errors") if entry is not None else None
    return isinstance(errors, int) and errors > 0


def _controlled_conflict_expected(console: dict[str, Any], key: str) -> bool:
    entry = _as_object_dict(console.get(key))
    return bool(
        entry is not None
        and entry.get("errors") == 1
        and isinstance(entry.get("expected"), str)
        and "409" in cast(str, entry["expected"])
    )


def _state_explicitly_failed(state: dict[str, object] | None) -> bool:
    return state is not None and state.get("status") not in {None, "passed"}


def _runtime_files_present(root: Path, relative_paths: Sequence[str]) -> bool:
    return all((root / relative_path).is_file() for relative_path in relative_paths)


def _recovery_observed(chrome: dict[str, object], edge: dict[str, object]) -> bool:
    chrome_desktop = _as_object_dict(chrome.get("desktop_dpr1"))
    edge_lifecycle = _as_object_dict(edge.get("lifecycle"))
    return bool(
        (
            chrome_desktop is not None
            and chrome_desktop.get("conflict_detail_gets_before_confirm") == 0
            and chrome_desktop.get("conflict_detail_gets_after_confirm") == 1
            and chrome_desktop.get("components_after_recovery") == 14
        )
        or _lifecycle_complete(edge_lifecycle)
    )


def _lifecycle_complete(lifecycle: dict[str, object] | None) -> bool:
    return bool(
        lifecycle is not None
        and lifecycle.get("instantiate_status") == 201
        and lifecycle.get("save_version_status") == 201
        and lifecycle.get("configured_component_persisted_after_reopen") is True
        and lifecycle.get("status") == "passed"
    )


def _evidence_status(*, failed: bool, complete: bool, partial: bool) -> Status:
    if failed:
        return "fail"
    if complete:
        return "pass"
    if partial:
        return "partial"
    return "missing"


def _collect_dependency_evidence(repository_root: Path, output_dir: Path) -> dict[str, Status]:
    statuses: dict[str, Status] = {}
    source_licenses = repository_root / VERIFICATION_ROOT / "licenses-m3.csv"
    target_licenses = output_dir / "licenses-m3.csv"
    if source_licenses.exists():
        _copy_redacted_text(source_licenses, target_licenses)
        with source_licenses.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        by_package = {row.get("package"): row for row in rows}
        expected_candidates = {
            "echarts": "6.1.0",
            "react-grid-layout": "2.2.3",
            "gridstack": "12.6.0",
        }
        statuses["M3-D01"] = (
            "pass"
            if rows
            and len(by_package) == len(rows)
            and all(row.get("commercial_compatibility") == "compatible" for row in rows)
            and all(row.get("license") for row in rows)
            and all(row.get("relationship") in {"direct", "transitive"} for row in rows)
            and all(row.get("evidence_files") for row in rows)
            and all(
                package in by_package and by_package[package].get("version") == version
                for package, version in expected_candidates.items()
            )
            else "fail"
        )
    else:
        statuses["M3-D01"] = "missing"

    source_bundle = repository_root / VERIFICATION_ROOT / "bundle-m3.json"
    source_build_log = repository_root / VERIFICATION_ROOT / "m3-r0-frontend-build.log"
    target_bundle = output_dir / "bundle-m3.json"
    target_build_log = output_dir / "bundle-build.log"
    if source_bundle.exists() and source_build_log.exists():
        _copy_redacted_text(source_bundle, target_bundle)
        _copy_redacted_text(source_build_log, target_build_log)
        try:
            bundle = _read_json(source_bundle)
        except (json.JSONDecodeError, ValueError):
            statuses["M3-D02"] = "fail"
        else:
            decision = _as_object_dict(bundle.get("decision"))
            inputs = _as_object_dict(bundle.get("inputs"))
            lock_sha256 = inputs.get("package_lock_sha256") if inputs is not None else None
            structure_valid = (
                decision is not None
                and decision.get("echarts_initial_load") == "deferred"
                and _bundle_section_valid(bundle.get("baseline"))
                and _bundle_section_valid(bundle.get("candidate"))
            )
            build_log = source_build_log.read_text(encoding="utf-8", errors="replace")
            build_bound = isinstance(lock_sha256, str) and (
                f"package_lock_sha256={lock_sha256}" in build_log
            )
            statuses["M3-D02"] = "pass" if structure_valid and build_bound else "partial"
    else:
        statuses["M3-D02"] = "missing"

    package_path = repository_root / "frontend/package.json"
    lockfile_path = repository_root / "frontend/package-lock.json"
    package = _read_json(package_path)
    dependencies = _as_object_dict(package.get("dependencies"))
    lockfile = _read_json(lockfile_path)
    lock_packages = _as_object_dict(lockfile.get("packages"))
    lock_versions = {
        "echarts": _lock_package_version(lock_packages, "echarts"),
        "react-grid-layout": _lock_package_version(lock_packages, "react-grid-layout"),
        "gridstack": _lock_package_version(lock_packages, "gridstack"),
    }
    dependency_pass = (
        dependencies is not None
        and all(
            dependencies.get(package_name) == version
            for package_name, version in EXPECTED_DEPENDENCY_VERSIONS.items()
        )
        and "gridstack" not in dependencies
        and lock_packages is not None
        and lock_versions
        == {
            "echarts": "6.1.0",
            "react-grid-layout": "2.2.3",
            "gridstack": None,
        }
    )
    commit_proof = _dependency_commit_proof(repository_root)
    statuses["M3-D03"] = (
        "fail" if not dependency_pass else "pass" if commit_proof["verified"] is True else "partial"
    )
    _write_json(
        output_dir / "dependency-lock-admission.json",
        {
            "schema_version": 1,
            "status": statuses["M3-D03"],
            "production_dependencies": {
                "echarts": dependencies.get("echarts") if dependencies is not None else None,
                "react-grid-layout": (
                    dependencies.get("react-grid-layout") if dependencies is not None else None
                ),
                "gridstack_present": (
                    "gridstack" in dependencies if dependencies is not None else None
                ),
            },
            "lockfile_versions": lock_versions,
            "lockfile_sha256": _sha256(lockfile_path),
            "independent_commit_proof": commit_proof,
        },
    )
    return statuses


def _bundle_section_valid(value: object) -> bool:
    section = _as_object_dict(value)
    if section is None:
        return False
    for key in ("initial", "total"):
        sizes = _as_object_dict(section.get(key))
        if sizes is None or not all(
            isinstance(sizes.get(name), int) and cast(int, sizes[name]) >= 0
            for name in ("raw_bytes", "gzip_bytes", "brotli_bytes")
        ):
            return False
    return isinstance(section.get("chunks"), list)


def _lock_package_version(
    lock_packages: dict[str, object] | None,
    package_name: str,
) -> str | None:
    if lock_packages is None:
        return None
    package = _as_object_dict(lock_packages.get(f"node_modules/{package_name}"))
    version = package.get("version") if package is not None else None
    return version if isinstance(version, str) else None


def _dependency_commit_proof(repository_root: Path) -> dict[str, object]:
    try:
        commit_sha = (
            _git_bytes(
                repository_root,
                "rev-parse",
                f"{DEPENDENCY_COMMIT}^{{commit}}",
            )
            .decode("ascii")
            .strip()
        )
        changed_files = sorted(
            path
            for path in _git_bytes(
                repository_root,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                commit_sha,
            )
            .decode("utf-8")
            .splitlines()
            if path
        )
        package = json.loads(
            _git_bytes(
                repository_root,
                "show",
                f"{commit_sha}:frontend/package.json",
            )
        )
        lockfile = json.loads(
            _git_bytes(
                repository_root,
                "show",
                f"{commit_sha}:frontend/package-lock.json",
            )
        )
        dependencies = _as_object_dict(cast(dict[str, object], package).get("dependencies"))
        lock_packages = _as_object_dict(cast(dict[str, object], lockfile).get("packages"))
        versions_match = dependencies is not None and all(
            dependencies.get(name) == version
            and _lock_package_version(lock_packages, name) == version
            for name, version in EXPECTED_DEPENDENCY_VERSIONS.items()
        )
        verified = changed_files == [
            "frontend/package-lock.json",
            "frontend/package.json",
        ] and bool(versions_match)
        return {
            "commit_sha": commit_sha,
            "changed_files": changed_files,
            "verified": verified,
        }
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "commit_sha": DEPENDENCY_COMMIT,
            "changed_files": [],
            "verified": False,
        }


def _fixture_metadata(repository_root: Path) -> dict[str, Any]:
    fixture_root = repository_root / FIXTURE_ROOT
    manifest_path = fixture_root / "manifest.json"
    manifest = _read_json(manifest_path)
    chart_cases = _read_json(fixture_root / "chart_cases.json")
    return {
        "fixture_version": manifest.get("fixture_version"),
        "manifest_sha256": _sha256(manifest_path),
        "chart_case_ids": _case_ids(chart_cases.get("cases")),
        "filter_case_ids": _case_ids(chart_cases.get("filter_cases")),
    }


def _copy_fixture_manifest(repository_root: Path, output_dir: Path) -> None:
    _copy_redacted_text(
        repository_root / FIXTURE_ROOT / "manifest.json",
        output_dir / "fixture-manifest.json",
    )


def _copy_redacted_text(source: Path, target: Path) -> None:
    if source.resolve() == target.resolve():
        raise ValueError(f"Evidence source and target must differ: {source}")
    content = source.read_text(encoding="utf-8", errors="replace")
    target.write_text(redact_secrets(content), encoding="utf-8")


def _environment_payload(
    git_sha: str,
    *,
    provenance: dict[str, object],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "git_sha": git_sha,
        "captured_at": datetime.now(UTC).isoformat(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "provenance": provenance,
    }


def _git_sha(repository_root: Path) -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repository_root,
        capture_output=True,
        check=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _git_provenance(
    repository_root: Path,
    *,
    git_sha: str | None,
) -> dict[str, object]:
    head_sha = _git_sha(repository_root)
    status = _git_bytes(repository_root, "status", "--porcelain=v1", "-z")
    dirty = bool(status)
    snapshot_sha256: str | None = None
    if dirty:
        digest = hashlib.sha256()
        digest.update(b"status\0")
        digest.update(status)
        digest.update(b"diff\0")
        digest.update(_git_bytes(repository_root, "diff", "--binary", "HEAD", "--"))
        untracked = _git_bytes(
            repository_root,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        )
        for raw_path in sorted(path for path in untracked.split(b"\0") if path):
            digest.update(b"untracked\0")
            digest.update(raw_path)
            path = repository_root / raw_path.decode("utf-8", errors="surrogateescape")
            if path.is_file():
                digest.update(_sha256(path).encode("ascii"))
        snapshot_sha256 = digest.hexdigest()
    return {
        "git_sha": git_sha or head_sha,
        "head_sha": head_sha,
        "git_sha_override": git_sha is not None,
        "worktree_state": "dirty" if dirty else "clean",
        "worktree_diff_sha256": snapshot_sha256,
    }


def _git_bytes(repository_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ("git", *args),
        cwd=repository_root,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def _write_commands_log(path: Path, results: Iterable[CommandResult]) -> None:
    sections = [_format_command_result(result) for result in results]
    path.write_text("\n".join(sections), encoding="utf-8")


def _write_command_log(path: Path, results: dict[str, CommandResult], keys: Sequence[str]) -> None:
    selected = [results[key] for key in keys if key in results]
    content = "\n".join(_format_command_result(result) for result in selected)
    if not content:
        content = "status=missing\nreason=command group was not executed\n"
    path.write_text(content, encoding="utf-8")


def _format_command_result(result: CommandResult) -> str:
    return (
        f"command_key={result.key}\n"
        f"command={result.command}\n"
        f"cwd={result.cwd}\n"
        f"started_at={result.started_at}\n"
        f"duration_seconds={result.duration_seconds}\n"
        f"exit_code={result.exit_code}\n"
        "stdout:\n"
        f"{result.stdout.rstrip()}\n"
        "stderr:\n"
        f"{result.stderr.rstrip()}\n"
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return cast(dict[str, Any], value)


def _as_object_dict(value: object) -> dict[str, object] | None:
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _case_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    case_ids: list[str] = []
    for item in cast(list[object], value):
        case = _as_object_dict(item)
        if case is not None and isinstance(case.get("case_id"), str):
            case_ids.append(cast(str, case["case_id"]))
    return case_ids


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command_results_bytes(
    keys: Sequence[str],
    results: dict[str, CommandResult],
) -> bytes:
    payload = [
        _command_result_payload(results[key]) if key in results else {"key": key, "missing": True}
        for key in keys
    ]
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _command_results_sha256(
    keys: Sequence[str],
    results: dict[str, CommandResult],
) -> str:
    return hashlib.sha256(_command_results_bytes(keys, results)).hexdigest()


def _artifact_evidence_sha256(
    output_dir: Path,
    filenames: Sequence[str],
    command_keys: Sequence[str],
    results: dict[str, CommandResult],
) -> str:
    digest = hashlib.sha256()
    for filename in filenames:
        digest.update(b"artifact\0")
        digest.update(filename.encode("utf-8"))
        path = output_dir / filename
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    digest.update(b"commands\0")
    digest.update(_command_results_bytes(command_keys, results))
    return digest.hexdigest()


def _scan_exported_credentials(output_dir: Path) -> dict[str, object]:
    scanned_files = 0
    findings = 0
    for path in sorted(item for item in output_dir.rglob("*") if item.is_file()):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned_files += 1
        if redact_secrets(content) != content:
            findings += 1
    return {
        "credentials_exported": findings > 0,
        "output_redaction": findings == 0,
        "scanned_files": scanned_files,
        "files_with_findings": findings,
    }


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _statuses() -> tuple[Status, ...]:
    return ("pass", "partial", "missing", "fail")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    specs = command_specs(
        include_postgresql=not args.skip_postgresql,
        include_backend_quality=not args.skip_backend_quality,
        include_frontend_quality=not args.skip_frontend_quality,
    )
    index = collect_evidence(
        args.output_dir,
        evidence_root=args.evidence_root,
        specs=specs,
    )
    print(json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if index["overall_status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
