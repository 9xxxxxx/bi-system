# Development Handoff: M2 Accepted Baseline

## Current Repository State

Date: 2026-07-17

Remote repository: `git@github.com:9xxxxxx/bi-system.git`

Primary agent instructions: `AGENTS.md`

Current milestone status:

- M0 engineering foundation: accepted.
- M1 data ingestion: accepted.
- M2 data modeling: accepted and recorded in `docs/verification/m2-verification.md`.
- M3-M6: planned but not started as production code.

The current M2 code baseline ends at commit:

```text
c02061e docs: record M2 verification evidence
```

Handoff and forward-plan documents are expected to live after that code baseline on `origin/main`.

Recent M2 closure commits:

```text
4d81b1f test(modeling): strengthen portability verification
9440a4f perf(modeling): add PostgreSQL query benchmark
c02061e docs: record M2 verification evidence
```

## Completed Capabilities

The project currently provides a FastAPI backend, React + Ant Design frontend, local authentication, data ingestion, semantic modeling, datasets, governed query execution, calculated fields, public metrics, row-level policies, and same-origin API proxying.

M2 query execution now verifies SQLite/PostgreSQL behavior for joins, Decimal, date, Boolean, NULL, ordering, RLS before aggregation, query timeout, and migration round trips. PostgreSQL 18 benchmark evidence covers 100,000 rows and 20 concurrent requests with no benchmark errors.

## Verification Baseline

Latest completed gate:

```powershell
uv run pytest backend/tests -q --cov=bi_system
uv run python scripts/run_postgres_tests.py
uv run ruff check backend scripts
uv run ruff format --check backend scripts
uv run basedpyright backend/src backend/tests scripts
npm --prefix frontend run check
npm --prefix frontend run build
uv run pre-commit run --all-files
```

Recorded results:

- Backend: 225 passed, 6 skipped, 91% coverage.
- PostgreSQL integration: 70 passed, with Alembic upgrade, downgrade to base, and re-upgrade.
- Frontend: 34 passed; production build passed.
- M2 PostgreSQL benchmark: 100,000 rows, 20 concurrency, 20 completed, 0 errors, P50 5,091.655 ms, P95 6,949.637 ms.

## New Machine Setup

On the new machine:

```powershell
git clone git@github.com:9xxxxxx/bi-system.git
cd bi-system
uv sync --locked --all-groups
npm --prefix frontend ci
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env.local
uv run alembic -c backend/alembic.ini upgrade head
```

Then read these files in order before starting implementation:

1. `AGENTS.md`
2. `docs/plans/2026-07-17-development-handoff.md`
3. `docs/verification/m2-verification.md`
4. `docs/plans/2026-07-17-m3-m6-multi-agent-development.md`
5. `docs/architecture/evaluations/frontend-components.md`

Start local development:

```powershell
uv run uvicorn bi_system.main:app --app-dir backend/src --reload
npm --prefix frontend run dev
```

Create an initial admin after migration:

```powershell
uv run python scripts/create_initial_admin.py --username admin --display-name "System Administrator"
```

## Local Data and Secrets

Git intentionally does not contain `.env`, `frontend/.env.local`, SQLite databases, uploaded files, exports, cookies, tokens, or production credentials.

If existing local samples are needed on the new machine, copy `data/` separately by a trusted channel. Do not commit database files or downloaded business data.

## Next Development Step

Do not start M3 production implementation directly. First complete M3-R0:

- Freeze dashboard, page, component, layout, template, filter, and query contracts.
- Run charting/layout spikes before adding production dependencies.
- Record library selection, licenses, bundle impact, screenshots, and browser evidence.
- Create a dedicated M3 architecture plan or ADR before adding migrations or frontend routes.

The broader M3-M6 execution plan is in `docs/plans/2026-07-17-m3-m6-multi-agent-development.md`.

Recommended first commit on the new machine:

```text
docs: define M3 dashboard architecture
```

That commit should freeze the dashboard domain contract, chart query contract, layout model, filter merge rules, candidate chart/layout libraries, and M3 verification matrix before adding migrations or feature routes.
