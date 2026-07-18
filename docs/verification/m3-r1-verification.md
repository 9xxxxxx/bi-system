# M3-R1 Verification

- Date: 2026-07-19
- Scope: dashboard domain foundation and workbench shell
- Baseline: M3-R0 Accepted (`36aae72`)

## Delivered Boundaries

- Portable dashboard, version, page, component, layout, template, and resource-grant schema.
- Workspace-scoped dashboard lifecycle with immutable aggregate versions, optimistic revision checks, recycle-bin delete/restore, and permission composition.
- Dashboard and template APIs for R1 creation, listing, reading, aggregate saving, permission replacement, deletion, and restoration.
- Lazy dashboard list/create/editor routes with loading, empty, error, forbidden, desktop editor, and mobile read-only states.
- Production dependencies are frozen at ECharts 6.1.0 and React Grid Layout 2.2.3. R1 does not execute chart queries or include either runtime in the built route chunks.

## Backend Evidence

| Gate | Result |
|---|---|
| `uv run pytest backend/tests -q --cov=bi_system` | 246 passed, 6 PostgreSQL-environment skips, 90% total coverage |
| Dashboard focused unit/integration set | 22 passed |
| `uv run ruff check backend scripts` | Passed |
| `uv run ruff format --check backend scripts` | 142 files formatted |
| `uv run basedpyright backend/src backend/tests scripts` | 0 errors, 0 warnings |
| SQLite Alembic `upgrade head -> downgrade 0004 -> upgrade head` | Passed |
| PostgreSQL integration runner | 74 passed; `upgrade -> downgrade base -> upgrade head` passed |
| Migration versus ORM metadata | Eight dashboard tables, `DIFF_COUNT 0` |

The six local skips require a configured PostgreSQL URL or PostgreSQL-only timeout environment. They were exercised successfully by the isolated PostgreSQL runner during M3-R1-C1.

## Frontend Evidence

Node 24.18.0 and npm 11.18.0 were invoked through the isolated repository runner.

| Gate | Result |
|---|---|
| `npm --prefix frontend run check -- --maxWorkers=1 --no-file-parallelism` | 14 files, 51 tests; lint, format, and typecheck passed |
| Dashboard feature suite | 4 files, 16 tests passed |
| `npm --prefix frontend run build` | Passed |
| Production build route boundary | No ECharts or React Grid Layout runtime chunk in R1 |

Vitest emits the existing jsdom pseudo-element `getComputedStyle` notice without a test failure.

## Chrome Workflow

Playwright CLI used the explicit Chrome channel at 1440 x 900 and 390 x 844 against a migrated SQLite database and the real FastAPI/Vite services.

1. Restored an authenticated browser state and opened `/dashboards` with zero console errors and warnings.
2. Created a blank dashboard: `POST /api/v1/dashboards` returned 201.
3. Added a KPI placeholder, changed its title, and saved: `POST /api/v1/dashboards/{id}/versions` returned 201 and the UI reported `v2`.
4. Reloaded the editor: `GET /api/v1/dashboards/{id}` returned 200 and the component title persisted.
5. Desktop document width equaled the 1440 px viewport with one component and no horizontal overflow.
6. At 390 px, the independent mobile layout rendered the saved component with zero overlap or horizontal overflow. Palette, inspector, and save controls were absent from the DOM and the read-only notice was visible.
7. Final browser console: 0 errors, 0 warnings.

## Screenshots

| Artifact | Dimensions | SHA-256 |
|---|---:|---|
| `m3-r1-dashboard-desktop-chrome.png` | 1440 x 979 | `53c14159f75caee0a0e8f9d8d479f41971fa9fdb26b141f23aa9b91f18a3b546` |
| `m3-r1-dashboard-mobile-chrome.png` | 390 x 900 | `783a9368107b953ce964ba75fecf482b66031e81f5679dfed5663b60c07c8153` |

## Scope Confirmation

- No M3-R2 chart query execution, field-slot configuration, metric sorting, time grain, or scoped-filter execution was implemented.
- Opaque global/page filter configuration is preserved during aggregate round trips so later R2 work cannot be erased by an R1 save.
- User-owned `.claude/` and `MIGRATION_MANIFEST.txt` remained untouched and uncommitted.
