# M0 Verification Record

- Date: 2026-07-15
- Platform: Windows, PowerShell
- Python: 3.13.11
- uv: 0.9.12
- Node.js: 24.11.1
- npm: 11.18.0
- PostgreSQL: 18
- Browser automation: Playwright CLI 0.1.13, Chromium

## Preserved Data

`data/dashboard.db` and `data/legacy/dashboard.db` are both 77,824 bytes and have SHA256 `53E578FE47CE432B81EA2DA12B1EA1FD4F6B1041989280A8B05DF4199280AF56`. Both copies returned these row counts:

| Table | Rows |
| --- | ---: |
| `dim_city` | 9 |
| `dz_data` | 50 |
| `metric_def` | 21 |
| `rk_data` | 140 |

`git ls-files data` lists only `data/README.md` and `data/legacy/README.md`; no database is tracked.

## Backend And Database

The following commands completed successfully from the repository root:

```powershell
uv sync --locked --all-groups
uv run ruff check backend scripts
uv run ruff format --check backend scripts
uv run basedpyright backend/src backend/tests scripts
uv run pytest backend/tests -q --cov=bi_system
uv run python scripts/run_postgres_tests.py
```

The default SQLite run passed 17 tests, skipped the PostgreSQL-only migration-state test as designed, and reported 92% line coverage. The isolated PostgreSQL 18 run passed 4 integration tests and completed upgrade, downgrade to base, and re-upgrade to head. Ruff and BasedPyright reported no issues.

## Frontend

The locked clean install and checks passed:

```powershell
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run build
```

Oxlint, Prettier, TypeScript, and 2 Vitest component tests passed. Vite produced a working production build. The initial Ant Design bundle is 679.02 kB (220.47 kB gzip) and triggers Vite's 500 kB warning; route-level splitting is required before feature modules expand, as recorded in ADR 0001.

## Browser Smoke Test

FastAPI ran on `127.0.0.1:8001` and Vite on `127.0.0.1:5173` for an isolated smoke test. The preferred in-app browser runtime could not initialize because of a host runtime property conflict, so the same local-only checks were completed with Playwright CLI.

- [Desktop success](screenshots/success-desktop.png): 1440x900, API `ready`, database `ok`.
- [Desktop API failure](screenshots/error-desktop.png): the API process was stopped; the page showed a clear recovery action without layout shift.
- [Mobile success](screenshots/success-mobile.png): 390x844, no overlap and no horizontal overflow.
- [Mobile navigation](screenshots/mobile-menu-open.png): the fixed overlay menu opened without resizing or overflowing the page.

The API was restarted after the failure check. Browser console errors in the failure state were the expected refused health requests; the success state had no application errors.

## Git And Residual Notes

`git diff --check` and all pre-commit hooks passed. Commits use Conventional Commits and remain scoped by M0 task. One third-party warning remains: FastAPI's current `TestClient` path reports Starlette's `httpx` deprecation notice. It does not affect runtime or test results and should be revisited when the compatible dependency release is available.
