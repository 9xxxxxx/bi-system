# Local Data

This directory contains local runtime and migration data. Database files,
uploads, exports, and generated artifacts are intentionally excluded from Git.

`dashboard.db` is the preserved SQLite database from the original prototype.
Do not modify or remove it during the M0 rebuild. Use the verified copy under
`data/legacy/` for migration experiments and regression checks.

