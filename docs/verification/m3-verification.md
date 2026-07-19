# M3 Verification

- Date: 2026-07-19
- Scope: M3 governed dashboards, chart queries, scoped filters, lifecycle editing, templates,
  browser behavior, performance, permissions, portability, and regression gates
- Product baseline: `4a932a5 feat(dashboard): complete lifecycle workbench`
- Evidence hardening: `97c3daf feat(verification): harden M3 acceptance evidence`
- Final Node 24 collector: `7fff5b1 fix(verification): pin Node 24 evidence runner`
- Fixture: `m3-star-v2`, manifest SHA-256
  `015df74d59fb6e70c04c0f05da1392a57a1e8acd919d851d51fff0394f123c8c`

## Outcome

The implemented M3 functional scope and all mandatory repository quality gates pass. The final
acceptance result is nevertheless **conditional and incomplete**, not fully accepted.

The authoritative 40-item collector is preserved in the
[M3 evidence archive](m3/2026-07-19-7fff5b1/artifact-index.json), with file provenance and omitted
trace/network hashes recorded in its [manifest](m3/2026-07-19-7fff5b1/manifest.json). It reports:

| Status | Count |
|---|---:|
| Pass | 18 |
| Partial | 18 |
| Missing | 4 |
| Fail | 0 |

The non-pass items are evidence-completeness gaps, plus the explicit PERF02 server-cache gap.
No product test command or quality gate failed. Missing structured exports do not by themselves
mean that the corresponding product behavior failed; they mean that the frozen acceptance matrix
requires a more specific machine-readable artifact than the current tests or browser runs export.
Those gaps still prevent an unconditional M3 acceptance statement.

The M3 implementation can be used as the functional baseline for subsequent work, but M3 must not
be described as completely accepted until the partial and missing evidence is closed or explicitly
disposed through the accepted milestone process.

## Delivered Scope

- Governed dashboard chart queries execute through M2 datasets, metrics, calculated fields, RLS,
  query limits, timeouts, source evidence, and immutable dashboard-version context.
- Twelve chart renderers, rich text, governed images, global/page/component filters, relative dates,
  Top N, series, labels, legends, tooltips, units, loading, empty, error, timeout, truncation, and
  recovery states are integrated.
- The lifecycle workbench supports pages, drag/resize, copy/paste, version saves, template
  publication and instantiation, reopen persistence, conflict confirmation, and stale-response
  protection.
- Desktop editing and mobile read-only layouts are implemented with accessible chart alternatives,
  named controls, DPR-aware Canvas backing stores, and no mobile edit affordances.
- ECharts remains behind a dynamic import. Production uses `react-grid-layout@2.2.3`;
  `gridstack` remains spike-only and is not admitted as a production dependency.

## Provenance

The lifecycle browser and page-performance evidence was produced against product commit `4a932a5`.
The trusted fixture benchmark, RLS oracle, bounded concurrency runner, portable fingerprints, and
collector hardening were committed as `97c3daf`. Commit `7fff5b1` then pinned the collector's
frontend commands to the isolated Node 24 runner.

The final collector ran at full SHA
`7fff5b1e35674708a08490ab35d941f8aa5924a1`. It records the worktree as dirty rather than
mislabeling it as a clean HEAD run, with snapshot SHA-256
`f53e2f306d5fb611a6492d198842134c1711038502b9cc93e3251dc347cc6ced`. Formal query artifacts
are independently bound to `97c3daf`; their producer source set is recorded as clean. The collector
scanned 64 exported files and found zero credential findings.

Environment inventory:

| Component | Version / value |
|---|---|
| OS | Windows 11 build 26200, AMD64 |
| CPU | Intel Family 6 Model 151, 20 logical processors |
| Python | CPython 3.13.8 |
| Node / npm | Node 24.18.0 / npm 11.18.0 |
| SQLite | 3.50.4 |
| PostgreSQL | 18.1 |
| Chrome | 150.0.7871.127 |
| Edge | 150.0.4078.83 |
| Playwright CLI | 0.1.17 |

## Quality Gates

All commands below exited with status 0 in the final Node 24 collector.

| Gate | Result |
|---|---|
| `uv run python spikes/m3/quality/fixture_tool.py check` | Passed |
| `uv run pytest spikes/m3/quality/tests -q` | 11 passed |
| `uv run pytest spikes/m3/backend/test_chart_query_compiler.py -q` | 24 passed |
| `uv run pytest spikes/m3/backend/test_c1_chart_cases.py -q` | 5 passed |
| SQLite chart/filter portability | 7 passed |
| SQLite dashboard/dataset/permission coverage | 28 passed, 1 warning |
| SQLite dashboard migrations | 2 passed |
| `uv run python scripts/run_postgres_tests.py` | 85 passed, 1 warning; `head -> base -> head` passed |
| `uv run pytest backend/tests -q --cov=bi_system` | 393 passed, 6 environment skips, 1 warning; 91% coverage |
| `uv run ruff check backend scripts` | Passed |
| `uv run ruff format --check backend scripts` | 166 files already formatted |
| `uv run basedpyright backend/src backend/tests scripts` | 0 errors, 0 warnings |
| Frontend lint / Prettier / TypeScript | Passed under Node 24 |
| Frontend Vitest | 22 files, 98 tests passed in 93.23 s |
| Frontend production build | 3,774 modules; Vite build completed in 438 ms |

The backend warning is the known Starlette `TestClient` deprecation. Vitest logs jsdom's unsupported
pseudo-element `getComputedStyle` diagnostic. The production build emits the expected chunk-size
warning for the dynamically isolated ECharts renderer; none of these diagnostics failed a gate.

All six regression and quality matrix gates pass: M3-R01 through M3-R06.

## Performance

All query runs consume the trusted deterministic 100,000-row fixture, use five warmups, retain raw
samples, execute the same seven scenarios and three principals, and report zero errors and zero
timeouts. P95 uses nearest-rank without removing outliers.

### Page And Dashboard

| Case | Browser | Warmups / samples | P50 | P95 | Max | Target | Result |
|---|---|---:|---:|---:|---:|---:|---|
| PERF01 cold HTTP navigation | Chrome 150 | 5 / 30 | 887 ms | 904 ms | 907 ms | 2,000 ms | Pass |
| PERF02 warmed dashboard display | Chrome 150 | 5 / 30 | 876 ms | 1,029 ms | 1,061 ms | 3,000 ms | Partial |

PERF02 meets the observed display-time target and finishes with 14 components, no loading or
fallback states, and no chart error. It remains **partial** because no server result cache exists and
the frozen case explicitly requires an observed warmed server-query cache. This is not relabeled as
a pass and is not treated as a current product failure. Query-cache keys, invalidation, PostgreSQL
tuning, and cold/hot cache acceptance are deliberately deferred to the already planned M4-R3 cache
packet.

### Governed Query Runs

The top-level timing below measures one worker serially executing the complete seven-query mix. It is
reported for throughput and round duration, but it is not the single-query acceptance gate. The hard
5,000 ms gate uses the maximum per-scenario client P95.

| Database | Concurrency / rounds / samples | Mix P50 | Mix P95 | Mix max | Throughput | Wall time | Max scenario P95 | Errors / timeouts |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SQLite 3.50.4 | 1 / 30 / 30 | 2,830.668 ms | 2,983.625 ms | 3,047.365 ms | 0.351 rps | 85.520 s | 915.508 ms | 0 / 0 |
| PostgreSQL 18.1 | 1 / 30 / 30 | 1,740.279 ms | 2,013.806 ms | 2,178.627 ms | 0.573 rps | 52.377 s | 637.112 ms | 0 / 0 |
| PostgreSQL 18.1 | 20 / 3 / 60 | 5,619.313 ms | 6,156.158 ms | 6,179.528 ms | 3.413 rps | 17.578 s | 1,778.729 ms | 0 / 0 |

The PostgreSQL c20 mix P95 exceeds 5 seconds only because it is the serial duration of seven queries;
it is explicitly not used as the single-query gate. Every representative scenario remains below
5,000 ms, all rounds are complete, all result fingerprints are stable, SQLite/PostgreSQL scenario
fingerprints match, and the full restricted-viewer R-NORTH oracle matches.

Per-scenario client P95:

| Scenario / principal | SQLite c1 | PostgreSQL c1 | PostgreSQL c20 |
|---|---:|---:|---:|
| Full KPI / administrator | 369.119 ms | 315.903 ms | 1,775.164 ms |
| Category bar / administrator | 379.796 ms | 327.552 ms | 933.908 ms |
| Category-region stacked / administrator | 915.508 ms | 637.112 ms | 1,778.729 ms |
| Month trend / editor | 430.668 ms | 290.188 ms | 775.339 ms |
| Top 2 / editor | 412.931 ms | 309.826 ms | 769.814 ms |
| Global-page-component filters / editor | 292.821 ms | 282.779 ms | 1,020.127 ms |
| Restricted viewer same group / restricted viewer | 270.540 ms | 257.562 ms | 604.903 ms |

The intentional Top-2 result is truncated in every sample: 30 SQLite c1, 30 PostgreSQL c1, and 60
PostgreSQL c20 samples. Truncation is stable and included in the result fingerprints.

### Timeout, Retry, And Cancellation

PERF05 passes in Chrome 150. Progress appears at 3,338 ms before the 10-second service constraint;
the controlled request returns HTTP 504 with `dataset_query_timeout`, and the timeout state is visible
at 4,230 ms. One explicit retry recovers at 4,537 ms with no stale timeout. Cancellation is clicked at
5,920 ms, aborts the request with `net::ERR_ABORTED`, and a deliberately delayed response does not
restore result, loading, or timeout state. The only console error is the expected controlled HTTP 504;
unexpected errors and warnings are zero.

## Browser Results

Playwright CLI used real Chrome and Edge channels against the real Vite/FastAPI services. Business
flows have zero console errors and warnings; each controlled 409 flow records exactly one expected
HTTP error.

| Browser / viewport | Layout and rendering | Workflow result |
|---|---|---|
| Chrome desktop, 1440 x 900, DPR 1 | 14 components, 0 overlaps, 0 horizontal overflow, 7/7 nonblank Canvas, 174 x 152 CSS and pixel Canvas | Keyboard copy/paste 14 -> 15; controlled conflict preserves draft and reloads only after confirmation; recovered to 14 components |
| Chrome mobile, 390 x 844, DPR 2 | 14 static components, 0 overlaps/overflow, 7/7 nonblank Canvas, 318 x 176 CSS / 636 x 352 backing, exported PNG 780 x 1688 | 0 edit controls and resize handles; 12 relative-date filter queries; read-only behavior passed |
| Edge desktop, 1440 x 900, DPR 1 | 14 components, 0 overlaps, 0 horizontal overflow, 7/7 nonblank Canvas | Template instantiate 201, save version 201, v2 persists after reopen; conflict recovery and keyboard copy/paste passed |
| Edge mobile, 390 x 844, DPR 1 | 14 static components, 0 overlaps/overflow, 7/7 nonblank Canvas, 318 x 176 backing | 0 edit controls and resize handles; 12 relative-date filter queries; read-only behavior passed |
| Edge mobile, 390 x 844, DPR 2 | 14 components, 7/7 nonblank Canvas, 318 x 176 CSS / 636 x 352 backing, exported PNG 780 x 1688 | DPR 2 rendering passed |

Accessibility evidence contains no unnamed buttons. Desktop exposes a named 12-column dashboard
canvas, 12 accessible data tables, named legend/label/tooltip switches, and named lifecycle/page
commands. Mobile exposes a named read-only canvas, a named filter button, named global/page/component
filter fields, and non-focusable static components.

The retained failed Chrome trace is superseded evidence from transient service contention. Its four
CORS/fetch errors plus the expected 409 are not counted as the final business-console result; the
replacement trace is clean.

## Dependency, Bundle, And License Gates

- Production dependency admission passes for `echarts@6.1.0` and
  `react-grid-layout@2.2.3`; `gridstack` is absent from production dependencies.
- The dependency commit proof for `f99962b` is verified and changes only
  `frontend/package.json` and `frontend/package-lock.json`.
- The spike bundle records 19 reviewed packages across 0BSD, Apache-2.0, BSD-3-Clause, ISC, and MIT,
  with zero review-required entries.
- ECharts is deferred from the initial closure. The spike candidate records 286,895 B raw / 87,234 B
  gzip / 75,502 B brotli initially and 645,381 B raw / 211,977 B gzip / 179,936 B brotli lazily.
- The final production build keeps `EChartRenderer` dynamic at 556.24 kB raw / 188.93 kB Vite gzip.

## Partial And Missing Evidence

### Contracts And Query Correctness

Partial: M3-C02 through M3-C06. Tests prove negative-contract rejection, golden values, filter order,
typed portability, and stable Top N, but the collector does not receive every requested error payload,
compiled AST, raw row/value set, resolved predicate, leakage scan, or ten-run ordered-result export.

### Database Portability

Partial: M3-DB01 and M3-DB02. SQLite and PostgreSQL golden tests pass, but neither exports the complete
normalized golden result set. Missing: M3-DB03, because no current harness emits both dialect outputs
in one field-by-field comparison artifact. Migrations, PostgreSQL integration, and cross-dialect
scenario fingerprints still pass; the missing export is not evidence of a known database mismatch.

### Permissions And RLS

Partial: M3-P01 through M3-P05. Principal, RLS, forged-filter, cross-workspace, and capability behavior
is asserted by passing tests. The missing detail is a complete same-query editor matrix plus unified
structured exports for pre-aggregate cache/tooltip exclusion, an unexpressible RLS-removal attempt,
resource-by-resource cross-workspace results, and atomic no-partial-write state.

### Performance

Partial: M3-PERF02 only. The observed P95 is 1,029 ms, but server-result-cache observation and its full
sample contract are absent. The implementation and invalidation contract remain deferred to M4-R3.

### Browser And UI

Partial: M3-UI01, M3-UI02, M3-UI09, M3-UI10, and M3-UI11. Existing browser evidence proves the core
Chrome/Edge desktop/mobile workflows, accessibility, DPR 2 rendering, controlled conflicts, and
recovery, but it does not provide the matrix's complete desktop stress profiles, chart golden export,
fixed-dimension artifact, all view-state exports, or a fully symmetric lifecycle artifact for both
browsers.

Missing: M3-UI04, M3-UI05, and M3-UI08. No dedicated structured runtime artifact was provided for
core chart pixel golden comparison, fixed-dimension invariants, or the complete loading/success/empty
state matrix. This does not erase the passing renderer tests and browser observations; it prevents the
collector from promoting those specific acceptance items to pass.

## Final Disposition

- M3 functional implementation: passed as the working product baseline.
- Repository regression, backend, frontend, PostgreSQL, dependency, and security gates: passed.
- Final M3 acceptance: **conditional / incomplete** with `18 pass / 18 partial / 4 missing / 0 fail`.
- PERF02 server result cache: remains partial and is deferred to M4-R3; it is not silently waived.
- M3 must not be recorded as fully accepted on the basis of this document.
