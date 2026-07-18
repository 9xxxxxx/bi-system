# M3 quality fixture

`m3-star-v2` is the current correctness and acceptance seed for M3 dashboards. It is
an intentionally small three-source star model: `fact_sales` left joins
`dim_product` and `dim_region`. The checked-in output includes exact golden
results, chart-case pointers, principals, typed schema, and SHA-256 manifest.
V1 remains under `fixture/v1/` so existing M3-R0 query-compiler evidence stays
reproducible. V2 adds a canonical UTC `occurred_at` fact timestamp plus
machine-readable workspace-day cases for `Asia/Hong_Kong` and the 2026 New York
DST spring-forward boundary.

`fixture/v2/datetime_cases.json` contains semantic inputs. The corresponding
UTC half-open boundaries and duration are pinned under
`golden_results.json::datetime_scenarios`. These generator checks prove that the
fixture and expectations are deterministic; they do not prove database behavior.
M3-R2 must load the V2 field and execute the same cases on SQLite and PostgreSQL,
then compare filtering, time-grain grouping, typed serialization, and returned
boundary evidence before claiming dual-database parity.

All commands run from the repository root:

```powershell
uv run python spikes/m3/quality/fixture_tool.py check
uv run python spikes/m3/quality/fixture_tool.py summary
uv run pytest spikes/m3/quality/tests -q
```

Regenerate only when intentionally publishing a new fixture version:

```powershell
uv run python spikes/m3/quality/fixture_tool.py generate
```

Create an ignored, deterministic 100,000-row V2 performance input:

```powershell
uv run python spikes/m3/quality/fixture_tool.py benchmark --rows 100000 --output .tmp/m3-star-benchmark-100000
```

Do not edit generated files by hand. Change the constants or algorithms in
`fixture_tool.py`, bump `FIXTURE_VERSION`, regenerate, and review manifest and
golden-result changes together.
