# Frontend Component Evaluation Gates

## Policy

Do not add a grid, chart, or editor to production dependencies until its milestone spike passes the gate below. Each spike must preserve runnable source, representative test data, exact commands, desktop/mobile browser screenshots, bundle output, and a conclusion ADR. A candidate fails on any blocker even when its weighted score passes.

Registry and lockfile metadata were checked on 2026-07-15. Current runtime packages React 19.2.7, React DOM 19.2.7, Ant Design 6.5.1, Ant Design Icons 6.3.2, TanStack Query 5.101.2, React Router 7.18.1, Zustand 5.0.14, i18next 26.3.6, and react-i18next 17.0.9 are MIT licensed. Frontend tooling is MIT except TypeScript 6.0.3 (Apache-2.0). `uv tree --depth 1` found one direct Python stack: FastAPI 0.139.0, SQLAlchemy 2.0.51, Alembic 1.18.5, Psycopg 3.3.4, Pydantic Settings 2.14.2, and Uvicorn 0.51.0, with no duplicate core framework. The direct-dependency licenses are acceptable for the current internal deployment; Psycopg's LGPL terms must remain unmodified and dynamically consumed.

## M1 Data Grid

Compare React Data Grid 7.0.0-beta.61 and Glide Data Grid 6.0.3. AG Grid Community 36.0.0 remains a reference candidate, but required spreadsheet-grade clipboard workflows must not depend on Enterprise-only modules. All three registry packages report MIT licensing.

| Criterion | Weight | Evidence |
| --- | ---: | --- |
| Multi-cell copy/paste | 20% | Excel round-trip, blanks, dates, and 1,000-cell paste |
| 100,000-row scrolling | 20% | P95 frame and interaction measurements on 20 columns |
| Editing and validation | 15% | Async errors, undo behavior, Chinese IME |
| Ant Design theming | 10% | Tokens, density, focus, dark/high-contrast proof |
| Keyboard operation | 10% | Selection, edit, copy/paste without a pointer |
| License | 10% | Production and redistribution review |
| Maintenance | 10% | Releases, issue response, React compatibility |
| Accessibility | 5% | Roles, names, focus, screen-reader smoke test |

The winner needs at least 80/100. Blockers are failed multi-cell copy/paste, data corruption, unusable Chinese IME, inaccessible core navigation, incompatible licensing, or failure to keep the 100,000-row fixture responsive in current Chrome and Edge. The beta status of React Data Grid must be addressed explicitly in the conclusion.

## M3 Charting

Validate Apache-2.0 ECharts 6.1.0 against required chart families, a 360 px mobile viewport, 2x PNG export clarity, drill/down and cross-filter event context, tree-shaken bundle size, theme integration, and an accessible table/text alternative. Core M3 chart types and event context are blockers; specialized maps may use a separately reviewed adapter.

## M5 Structured Editor

Validate MIT TipTap Core 3.27.4 for typed structured blocks, required and locked blocks, template variables, deterministic JSON serialization, autosave/version replay, Chinese IME, paste cleaning, and PDF/Word/long-PNG pagination. Loss of content, editable locked blocks, nondeterministic version restoration, or broken Chinese input are blockers.

## External References

Astryx and Google Labs `design.md` are design-process references only. They may inform spikes and [DESIGN.md](../../../DESIGN.md), but neither enters production or development dependencies without a separate ADR.
