# Repository Guidelines

## Project Structure & Module Organization

This repository is being built as a modern BI reporting and bulletin editing system. Backend code lives in `backend/src/bi_system`, with shared application settings under `backend/src/bi_system/core`. Backend tests live in `backend/tests`, grouped by test type such as `backend/tests/unit`. Data files used for local validation are kept under `data`; legacy preserved samples are under `data/legacy` and should not be committed unless explicitly documented. The planned frontend will live in `frontend` using React, TypeScript, Vite, and Ant Design.

## Build, Test, and Development Commands

Use `uv` for all Python dependency and environment management.

- `uv sync --all-groups`: install runtime and development dependencies.
- `uv run pytest`: run the backend test suite.
- `uv run ruff check backend`: lint backend code.
- `uv run basedpyright backend/src backend/tests`: run strict Python type checks.
- `uv run uvicorn bi_system.main:app --reload`: run the FastAPI app locally once `main.py` exists.

Frontend commands will be added after the Vite project is scaffolded.

## Coding Style & Naming Conventions

Python targets 3.13, uses 4-space indentation, SQLAlchemy 2 style, Pydantic Settings, Ruff, and BasedPyright strict mode. Prefer explicit types for public functions and tests. Use `snake_case` for Python modules, functions, variables, and database fields. Use `PascalCase` for classes and Pydantic models. TypeScript code should use 2-space indentation, `PascalCase` components, and `camelCase` variables.

## Testing Guidelines

Write focused tests next to the behavior they cover. Use `test_*.py` files and `test_*` functions. Common database behavior must remain compatible with both SQLite and PostgreSQL. Run `uv run pytest`, `uv run ruff check backend`, and `uv run basedpyright backend/src backend/tests` before committing backend changes.

## Commit & Pull Request Guidelines

Follow Conventional Commit prefixes already used in history, such as `chore:`, `style:`, `docs:`, `build:`, `feat:`, and `fix:`. Keep commits scoped and independently reviewable. Pull requests should include a short purpose statement, key changes, verification commands, linked issues when available, and screenshots or recordings for UI changes.

## Security & Configuration Tips

Do not commit `.env`, downloaded datasets, credentials, cookies, or production exports. External model calls must use desensitized data. Keep local SQLite data lightweight and treat PostgreSQL as the target for test and production compatibility.
