from __future__ import annotations

import json
from time import perf_counter
from uuid import UUID

from spikes.m3.backend.chart_query_compiler import (
    ChartQueryCompiler,
    FieldMetadata,
    ResourceCatalog,
)

DATASET_ID = UUID("00000000-0000-0000-0000-000000000001")
CITY_ID = UUID("00000000-0000-0000-0000-000000000002")
AMOUNT_ID = UUID("00000000-0000-0000-0000-000000000003")


def main(iterations: int = 10_000) -> None:
    compiler = ChartQueryCompiler()
    catalog = ResourceCatalog(
        dataset_id=DATASET_ID,
        fields={
            CITY_ID: FieldMetadata(role="dimension", data_type="string"),
            AMOUNT_ID: FieldMetadata(role="measure", data_type="decimal"),
        },
        metric_version_ids=frozenset(),
    )
    config: dict[str, object] = {
        "chart_type": "bar",
        "dataset_id": DATASET_ID,
        "dimension_id": CITY_ID,
        "values": [{"kind": "field", "field_id": AMOUNT_ID, "aggregate": "sum"}],
        "top_n": 10,
        "filter": {
            "kind": "comparison",
            "field_id": CITY_ID,
            "operator": "ne",
            "value": "unknown",
        },
    }
    started = perf_counter()
    for _ in range(iterations):
        compiler.compile(config, catalog)
    elapsed_seconds = perf_counter() - started
    print(
        json.dumps(
            {
                "iterations": iterations,
                "elapsed_seconds": round(elapsed_seconds, 6),
                "compiles_per_second": round(iterations / elapsed_seconds, 2),
                "microseconds_per_compile": round(elapsed_seconds * 1_000_000 / iterations, 2),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
