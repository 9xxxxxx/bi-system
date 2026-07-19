# M3-R2 Verification

- Date: 2026-07-19
- Scope: governed dashboard queries, scoped filters, core renderers, controlled content, performance, and browser acceptance
- Accepted baseline: M3-R1 (`5a45b46`)
- Implementation and acceptance commits: `bf8e9f9` through `0cfa963`

## Delivered Boundaries

- Persisted and editor-preview chart queries run through the governed M2 compiler with immutable dashboard-version context.
- Global, page, and component filters remain distinct and combine after RLS with portable absolute/relative date resolution.
- KPI, trend, target, detail, ranking, bar, horizontal bar, stacked bar, line, area, pie, and donut renderers share normalized data and source evidence.
- Dataset, field, and metric catalogs replace raw UUID entry. Configuration covers field roles, aggregation, sorting, Top N, series, units, legend, labels, tooltip, and theme.
- ECharts remains dynamically loaded. Lightweight results do not load the chart runtime.
- Rich text is block-based and non-executable. Dashboard images use governed PNG/JPEG/WebP/GIF assets; SVG is rejected.

## Backend Gates

| Gate | Result |
|---|---|
| `uv run pytest backend/tests -q --cov=bi_system` | 323 passed, 6 environment skips; 91% coverage |
| PostgreSQL 18 integration runner | 82 passed |
| PostgreSQL migration `head -> base -> head` | Passed |
| `uv run ruff check backend scripts` | Passed |
| `uv run ruff format --check backend scripts` | 160 files formatted |
| `uv run basedpyright backend/src backend/tests scripts` | 0 errors, 0 warnings |
| `m3-star-v2` fixture validation | 11 passed |
| SQLite/PostgreSQL chart-query portability | Passed, including time grains, filters, RLS, stable Top N, Decimal, date, and datetime values |

The PostgreSQL run found and closed a real portability defect: repeated bound `date_trunc` grains caused grouping errors. The fixed compiler safely inlines only the governed grain enum (`9a3f1b3`).

## Frontend Gates

Node 24.18.0 and npm 11.18.0 were invoked through the isolated repository runner.

| Gate | Result |
|---|---|
| Complete `check` with single-worker Vitest flags | Passed in 101.273 s |
| Vitest | 22 files, 80 tests passed in 92.66 s |
| Production build | Passed in 5.336 s; 3,753 modules, Vite build 474 ms |
| Stable table-row-key focused suite | 1 file, 6 tests passed |
| `git diff --check` | Passed |

Chrome initially exposed an Ant Design 6 console diagnostic because a table row-key callback used the deprecated index parameter. Commit `0cfa963` now derives stable typed fingerprints and unique duplicate occurrences; the final desktop and mobile sessions contain zero console errors and warnings.

The only non-failing test diagnostic is jsdom's unsupported pseudo-element `getComputedStyle` message (16 occurrences). Vite also reports the expected over-500-kB warning for the deferred ECharts chunk.

## Performance

The deterministic performance scale contains 100,000 fact rows and executes three governed chart queries per sample.

| Database | Concurrency / samples | P50 | P95 | Throughput | Errors / timeouts |
|---|---:|---:|---:|---:|---:|
| SQLite | 1 / 30 | 1,035.975 ms | 1,056.359 ms | 0.964 rps | 0 / 0 |
| PostgreSQL 18 | 20 / 60 | 2,076.669 ms | 3,551.428 ms | 8.471 rps | 0 / 0 |

Both P95 values pass the 5,000 ms regular-query target. The intentional Top-N query reports truncation in every sample. Structured results are in `m3-r2-performance.json`.

This is the R2 exit baseline, not the complete M3 performance certification. The current benchmark performs one warmup and records aggregate results for a three-query mix. M3-R3 must rerun five warmups, retain raw samples and environment inventory, cover the full principal/query mix, and add production page plus cached-dashboard timings required by the acceptance matrix.

## Bundle And Licenses

The production manifest was regenerated under Node 24.18.0, npm 11.18.0, and Vite 8.1.4.

| Boundary | Raw | gzip level 9 | brotli level 11 |
|---|---:|---:|---:|
| Initial asset closure | 784,299 B | 259,684 B | 225,210 B |
| Dashboard static asset closure | 1,244,643 B | 408,755 B | 355,149 B |
| Dynamic `EChartRenderer` | 556,244 B | 186,880 B | 157,906 B |

`EChartRenderer` is an `isDynamicEntry` and is absent from both the initial and dashboard static closures. Details and per-file sizes are in `m3-r2-bundle.json`.

The accepted frontend inventory remains 19 production packages across 0BSD, Apache-2.0, BSD-3-Clause, ISC, and MIT with zero review-required entries. Pillow 12.3.0 is `MIT-CMU`; image validation enforces 10 MB and 40 million total decoded pixels across animation frames.

## Chrome Workflow

Playwright CLI 0.1.17 used an explicit `--browser chrome` channel. The runtime was an Alembic-upgraded ignored SQLite database, real FastAPI/Vite services, and a real HttpOnly session.

1. Loaded a 14-component `m3-star-v2` dashboard containing all 12 query renderers, rich text, and image content.
2. Observed 12 StrictMode cancellation requests followed by 12 real `POST /api/v1/dashboard-chart-queries` responses with HTTP 200.
3. Confirmed requests include `dashboard_version_id`, editor `preview_component`, and independent global/page/component runtime filters.
4. Confirmed the representative KPI returns Decimal string `350.50`, dataset v1, one metric version, three source batches, and all resolved date scopes in `Asia/Hong_Kong`.
5. Changed the page filter to `R-SOUTH`; 12 re-queries returned 200 and the KPI changed to `100.00` without weakening global or component filters.
6. Verified the real Top-2 response displays truncation and warning evidence.
7. Replayed loading/cancel, empty, 403, 504, 500/retry, and truncation for one target component. These mocks prove frontend presentation only; backend contracts remain covered by real tests.
8. Uploaded a real 160 x 96 PNG. The API returned 201 and matching SHA-256, the content route returned 200, and the image decoded at 160 x 96 with the configured alt text.
9. Confirmed literal `<script>` rich-text content creates no executable nested script element.

Desktop at 1440 x 900 has exact horizontal fit, 14 non-overlapping components, seven nontransparent/nonuniform Canvas surfaces, 12 accessible tables, and 12 source-evidence controls. Mobile at 390 x 844 has exact horizontal fit, 14 non-overlapping components, seven varied Canvas surfaces, and no component panel, property panel, or save action. Its 378 px filter drawer remains inside the viewport and exposes all three scopes.

Full structured network, Canvas, layout, content, state, console, and browser facts are in `m3-r2-browser-evidence.json`.

## Screenshots

| Artifact | Dimensions | SHA-256 |
|---|---:|---|
| `m3-r2-dashboard-desktop-chrome.png` | 1440 x 1993 | `4381ce75aca5071e9cdd6d1b96229043bba1181d5236abfee8f1229e74d83c1a` |
| `m3-r2-dashboard-mobile-chrome.png` | 390 x 5044 | `dc20fffb0507e2091d50e70bbc96dcda3ca65317a979b77031c713224c444af2` |
| `m3-r2-dashboard-mobile-filter-chrome.png` | 390 x 844 | `1605992686964b621633474cc8931837040ed19c44e50194b5de92b8e1a13e1e` |

## Scope Confirmation

- M3-R2 is accepted. M3-R3 drag/resize, template publication, retention cleanup, and final M3 acceptance remain separate work.
- Edge complete-flow, DPR 2/export, trace, full accessibility artifact, five-warmup raw performance, page P95, and cached-dashboard P95 remain explicit M3-R3 gates. R0's Chrome/Edge spike evidence is not misrepresented as an R2 production-flow rerun.
- Runtime databases, sessions, uploads, benchmark raw output, and credentials remain ignored and uncommitted.
- User-owned `.claude/` and `MIGRATION_MANIFEST.txt` remain untouched and uncommitted.
