# ADR 0003: Ingestion Jobs and File Storage

- Status: Accepted
- Date: 2026-07-15

## Context

M1 must import CSV and modern Excel files up to 100 MB or about one million rows without loading the complete file into application memory. Imports need visible progress, cancellation, retries, preserved source files, and identical core behavior on SQLite and PostgreSQL. The current team scale does not justify operating Redis and a separate queue framework.

## Decision

- Store immutable source blobs through a `FileStorage` interface. M1 uses a local content-addressed implementation under the ignored `data/uploads/sha256/` tree; object storage can be added later without changing domain services.
- Calculate SHA256 while streaming each upload to a temporary file. Move it atomically to its final key only after size, extension, and basic content checks pass. Repeated content reuses the blob but creates or reuses workspace-scoped source metadata without exposing another workspace's filenames.
- Persist import work and progress in the application database. Workers claim pending batches with a time-limited lease, increment attempts, and resume only from committed chunk boundaries.
- Run one import worker in SQLite mode. PostgreSQL may run multiple workers using a dialect adapter for row locking. Queue implementation details must remain outside domain services.
- Parse CSV incrementally with Python streaming I/O. Parse `.xlsx` worksheets in read-only mode. Legacy `.xls`, macro-enabled files, encrypted workbooks, and formula execution are not supported in M1; the API returns a clear conversion action.
- Keep full error reports as generated file assets and only a bounded issue sample in relational tables. Raw sensitive values are truncated and must not enter logs.

## State Model

An import batch moves through `pending`, `processing`, `succeeded`, `partially_succeeded`, `failed`, or `cancelled`. A retry may move `failed` back to `pending`; cancellation is accepted only before the irreversible commit phase. State transitions are enforced in one domain service and recorded with timestamps, attempt count, progress, and a public error code.

## Consequences

This design keeps local operation lightweight and makes restart recovery possible without a new service. SQLite remains intentionally single-worker and is not a concurrency benchmark. PostgreSQL-specific locking and bulk-write optimizations require portable fallbacks and dual-database tests. A future Redis queue must preserve the same batch contract and may not become the source of truth for status.

## Dependency Evidence

Checked on 2026-07-15: openpyxl 3.1.5 is MIT licensed and python-multipart 0.0.32 is Apache-2.0 licensed. Six reader tests verify UTF-8/GB18030 CSV, Chinese XLSX values, worksheet selection, dates, formula text without execution, and controlled corrupt-workbook errors. Neither dependency introduces a second data-frame or task-queue runtime.
