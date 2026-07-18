# ADR 0004: Dashboard Domain And Query Contracts

- Status: Accepted
- Date: 2026-07-18

## Context

M2 provides governed datasets, versioned metrics, calculated fields, row-level policies and a timeout-limited query path. M3 needs dashboard editing, core charts, scoped filters, templates and separate desktop/mobile layouts without creating a second query language or bypassing M2 evidence and permissions.

Charting and layout libraries are not production dependencies yet. M3-R0 must validate their licenses, React/browser compatibility, bundle cost, rendering, export and mobile behavior before selection.

## Decision

- Model dashboards and templates as stable workspace-scoped resources with immutable versions.
- Reuse the existing internal `deleted` plus `deleted_at` lifecycle representation for recycle-bin behavior.
- Combine coarse role permissions with dashboard-specific user/role/workspace resource grants; always apply underlying dataset permissions and RLS separately.
- Persist pages, components and desktop/mobile layout profiles inside a dashboard version.
- Persist versioned, strongly typed component configuration that references only resource, field and metric UUIDs.
- Compile chart query configuration into the M2 governed dataset query contract. Do not accept physical identifiers, SQL, arbitrary functions or executable code.
- Persist client-visible logical `slot_key` values separately from server-generated M2 query aliases. Sort targets are discriminated resource UUIDs, never aliases.
- Keep global, page and component filters as separate existing M2 `FilterExpression` values, compile each inside the governed M2 path, and SQLAlchemy-AND them with mandatory predicates and RLS. The user scopes share a 50-predicate budget and are never flattened into one AST.
- Resolve relative dates server-side from a configured IANA workspace timezone into portable UTC boundaries, and return the resolved interval as query evidence.
- Preserve dataset version, metric versions, source batches, elapsed time and truncation in every chart query response.
- Persist new dashboard versions as atomically validated aggregates; use a strong preview configuration only for authorized unsaved editor queries.
- Keep the layout contract library-neutral. Desktop editing may edit both profiles; mobile clients remain read-only.
- Use ECharts 6.1.0 behind a dynamic chart boundary; it must not enter the initial application closure.
- Use React Grid Layout 2.2.3 for desktop editing with a 12-column, 44 px-row, non-overlapping vertically compacted grid. Keep GridStack spike-only.
- Keep M4 interactions and M5 formal export/background jobs outside M3.

## Accepted M3-R0 Evidence

- Backend compilation: 29 focused tests and 45 M2 joint regressions, including UUID boundaries, stable gap codes and complete-series enforcement.
- Fixture: deterministic `m3-star-v2` DateTime/timezone/DST evidence, while A1's frozen V1 chart golden remains reproducible.
- Frontend: Node 24.18/npm 11.18, 15 spike tests, Chrome 149 and Edge 150 desktop/mobile/1-20-50 stress evidence, nonblank Canvas, 2x PNG, drag/resize and zero console errors/warnings.
- Dependencies: 19 compatible production package licenses and a same-config raw/gzip/brotli baseline. ECharts is absent from the initial manifest closure; the initial candidate gzip delta is 24,291 bytes.
- Evidence paths: `docs/architecture/evaluations/m3-chart-query-compiler-spike.md`, `m3-chart-layout-spike.md`, `m3-acceptance-matrix.md` and `docs/verification/m3-r0-*`.

## Frozen Query Gap Decisions

- M3-R2 adds a discriminated UUID-only field/metric sort target; metric sorting reuses the server-resolved metric expression.
- M3-R2 adds governed day/week/month/quarter/year time grains behind SQLite/PostgreSQL adapters.
- Stacked charts may use multiple measures or one bounded series dimension. Series-dimension Top N is rejected in M3 to prevent partial groups.
- Series queries require server-resolved primary and series cardinalities whose product fits the effective row limit. Preflight overflow and any runtime truncated series result fail closed instead of rendering an incomplete group.
- M3 Top N does not calculate an `Others` bucket; truncation is explicit evidence.
- NULL sorts last with a deterministic dimension tie-breaker. Decimal and temporal values use canonical typed serialization.

## Consequences

- M3-R1 may begin domain/contract implementation, but dependencies, migrations, backend integration and frontend integration remain separate reviewable commits.
- Production frontend integration must preserve the proven dynamic ECharts boundary and rerun bundle/license evidence against the real entry.
- M3-R2 still owns metric sorting, portable time grains, scoped-filter execution and V2 DateTime/DST SQLite/PostgreSQL parity.
- M3-R3 still owns keyboard move/resize controls, full browser workflows and production performance acceptance.
