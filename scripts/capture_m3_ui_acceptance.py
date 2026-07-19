# ruff: noqa: E501
"""Capture fail-closed browser evidence for the M3 UI acceptance gaps.

The acceptance collector intentionally treats the three evidence arrays as opaque
containers.  This helper produces their contents with the assertions that make
those containers reviewable: request/response checks, DOM and Canvas checks,
fixed bounding boxes, screenshots and SHA-256 bindings.  It never edits the
collector's evidence root; the coordinator must review and ingest the produced
``ui-closure.json`` explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPOSITORY_ROOT / ".tmp/m3-r3-acceptance/ui-closure"
DEFAULT_AUTH_STATE = REPOSITORY_ROOT / ".tmp/m3-r3-desktop-a-auth.json"
DEFAULT_DASHBOARD_ID = "3e3fd4a9-f8b7-49be-90de-81a74043a167"
FIXTURE_ROOT = REPOSITORY_ROOT / "spikes/m3/quality/fixture/v2"
CORE_CASE_TYPES = (
    "kpi",
    "detail_table",
    "ranking_table",
    "bar",
    "horizontal_bar",
    "stacked_bar",
    "line",
    "area",
    "pie",
    "donut",
)
FIXTURE_FIELD_BINDINGS: dict[str, tuple[tuple[str, str], ...]] = {
    "kpi-gross": (("gross_amount", "value"),),
    "detail-products": (("product_name", "dimension"), ("gross_amount", "value")),
    "ranking-products-top2": (("product_name", "dimension"), ("gross_amount", "value")),
    "bar-category": (("category", "dimension"), ("gross_amount", "value")),
    "horizontal-bar-region": (("region_name", "dimension"), ("gross_amount", "value")),
    "stacked-category-region": (
        ("category", "dimension"),
        ("region_name", "series"),
        ("gross_amount", "value"),
    ),
    "line-month": (("month", "dimension"), ("gross_amount", "value")),
    "area-month": (("month", "dimension"), ("gross_amount", "value")),
    "pie-category": (("category", "dimension"), ("gross_amount", "value")),
    "donut-category": (("category", "dimension"), ("gross_amount", "value")),
}


class CaptureError(RuntimeError):
    """Raised when the runtime cannot prove the requested acceptance claim."""


@dataclass(frozen=True)
class CommandRecord:
    argv: list[str]
    exit_code: int
    stdout_sha256: str
    stderr_sha256: str


class PlaywrightCli:
    def __init__(
        self, executable: Sequence[str], session: str, records: list[CommandRecord]
    ) -> None:
        self.executable = executable
        self.session = session
        self.records = records

    def run(self, *arguments: str, timeout: int = 60) -> Any:
        argv = [*self.executable, f"-s={self.session}", *arguments, "--json"]
        try:
            completed = subprocess.run(
                argv,
                cwd=REPOSITORY_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            stdout = _timeout_output(error.stdout)
            stderr = _timeout_output(error.stderr)
            self.records.append(
                CommandRecord(
                    argv=_redact_command(argv),
                    exit_code=124,
                    stdout_sha256=_sha256_text(stdout),
                    stderr_sha256=_sha256_text(stderr),
                )
            )
            raise CaptureError(
                f"playwright command timed out after {timeout}s: {arguments[0]}"
            ) from error
        except OSError as error:
            raise CaptureError(f"could not start playwright-cli: {error}") from error
        self.records.append(
            CommandRecord(
                argv=_redact_command(argv),
                exit_code=completed.returncode,
                stdout_sha256=_sha256_text(completed.stdout),
                stderr_sha256=_sha256_text(completed.stderr),
            )
        )
        if completed.returncode:
            raise CaptureError(
                f"playwright command failed ({completed.returncode}): {arguments[0]}"
            )
        return _decode_cli_output(completed.stdout)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_output(*arguments: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    )
    return completed.stdout if binary else completed.stdout.decode("utf-8")


def _producer_provenance() -> dict[str, object]:
    head_sha = cast(str, _git_output("rev-parse", "HEAD")).strip()
    status = cast(str, _git_output("status", "--porcelain=v1", "--untracked-files=all"))
    tracked_diff = cast(bytes, _git_output("diff", "--binary", "HEAD", binary=True))
    source_paths = {
        "ui_capture": Path(__file__),
        "fixture_chart_cases": FIXTURE_ROOT / "chart_cases.json",
        "fixture_golden_results": FIXTURE_ROOT / "golden_results.json",
        "fixture_manifest": FIXTURE_ROOT / "manifest.json",
    }
    source_hashes = {name: _sha256_file(path) for name, path in source_paths.items()}
    snapshot = {
        "head_sha": head_sha,
        "tracked_diff_sha256": hashlib.sha256(tracked_diff).hexdigest(),
        "git_status_sha256": _sha256_text(status),
        "source_content_sha256": source_hashes,
    }
    return {
        **snapshot,
        "worktree_state": "dirty" if status.strip() else "clean",
        "source_snapshot_sha256": _sha256_text(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        ),
    }


def _timeout_output(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _redact_command(argv: list[str]) -> list[str]:
    """Keep paths and browser actions reproducible without serializing secrets."""
    return [
        "<auth-state>" if argument.endswith("auth-state.json") else argument for argument in argv
    ]


def _decode_cli_output(stdout: str) -> Any:
    """Decode the CLI JSON envelope without accepting arbitrary textual output."""
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError:
        decoded = None
    if decoded is not None:
        return _extract_cli_result(decoded)
    candidates = [line.strip() for line in stdout.splitlines() if line.strip()]
    for candidate in reversed(candidates):
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return _extract_cli_result(decoded)
    raise CaptureError("playwright-cli did not return a JSON result")


def _extract_cli_result(decoded: object) -> Any:
    if isinstance(decoded, dict) and "result" in decoded:
        result = cast(dict[str, Any], decoded)["result"]
        if isinstance(result, str):
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return result
        return result
    return cast(Any, decoded)


def _resolve_playwright_cli(command: str) -> list[str]:
    """Use the cmd shim on Windows; ``which`` otherwise prefers a non-executable shim."""
    path = Path(command)
    if path.is_file():
        return [str(path)]
    if sys.platform == "win32":
        command_shim = shutil.which(f"{command}.cmd")
        if command_shim:
            return [command_shim]
    resolved = shutil.which(command)
    if resolved:
        return [resolved]
    raise CaptureError(f"playwright-cli was not found: {command}")


def _read_fixture() -> tuple[dict[str, Any], dict[str, Any], str]:
    chart_cases = json.loads((FIXTURE_ROOT / "chart_cases.json").read_text(encoding="utf-8"))
    golden = json.loads((FIXTURE_ROOT / "golden_results.json").read_text(encoding="utf-8"))
    manifest = FIXTURE_ROOT / "manifest.json"
    if not manifest.is_file():
        raise CaptureError(f"fixture manifest is missing: {manifest}")
    return chart_cases, golden, _sha256_file(manifest)


def _javascript_payload(
    *,
    dashboard_id: str,
    frontend_url: str,
    api_url: str,
    chart_cases: dict[str, Any],
    golden: dict[str, Any],
    screenshot_prefix: str,
) -> str:
    """Return one self-contained Playwright callback with all UI assertions."""
    payload = json.dumps(
        {
            "dashboardId": dashboard_id,
            "frontendUrl": frontend_url.rstrip("/"),
            "apiUrl": api_url.rstrip("/"),
            "chartCases": chart_cases["cases"],
            "golden": golden,
            "fixtureBindings": FIXTURE_FIELD_BINDINGS,
            "screenshotPrefix": screenshot_prefix.replace("\\", "/"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"""async (page) => {{
  const input = {payload};
  const responses = [];
  const onResponse = async (response) => {{
    if (!response.url().endsWith('/dashboard-chart-queries')) return;
    let body = null;
    try {{ body = await response.json(); }} catch {{ /* handled by assertion */ }}
    responses.push({{ status: response.status(), body }});
  }};
  page.on('response', onResponse);
  await page.goto(`${{input.frontendUrl}}/dashboards/${{input.dashboardId}}`, {{
    waitUntil: 'domcontentloaded', timeout: 30000,
  }});
  await page.waitForFunction(
    () => document.querySelectorAll('.dashboard-component-placeholder').length > 0 &&
      !document.querySelector('[aria-label="正在加载图表数据"]'),
    {{ timeout: 45000 }},
  );
  await page.waitForTimeout(500);
  const detail = await page.evaluate(async (url) => {{
    const response = await fetch(url, {{ credentials: 'include' }});
    if (!response.ok) throw new Error(`dashboard detail request failed: ${{response.status}}`);
    return response.json();
  }}, `${{input.apiUrl}}/dashboards/${{input.dashboardId}}`);
  const components = (detail.pages ?? []).flatMap((page) => page.components ?? []);
  const pointer = (root, path) => path.slice(1).split('/').reduce((value, part) => value?.[part], root);
  const canonicalRows = (rows, bindings) => rows.map((row) => Object.fromEntries(
    bindings.map((binding) => [binding.fixture_field, row[binding.query_alias]]),
  )).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  const sameRows = (left, right) => JSON.stringify(left) === JSON.stringify(right);
  const chartCases = await Promise.all(input.chartCases.map(async (chartCase) => {{
    const component = components.find((item) => item.component_type === chartCase.component_type);
    const componentId = component?.component_id ?? component?.id ?? null;
    const article = componentId
      ? page.locator(`[data-component-id="${{componentId}}"]`)
      : null;
    const articlePresent = Boolean(article && await article.count() === 1);
    const expected = pointer(input.golden, chartCase.golden_pointer);
    const response = responses.find((item) => item.body?.component_id === componentId) ?? null;
    const responseRows = response?.body?.rows ?? response?.body?.data?.rows ?? null;
    const expectedRows = Array.isArray(expected) ? expected : [expected];
    const bindings = (input.fixtureBindings[chartCase.case_id] ?? []).map(([fixture_field, slot_key]) => {{
      const column = response?.body?.columns?.find((item) => item.slot_key === slot_key);
      return {{
        fixture_field,
        expected_slot_key: slot_key,
        slot_key: column?.slot_key ?? null,
        query_alias: column?.query_alias ?? null,
        label: column?.label ?? null,
        resource_kind: column?.resource_kind ?? null,
      }};
    }});
    const bindingsComplete = bindings.length > 0 && bindings.every((binding) =>
      binding.slot_key === binding.expected_slot_key && typeof binding.query_alias === 'string' &&
      binding.query_alias.length > 0 && typeof binding.label === 'string' && binding.label.length > 0 &&
      ['field', 'metric'].includes(binding.resource_kind));
    const actualCanonical = bindingsComplete && Array.isArray(responseRows)
      ? canonicalRows(responseRows, bindings) : [];
    const expectedCanonical = bindingsComplete
      ? canonicalRows(expectedRows, bindings) : [];
    const text = articlePresent ? await article.innerText() : '';
    const nonBlankCanvas = articlePresent && await article.locator('canvas').first().evaluate((canvas) => {{
      const context = canvas.getContext('2d');
      const pixels = context?.getImageData(0, 0, canvas.width, canvas.height).data;
      return Boolean(pixels && [...pixels].some((value) => value !== 0));
    }}).catch(() => false);
    const checks = {{
      component_present: articlePresent,
      response_ok: response?.status === 200,
      response_columns_bound: bindingsComplete,
      response_matches_golden: expected !== undefined && sameRows(actualCanonical, expectedCanonical),
      no_error_fallback: !text.includes('图表查询失败'),
      canvas_nonblank_when_required: !['kpi', 'detail_table', 'ranking_table'].includes(chartCase.component_type) ? nonBlankCanvas : true,
    }};
    const passed = Object.values(checks).every(Boolean);
    return {{
      case_id: chartCase.case_id,
      component_type: chartCase.component_type,
      bindings,
      response_row_count: Array.isArray(responseRows) ? responseRows.length : null,
      expected_row_count: expectedRows.length,
      checks,
      passed,
    }};
  }}));
  const firstArticle = page.locator('.dashboard-component-placeholder').filter({{ has: page.locator('canvas') }}).first();
  if (await firstArticle.count() !== 1) throw new Error('no Canvas-backed chart was rendered');
  const stableBox = async (label) => {{
    const box = await firstArticle.boundingBox();
    if (!box) throw new Error(`missing component box for ${{label}}`);
    return {{ label, x: Math.round(box.x * 10) / 10, y: Math.round(box.y * 10) / 10,
      width: Math.round(box.width * 10) / 10, height: Math.round(box.height * 10) / 10 }};
  }};
  const normal = await stableBox('success');
  const canvas = firstArticle.locator('canvas').first();
  await canvas.hover();
  await page.waitForTimeout(250);
  const hover = await stableBox('hover');
  const dimensions = {{ success: normal, hover, stable: normal.width === hover.width && normal.height === hover.height }};
  await page.screenshot({{ path: `${{input.screenshotPrefix}}-success.png` }});
  page.off('response', onResponse);
  const passed = chartCases.length === input.chartCases.length && chartCases.every((item) => item.passed) && dimensions.stable;
  return {{ chart_cases: chartCases, fixed_dimensions: dimensions, passed }};
}}"""


def _state_javascript(
    *, dashboard_id: str, frontend_url: str, api_url: str, screenshot_prefix: str
) -> str:
    """Exercise UI05's five fixed-dimension states and UI08's three view states."""
    frontend_url = frontend_url.rstrip("/")
    api_url = api_url.rstrip("/")
    prefix = screenshot_prefix.replace("\\", "/")
    return f"""async (page) => {{
  const url = '{frontend_url}/dashboards/{dashboard_id}';
  const detailUrl = '{api_url}/dashboards/{dashboard_id}';
  const chartPattern = '**/dashboard-chart-queries';
  await page.goto(url, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
  const initialTarget = page.locator('.dashboard-component-placeholder').filter({{ has: page.locator('canvas') }}).first();
  await initialTarget.waitFor({{ timeout: 45000 }});
  const componentId = await initialTarget.getAttribute('data-component-id');
  if (!componentId) throw new Error('query component is missing a stable component id');
  const target = page.locator(`[data-component-id="${{componentId}}"]`);
  const box = async (state) => {{
    const value = await target.boundingBox();
    if (!value) throw new Error(`missing bounding box for ${{state}}`);
    return {{ state, x: value.x, y: value.y, width: value.width, height: value.height }};
  }};
  const success = await box('success');
  await page.screenshot({{ path: '{prefix}-success-state.png' }});
  await target.locator('canvas').first().hover();
  await page.waitForTimeout(250);
  const hover = await box('hover');
  async function loadWith(handler) {{
    await page.route(chartPattern, handler);
    await page.goto(url, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
    await target.waitFor({{ timeout: 45000 }});
  }}
  let delayedRequest = false;
  const delayedRoutes = [];
  await loadWith(async (route) => {{
    if (!delayedRequest) {{
      delayedRequest = true;
      await page.waitForTimeout(1500);
    }}
    try {{ await route.continue(); }} catch (error) {{ delayedRoutes.push(String(error)); }}
  }});
  const loading = {{
    visible: await target.locator('[aria-label="正在加载图表数据"]').count() > 0,
    cancel_visible: await target.getByRole('button', {{ name: '取消查询' }}).count() > 0,
  }};
  const loadingBox = await box('loading');
  await page.screenshot({{ path: '{prefix}-loading.png' }});
  await page.unroute(chartPattern);
  await page.waitForFunction(() => !document.querySelector('[aria-label="正在加载图表数据"]'), {{ timeout: 45000 }});
  await loadWith(async (route) => {{
    await route.fulfill({{ status: 200, contentType: 'application/json', body: JSON.stringify({{ columns: [], rows: [], truncated: false }}) }});
  }});
  const emptyText = await target.innerText();
  const empty = {{
    visible: emptyText.includes('当前筛选条件下暂无数据'),
    no_zero_value: !/(^|\\s)0(?:\\.0+)?($|\\s)/.test(emptyText),
  }};
  const emptyBox = await box('empty');
  await page.screenshot({{ path: '{prefix}-empty.png' }});
  await page.unroute(chartPattern);
  await loadWith(async (route) => {{
    await route.fulfill({{ status: 500, contentType: 'application/json', body: JSON.stringify({{ detail: {{ code: 'm3_ui_closure_test', message: 'intentional browser state test' }} }}) }});
  }});
  const error = {{
    visible: await target.getByText('图表查询失败', {{ exact: true }}).count() > 0,
    retry_visible: await target.getByRole('button', {{ name: /重\\s*试/ }}).count() > 0,
  }};
  const errorBox = await box('error');
  await page.screenshot({{ path: '{prefix}-error.png' }});
  await page.unroute(chartPattern);
  const longLabel = 'M3-R3 long label ' + 'acceptance '.repeat(24);
  await page.route(detailUrl, async (route) => {{
    const response = await route.fetch();
    const detail = await response.json();
    for (const dashboardPage of detail.pages ?? []) {{
      for (const component of dashboardPage.components ?? []) {{
        if ((component.component_id ?? component.id) === componentId) {{
          component.config = {{ ...component.config, title: longLabel }};
        }}
      }}
    }}
    await route.fulfill({{ response, body: JSON.stringify(detail) }});
  }});
  await page.goto(url, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
  await target.waitFor({{ timeout: 45000 }});
  await target.getByText(longLabel, {{ exact: true }}).waitFor({{ timeout: 45000 }});
  const longLabelBox = await box('long_label');
  await page.screenshot({{ path: '{prefix}-long-label.png' }});
  await page.unroute(detailUrl);
  const boxes = {{ success, loading: loadingBox, empty: emptyBox, error: errorBox, hover, long_label: longLabelBox }};
  const deltas = Object.fromEntries(Object.entries(boxes).map(([state, value]) => [state, {{
    x: value.x - success.x, y: value.y - success.y,
    width: value.width - success.width, height: value.height - success.height,
  }}]));
  const fixedDimensions = Object.values(deltas).every((delta) => delta.width === 0 && delta.height === 0);
  const passed = Object.values(loading).every(Boolean) && Object.values(empty).every(Boolean) &&
    Object.values(error).every(Boolean) && fixedDimensions;
  return {{ component_id: componentId, loading, empty, error, boxes, deltas, fixed_dimensions: fixedDimensions,
    delayed_route_count: delayedRoutes.length, passed }};
}}"""


def _run_browser(
    *,
    browser: str,
    cli_executable: Sequence[str],
    auth_state: Path,
    dashboard_id: str,
    frontend_url: str,
    api_url: str,
    output_dir: Path,
    chart_cases: dict[str, Any],
    golden: dict[str, Any],
) -> tuple[dict[str, Any], PlaywrightCli]:
    records: list[CommandRecord] = []
    session = f"m3-ui-closure-{browser}"
    cli = PlaywrightCli(cli_executable, session, records)
    browser_channel = "chrome" if browser == "chrome" else "msedge"
    completed = False
    try:
        cli.run("open", "about:blank", "--browser", browser_channel)
        cli.run("resize", "1440", "900")
        cli.run("state-load", str(auth_state))
        prefix = output_dir / browser
        runtime_script = output_dir / f"{browser}-runtime.js"
        state_script = output_dir / f"{browser}-states.js"
        runtime_script.write_text(
            _javascript_payload(
                dashboard_id=dashboard_id,
                frontend_url=frontend_url,
                api_url=api_url,
                chart_cases=chart_cases,
                golden=golden,
                screenshot_prefix=str(prefix),
            ),
            encoding="utf-8",
        )
        state_script.write_text(
            _state_javascript(
                dashboard_id=dashboard_id,
                frontend_url=frontend_url,
                api_url=api_url,
                screenshot_prefix=str(prefix),
            ),
            encoding="utf-8",
        )
        runtime = cli.run(
            "run-code",
            "--filename",
            str(runtime_script),
            timeout=120,
        )
        states = cli.run(
            "run-code",
            "--filename",
            str(state_script),
            timeout=120,
        )
        result = {
            "browser": browser,
            "runtime": runtime,
            "states": states,
            "passed": bool(runtime.get("passed") and states.get("passed")),
            "commands": [asdict(record) for record in records],
        }
        completed = True
        return result, cli
    finally:
        if not completed:
            with suppress(CaptureError):
                cli.run("close", timeout=10)


def _attach_file_hashes(output_dir: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(output_dir).as_posix(),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "ui-closure.json"
    ]


def _write_json_atomic(path: Path, payload: object) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def capture(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise CaptureError(f"output directory must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    if not args.auth_state.is_file():
        raise CaptureError(f"auth state is missing: {args.auth_state}")
    cli_executable = _resolve_playwright_cli(args.playwright_cli)
    chart_cases, golden, manifest_sha256 = _read_fixture()
    provenance = _producer_provenance()
    present_types = {item["component_type"] for item in chart_cases["cases"]}
    if present_types != set(CORE_CASE_TYPES):
        raise CaptureError("fixture chart cases no longer cover the frozen core chart matrix")
    browser_runs = [
        _run_browser(
            browser=browser,
            cli_executable=cli_executable,
            auth_state=args.auth_state,
            dashboard_id=args.dashboard_id,
            frontend_url=args.frontend_url,
            api_url=args.api_url,
            output_dir=output_dir,
            chart_cases=chart_cases,
            golden=golden,
        )
        for browser in args.browsers
    ]
    results = [result for result, _cli in browser_runs]
    payload = {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "git_sha": provenance["head_sha"],
        "producer_provenance": provenance,
        "fixture_version": chart_cases.get("fixture_version"),
        "fixture_manifest_sha256": manifest_sha256,
        "case_ids": ["M3-UI04", "M3-UI05", "M3-UI08"],
        "browsers": results,
        "artifacts": _attach_file_hashes(output_dir),
        "passed": all(result["passed"] for result in results),
    }
    _write_json_atomic(output_dir / "ui-closure.json", payload)
    for _result, cli in browser_runs:
        with suppress(CaptureError):
            cli.run("close", timeout=10)
    if not payload["passed"]:
        raise CaptureError(
            f"UI closure assertions failed; inspect {output_dir / 'ui-closure.json'}"
        )
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--auth-state", type=Path, default=DEFAULT_AUTH_STATE)
    parser.add_argument("--dashboard-id", default=DEFAULT_DASHBOARD_ID)
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5173")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--playwright-cli", default="playwright-cli")
    parser.add_argument(
        "--browsers", nargs="+", choices=("chrome", "edge"), default=["chrome", "edge"]
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        capture(parse_args(argv))
    except (CaptureError, subprocess.TimeoutExpired) as error:
        print(f"capture failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
