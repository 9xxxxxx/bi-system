# M3 Phase 25 Cross-Machine Handoff

- Recorded: 2026-07-20
- Current phase: Phase 25 — M3-R3 integration, verification, and conditional M3 acceptance
- Source baseline: `7144934 feat(verification): add M3 permission and UI evidence capture`
- Acceptance status: **conditional / incomplete**; M4 research is permitted, but M4 production contracts and code remain blocked.

## Verified Checkpoint

Commit `7144934` contains two independently verified evidence producers and their focused tests:

- `scripts/export_m3_permission_evidence.py` exports structured P01--P05 permission/RLS evidence.
- `scripts/capture_m3_ui_acceptance.py` captures Chrome-first UI closure evidence and fails closed when result columns or loading/cancel state cannot be proven.

The focused verification command completed with `13 passed`:

```powershell
uv run pytest backend/tests/unit/test_export_m3_permission_evidence.py backend/tests/unit/test_capture_m3_ui_acceptance.py -q
uv run ruff check scripts/export_m3_permission_evidence.py scripts/capture_m3_ui_acceptance.py backend/tests/unit/test_export_m3_permission_evidence.py backend/tests/unit/test_capture_m3_ui_acceptance.py
uv run ruff format --check scripts/export_m3_permission_evidence.py scripts/capture_m3_ui_acceptance.py backend/tests/unit/test_export_m3_permission_evidence.py backend/tests/unit/test_capture_m3_ui_acceptance.py
uv run basedpyright scripts/export_m3_permission_evidence.py scripts/capture_m3_ui_acceptance.py backend/tests/unit/test_export_m3_permission_evidence.py backend/tests/unit/test_capture_m3_ui_acceptance.py
```

## Milestone Baseline

The authoritative M3 collector remains `18 pass / 18 partial / 4 missing / 0 fail`; all six
repository regression/quality gates pass. The full status and immutable evidence closure are in
[M3 verification](m3-verification.md).

`M3-PERF02` is still partial: observed dashboard P95 is 1,029 ms, but the server result cache
required by the frozen matrix is not implemented. Its cache keys, invalidation, and PostgreSQL
tuning belong to planned M4-R3; do not relabel this item as passed or implement an unplanned cache
in Phase 25.

## Resume From Here

The following work was deliberately left uncommitted because it is not yet independently verified:

- `scripts/export_m3_contract_db_evidence.py` and its focused test need the C02 injection-evidence
  rework before they can enter the collector.
- `scripts/collect_m3_acceptance_evidence.py` and
  `backend/tests/unit/test_m3_acceptance_evidence.py` contain in-progress collector integration;
  finish the expanded static typing and validate the structured DB, permission, and UI inputs before
  producing a new authoritative index.

Current UI closure evidence stays fail-closed: UI05 fixed dimensions are covered, while UI04 needs
stable response mapping metadata and UI08 needs a reliably observable loading/cancel state. Preserve
these as non-pass items unless the structured artifact proves them.

## Local-Only Files

Do not stage or alter `.claude/` or `MIGRATION_MANIFEST.txt`; they are user-owned untracked files.
The local `task_plan.md`, `progress.md`, and `findings.md` are excluded by `.git/info/exclude`; this
tracked handoff is the portable continuation record for a new machine.
