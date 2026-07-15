# ADR 0001: Platform Stack

- Status: Accepted
- Date: 2026-07-15

## Context

The product needs a data-dense BI workspace and bulletin editor for about 20 concurrent users. It must run on Windows during development and move to Linux without business-code changes. M0 establishes a maintainable base without prematurely adding chart, grid, or editor libraries.

## Decision

- Build a React 19 single-page application with TypeScript, Vite, and Ant Design. React has the stronger fit for the shortlisted data-grid and structured-editor ecosystems; Vite supplies the development and production toolchain, not a second UI framework.
- Build a versioned FastAPI API as a modular monolith. Keep module boundaries explicit so background workers can be separated later, but do not accept distributed-system cost before scale requires it.
- Use TanStack Query for server state, Zustand only for cross-feature client state, and React Router for navigation. Do not mirror query data in Zustand.
- Use `uv` as the only Python environment and lock entry point. Commit `uv.lock` and verify it with `uv sync --locked --all-groups`.
- Use npm with `frontend/package-lock.json`; CI installs with `npm ci`. Any `package.json` change must include its lockfile change.
- Treat [DESIGN.md](../../../DESIGN.md) as the frontend design source of truth. The approaches in Google Labs `design.md` inform this workflow but are not a runtime dependency. Facebook Astryx is reference material only.

## Alternatives

Vue is capable but offers less alignment with the evaluated grid/editor candidates. Next.js adds server-rendering and server-component complexity without a current public-site requirement. Microservices would add deployment, tracing, and transaction overhead with no benefit at the expected scale.

## Verification Evidence

Verified on 2026-07-15 with Python 3.13.11, uv 0.9.12, Node 24.11.1, and npm 11.18.0. The locked environment contains FastAPI 0.139.0, SQLAlchemy 2.0.51, React 19.2.7, Vite 8.1.4, and Ant Design 6.5.1. `uv run pytest backend/tests -q --cov=bi_system`, strict type/lint checks, `npm --prefix frontend run check`, and the production build passed. The scope follows the [requirements specification](../../superpowers/specs/2026-07-14-bi-reporting-system-requirements.md).

## Consequences

Initial Ant Design bundling produces a size warning; feature routes must be split before BI modules expand. New foundational libraries require a documented spike and must not duplicate an existing state, routing, or component responsibility.
