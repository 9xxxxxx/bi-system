# Repository Guidelines

## Project Structure & Module Organization

The FastAPI application lives in `backend/src/bi_system/`; keep API routes, core configuration, and database infrastructure in their existing focused packages. Backend tests are split between `backend/tests/unit/` and `backend/tests/integration/`. Alembic migrations live in `backend/migrations/`. The React application is under `frontend/src/`, organized into `app/`, feature folders, and shared infrastructure. Record decisions in `docs/architecture/`; keep local runtime data in the ignored `data/` directory.

## Build, Test, and Development Commands

Use `uv` as the only Python environment and dependency entry point. Run `uv sync --locked --all-groups`, then apply migrations with `uv run alembic -c backend/alembic.ini upgrade head`. Start the API with `uv run uvicorn bi_system.main:app --app-dir backend/src --reload`. Install frontend dependencies with `npm --prefix frontend ci` and start Vite with `npm --prefix frontend run dev`. Run `npm --prefix frontend run check` before committing; keep `package-lock.json` synchronized with every package change.

## Coding Style & Naming Conventions

Python uses four spaces, explicit type annotations, Ruff formatting, and `snake_case`; classes use `PascalCase`. TypeScript uses two spaces, Prettier, `PascalCase` components, and `camelCase` functions and hooks. Keep modules small and feature-focused. Do not add database-specific SQL outside an explicit adapter.

## Testing Guidelines

Name Python tests `test_*.py` and frontend tests `*.test.tsx`. Cover loading, success, empty, and error states for UI work. Run `uv run pytest backend/tests -q`, `uv run ruff check backend scripts`, and `uv run basedpyright backend/src backend/tests scripts`. Every migration and shared database behavior must pass on SQLite and PostgreSQL; use `uv run python scripts/run_postgres_tests.py`.

## Commit & Pull Request Guidelines

Use Conventional Commits, for example `feat(api): add dataset preview` or `fix(web): preserve dashboard filters`. Keep commits focused and independently reviewable. Pull requests must describe scope, database impact, verification commands, linked issues when available, and screenshots or recordings for visible UI changes.

## Security & Configuration

Never commit `.env`, database files, uploads, exports, cookies, tokens, or production credentials. Update `.env.example` when configuration changes. Preserve the existing `data/dashboard.db` samples during cleanup. External model calls may receive only desensitized, policy-approved data.
