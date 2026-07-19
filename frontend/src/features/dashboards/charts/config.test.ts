import { expect, it } from "vitest";

import { defaultChartConfig, hasRunnableQuery } from "./config";
import type { DashboardComponentType } from "../types";

const queryTypes: DashboardComponentType[] = [
  "kpi",
  "trend_indicator",
  "target_progress",
  "detail_table",
  "ranking_table",
  "bar",
  "horizontal_bar",
  "stacked_bar",
  "line",
  "area",
  "pie",
  "donut",
];

it.each(queryTypes)("creates a strict versioned config for %s", (type) => {
  const config = defaultChartConfig(type);
  expect(config.schema_version).toBe(1);
  expect(config.query).not.toHaveProperty("schema_version");
  expect(config.query.measures.length).toBe(
    ["target_progress", "stacked_bar"].includes(type) ? 2 : 1,
  );
  expect(config).not.toHaveProperty("date_filter");
  expect(hasRunnableQuery(config)).toBe(false);
});

it("creates a backend-valid stacked bar without requiring a series", () => {
  const config = defaultChartConfig("stacked_bar");
  expect(config.query.series_dimension).toBeNull();
  expect(config.query.measures.map((measure) => measure.slot_key)).toEqual([
    "value",
    "value_2",
  ]);
});
