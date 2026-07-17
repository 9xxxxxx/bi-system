# Repository Guidelines

## Agent Operating Rules

Always reply to the user in Chinese unless they explicitly request another language. Use `uv` as the only Python dependency and command entry point. Keep Git history clean with focused Conventional Commits. Before editing, run `git status --short` and treat unrelated changes as user-owned.

## Current Development Baseline

M0 engineering foundation, M1 data ingestion, and M2 data modeling are accepted. M2 evidence is recorded in `docs/verification/m2-verification.md`; the machine-transfer handoff is in `docs/plans/2026-07-17-development-handoff.md`. M3-M6 are planned in `docs/plans/2026-07-17-m3-m6-multi-agent-development.md` but production code has not started.

Do not jump straight into M3 feature code. First complete M3-R0: freeze dashboard, layout, chart, filter, template, and query contracts; run charting/layout spikes; record license, bundle, screenshot, and browser evidence.

## Project Structure & Module Organization

Backend code lives in `backend/src/bi_system/`; tests are split between `backend/tests/unit/` and `backend/tests/integration/`. Alembic migrations live in `backend/migrations/`. The React app is under `frontend/src/`, organized by `app/`, feature folders, and shared infrastructure. Architecture decisions and evaluations belong in `docs/architecture/`; plans and handoff notes belong in `docs/plans/`; verification evidence belongs in `docs/verification/`. Keep runtime data in ignored `data/`.

## Build, Test, and Development Commands

Install dependencies with `uv sync --locked --all-groups` and `npm --prefix frontend ci`. Apply migrations with `uv run alembic -c backend/alembic.ini upgrade head`. Start local services with `uv run uvicorn bi_system.main:app --app-dir backend/src --reload` and `npm --prefix frontend run dev`.

Before committing relevant code, run `uv run pytest backend/tests -q --cov=bi_system`, `uv run ruff check backend scripts`, `uv run ruff format --check backend scripts`, `uv run basedpyright backend/src backend/tests scripts`, `npm --prefix frontend run check`, and `npm --prefix frontend run build`. For migrations or database behavior, also run `uv run python scripts/run_postgres_tests.py`.

## Coding Style & Naming Conventions

Python uses four spaces, explicit type annotations, Ruff formatting, and `snake_case`; classes use `PascalCase`. TypeScript uses two spaces, Prettier, `PascalCase` components, and `camelCase` functions/hooks. Prefer existing module patterns. Do not add database-specific SQL outside explicit adapters.

## Testing Guidelines

Name Python tests `test_*.py` and frontend tests `*.test.tsx`. UI work must cover loading, success, empty, and error states. Shared database behavior must pass on SQLite and PostgreSQL. Visible UI changes need desktop and 390 px mobile evidence; chart/editor/export work needs browser rendering checks.

## Commit, PR, and Security Rules

Use Conventional Commits such as `feat(api): add dataset preview` or `docs: record M3 verification evidence`. Keep commits independently reviewable; separate migrations, backend contracts, frontend integration, dependency changes, and verification docs.

Never commit `.env`, `frontend/.env.local`, database files, uploads, exports, cookies, tokens, production credentials, or downloaded business data. External model calls may receive only desensitized, policy-approved data. Preserve local `data/` samples during cleanup unless the user explicitly says otherwise.
