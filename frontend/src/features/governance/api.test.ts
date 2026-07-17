import { afterEach, expect, it, vi } from "vitest";

import type { DatasetField } from "../data-modeling/types";
import { createMetric, publishRowPolicy } from "./api";
import {
  numericAggregateOptions,
  toMetricRequest,
  toPolicyRequest,
} from "./formContracts";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("sends metric creation with backend aggregate enum values", async () => {
  expect(numericAggregateOptions.map((option) => option.value)).toEqual([
    "sum",
    "avg",
    "min",
    "max",
    "count",
    "count_distinct",
  ]);
  const request = toMetricRequest({
    dataset_id: "dataset-1",
    code: " average_sales ",
    name: " 平均销售额 ",
    description: " 平均口径 ",
    field_id: "field-amount",
    aggregate: "avg",
    status: "active",
  });
  expect(request).toEqual({
    dataset_id: "dataset-1",
    code: "average_sales",
    name: "平均销售额",
    description: "平均口径",
    formula: {
      op: "aggregate",
      function: "avg",
      field_id: "field-amount",
    },
    unit: null,
    dimension_field_ids: [],
    status: "active",
  });
  const fetchMock = vi.fn(
    async () =>
      new Response(JSON.stringify({ id: "metric-1" }), { status: 201 }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await createMetric(request);

  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringMatching(/\/api\/v1\/metrics$/),
    expect.objectContaining({ method: "POST", body: JSON.stringify(request) }),
  );
});

it("rejects invalid numeric policy values before an API request", () => {
  const decimalField: DatasetField = {
    id: "field-amount",
    model_source_id: "source-1",
    source_column_id: "column-amount",
    name: "amount",
    label: "销售金额",
    field_kind: "source",
    role: "measure",
    data_type: "decimal",
    hidden: false,
    ordinal: 0,
  };

  expect(() =>
    toPolicyRequest(
      {
        dataset_id: "dataset-1",
        name: "金额规则",
        effect: "allow",
        field_id: decimalField.id,
        operator: "gt",
        value: "not-a-number",
      },
      [decimalField],
    ),
  ).toThrow("策略条件值必须是有效数值");
});

it("rejects invalid boolean policy values before an API request", () => {
  const booleanField: DatasetField = {
    id: "field-enabled",
    model_source_id: "source-1",
    source_column_id: "column-enabled",
    name: "enabled",
    label: "是否启用",
    field_kind: "source",
    role: "dimension",
    data_type: "boolean",
    hidden: false,
    ordinal: 0,
  };

  expect(() =>
    toPolicyRequest(
      {
        dataset_id: "dataset-1",
        name: "启用规则",
        effect: "allow",
        field_id: booleanField.id,
        operator: "eq",
        value: "unknown",
      },
      [booleanField],
    ),
  ).toThrow("策略条件值必须是有效布尔值");
});

it("creates, binds, and activates a row policy in order", async () => {
  const calls: Array<{ method: string; path: string; body?: string }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      calls.push({
        method: init?.method ?? "GET",
        path: url.pathname,
        body: init?.body as string | undefined,
      });
      const status = url.pathname.endsWith("/row-policies") ? 201 : 200;
      return new Response(
        JSON.stringify(
          policy(url.pathname.endsWith("/activate") ? "active" : "draft"),
        ),
        { status },
      );
    }),
  );

  const result = await publishRowPolicy(
    {
      dataset_id: "dataset-1",
      name: "华东区域访问",
      effect: "allow",
      expression: {
        kind: "comparison",
        field_id: "field-region",
        operator: "eq",
        value: "华东",
      },
    },
    ["user-1"],
    ["role-1"],
  );

  expect(result.status).toBe("active");
  expect(calls.map(({ method, path }) => `${method} ${path}`)).toEqual([
    "POST /api/v1/row-policies",
    "PUT /api/v1/row-policies/policy-1/bindings",
    "POST /api/v1/row-policies/policy-1/activate",
  ]);
  expect(JSON.parse(calls[1].body ?? "{}")).toEqual({
    user_ids: ["user-1"],
    role_ids: ["role-1"],
  });
});

function policy(status: "draft" | "active") {
  return {
    id: "policy-1",
    dataset_id: "dataset-1",
    name: "华东区域访问",
    version: 1,
    effect: "allow",
    status,
    user_ids: [],
    role_ids: [],
    updated_at: "2026-07-17T08:00:00Z",
  };
}
