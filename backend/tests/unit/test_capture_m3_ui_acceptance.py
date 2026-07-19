# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from scripts import capture_m3_ui_acceptance as capture


def test_decode_cli_output_accepts_only_json_result_envelopes() -> None:
    assert capture._decode_cli_output('{"result":"{\\"passed\\":true}"}\n') == {"passed": True}
    assert capture._decode_cli_output('{\n  "result": {"passed": true}\n}\n') == {"passed": True}

    with pytest.raises(capture.CaptureError, match="JSON"):
        capture._decode_cli_output("browser output without JSON")


def test_redacted_command_never_serializes_auth_state_contents() -> None:
    redacted = capture._redact_command(["playwright-cli", "state-load", "C:/tmp/auth-state.json"])

    assert redacted[-1] == "<auth-state>"


def test_timeout_output_handles_text_and_bytes() -> None:
    assert capture._timeout_output("text") == "text"
    assert capture._timeout_output(b"bytes") == "bytes"
    assert capture._timeout_output(None) == ""


def test_windows_cli_resolution_prefers_cmd_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capture.sys, "platform", "win32")

    def fake_which(value: str) -> str | None:
        return "C:/npm/playwright-cli.cmd" if value.endswith(".cmd") else None

    monkeypatch.setattr(
        capture.shutil,
        "which",
        fake_which,
    )

    assert capture._resolve_playwright_cli("playwright-cli") == ["C:/npm/playwright-cli.cmd"]


def test_fixture_core_chart_coverage_is_frozen() -> None:
    chart_cases, _golden, manifest_sha256 = capture._read_fixture()

    assert {item["component_type"] for item in chart_cases["cases"]} == set(capture.CORE_CASE_TYPES)
    assert len(manifest_sha256) == 64


def test_producer_provenance_binds_git_and_capture_inputs() -> None:
    provenance = capture._producer_provenance()

    assert len(str(provenance["head_sha"])) == 40
    assert provenance["worktree_state"] in {"clean", "dirty"}
    assert len(str(provenance["tracked_diff_sha256"])) == 64
    assert len(str(provenance["git_status_sha256"])) == 64
    assert len(str(provenance["source_snapshot_sha256"])) == 64
    source_hashes = cast(dict[str, object], provenance["source_content_sha256"])
    assert set(source_hashes) == {
        "ui_capture",
        "fixture_chart_cases",
        "fixture_golden_results",
        "fixture_manifest",
    }


def test_javascript_payload_contains_fail_closed_data_and_pixel_assertions() -> None:
    chart_cases, golden, _manifest_sha256 = capture._read_fixture()
    source = capture._javascript_payload(
        dashboard_id="dashboard-id",
        frontend_url="http://127.0.0.1:5173",
        api_url="http://127.0.0.1:8000/api/v1",
        chart_cases=chart_cases,
        golden=golden,
        screenshot_prefix=".tmp/ui-closure/chrome",
    )

    for required in (
        "fixtureBindings",
        "response_columns_bound",
        "response_matches_golden",
        "canvas_nonblank_when_required",
        "fixed_dimensions",
        "page.screenshot",
        "chart_cases",
    ):
        assert required in source


def test_capture_refuses_nonempty_output_before_browser_side_effects(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    output.mkdir()
    (output / "existing.json").write_text("{}", encoding="utf-8")
    args = capture.parse_args(["--output-dir", str(output)])

    with pytest.raises(capture.CaptureError, match="empty"):
        capture.capture(args)


def test_attached_hashes_bind_runtime_artifacts_but_not_the_summary(tmp_path: Path) -> None:
    png = tmp_path / "chrome-success.png"
    png.write_bytes(b"png-bytes")
    (tmp_path / "ui-closure.json").write_text(json.dumps({}), encoding="utf-8")

    hashes = capture._attach_file_hashes(tmp_path)

    assert hashes == [
        {
            "path": "chrome-success.png",
            "sha256": "ea80334363eed145dfeee51ebae7dc3f1cd7d0c7879f8bfd2070c061d3c33f56",
            "bytes": 9,
        }
    ]


def test_atomic_json_writer_never_leaves_the_temporary_file(tmp_path: Path) -> None:
    destination = tmp_path / "ui-closure.json"

    capture._write_json_atomic(destination, {"passed": False})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"passed": False}
    assert not destination.with_suffix(".tmp").exists()
