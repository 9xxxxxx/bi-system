# ADR 0002: SQLite and PostgreSQL Portability

- Status: Accepted
- Date: 2026-07-15

## Context

SQLite supports lightweight local, demo, and single-user operation. PostgreSQL is the integration and production target. Both databases must share domain models, migration history, and core behavior so production migration is an operational change rather than a rewrite.

## Decision

- Define shared models with SQLAlchemy 2 and use Alembic for every schema change.
- Prefer portable `Uuid`, `String`, `Integer`, `Numeric`, `Date`, `DateTime`, `Boolean`, and generic `JSON` types. Use Python `Decimal` for numeric values and normalize timestamps to UTC at application boundaries.
- Use application-generated UUIDs where identifiers must survive export or database migration.
- Do not use unwrapped JSONB, arrays, full-text search, database enums, dialect SQL, stored procedures, or backend-specific defaults in shared modules.
- Keep any justified database-specific optimization behind an adapter with a portable fallback and tests for both paths.
- Enable `PRAGMA foreign_keys=ON` for every SQLite connection. Do not rely on SQLite's permissive typing; validate data in Pydantic and enforce constraints in migrations.
- Use PostgreSQL for multi-user and production workloads. SQLite does not define production concurrency or performance expectations.

## Migration Rules

Each revision must have working `upgrade` and `downgrade` paths. Before merge, run the complete migration chain against SQLite and PostgreSQL:

```powershell
uv run alembic -c backend/alembic.ini upgrade head
uv run alembic -c backend/alembic.ini downgrade base
uv run python scripts/run_postgres_tests.py
```

Destructive or data-transforming migrations require a tested backup/restore path and representative copied data. Schema changes may not edit an already-shipped revision.

## Consequences

Some PostgreSQL-specific performance features remain available only through explicit adapters. This constraint trades a small amount of peak optimization for predictable Windows-to-Linux deployment and test-to-production migration. The M0 baseline has been verified through upgrade, downgrade, and re-upgrade on SQLite and PostgreSQL 18.
