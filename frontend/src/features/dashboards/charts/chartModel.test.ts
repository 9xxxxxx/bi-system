import { expect, it } from "vitest";

import { buildChartModel } from "./chartModel";
import { defaultChartConfig } from "./config";
import type { DashboardChartQueryResponse } from "./types";

const response: DashboardChartQueryResponse = {
  request_id: "request-1",
  component_id: "component-1",
  columns: [
    {
      slot_key: "dimension",
      query_alias: "dimension",
      resource_kind: "field",
      resource_id: "field-region",
      aggregate: null,
      label: "区域",
      data_type: "string",
      unit: null,
    },
    {
      slot_key: "series",
      query_alias: "series",
      resource_kind: "field",
      resource_id: "field-category",
      aggregate: null,
      label: "品类",
      data_type: "string",
      unit: null,
    },
    {
      slot_key: "value",
      query_alias: "value_1",
      resource_kind: "field",
      resource_id: "field-amount",
      aggregate: "sum",
      label: "销售额",
      data_type: "decimal",
      unit: "万元",
    },
  ],
  rows: [
    { dimension: "华东", series: "硬件", value_1: "120.5" },
    { dimension: "华东", series: "软件", value_1: "80" },
    { dimension: "华南", series: "硬件", value_1: "90" },
  ],
  truncated: false,
  elapsed_ms: 12,
  dataset_version: 3,
  metric_version_ids: [],
  source_batch_ids: ["batch-1"],
  resolved_filters: [],
  warnings: [],
};

it("uses server query aliases and pivots a bounded series dimension", () => {
  const config = defaultChartConfig("stacked_bar");
  config.query.dataset_id = "dataset-1";
  config.query.dimensions[0].field_id = "field-region";
  config.query.measures[0] = {
    kind: "field",
    field_id: "field-amount",
    aggregate: "sum",
    slot_key: "value",
  };
  config.query.series_dimension = {
    field_id: "field-category",
    slot_key: "series",
    max_series: 10,
  };

  const model = buildChartModel(response, config);

  expect(model.categories).toEqual(["华东", "华南"]);
  expect(model.series).toEqual([
    {
      id: "value:硬件",
      label: "硬件",
      values: [120.5, 90],
      rawValues: ["120.5", "90"],
    },
    {
      id: "value:软件",
      label: "软件",
      values: [80, null],
      rawValues: ["80", null],
    },
  ]);
  expect(model.tableRows[0]).toEqual(["华东", "硬件", "120.5"]);
});

it("indexes rows without repeated linear searches", () => {
  const rows = [...response.rows];
  Object.defineProperty(rows, "find", {
    value: () => {
      throw new Error("row lookup must use an index");
    },
  });
  const config = defaultChartConfig("stacked_bar");
  config.query.dataset_id = "dataset-1";
  config.query.dimensions[0].field_id = "field-region";
  config.query.measures = [
    {
      kind: "field",
      field_id: "field-amount",
      aggregate: "sum",
      slot_key: "value",
    },
  ];
  config.query.series_dimension = {
    field_id: "field-category",
    slot_key: "series",
    max_series: 10,
  };

  expect(buildChartModel({ ...response, rows }, config).series).toHaveLength(2);
});
