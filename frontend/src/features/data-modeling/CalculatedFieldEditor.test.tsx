import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "../../test/TestProviders";
import { CalculatedFieldEditor } from "./CalculatedFieldEditor";
import { parseCalculatedLiteral } from "./calculatedFieldContracts";
import type { DatasetDetail } from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
});

const dataset: DatasetDetail = {
  id: "dataset-sales",
  semantic_model_id: "model-sales",
  series_id: "series-sales",
  version: 1,
  name: "销售数据集",
  description: null,
  status: "active",
  source_count: 1,
  field_count: 3,
  metric_count: 0,
  owner_name: "数据管理员",
  updated_at: "2026-07-17T08:00:00Z",
  fields: [
    {
      id: "field-revenue",
      model_source_id: "model-source-sales",
      source_column_id: "column-revenue",
      name: "revenue",
      label: "收入",
      field_kind: "source",
      role: "measure",
      data_type: "decimal",
      hidden: false,
      ordinal: 0,
    },
    {
      id: "field-cost",
      model_source_id: "model-source-sales",
      source_column_id: "column-cost",
      name: "cost",
      label: "成本",
      field_kind: "source",
      role: "measure",
      data_type: "decimal",
      hidden: false,
      ordinal: 1,
    },
    {
      id: "field-region",
      model_source_id: "model-source-sales",
      source_column_id: "column-region",
      name: "region",
      label: "区域",
      field_kind: "source",
      role: "dimension",
      data_type: "string",
      hidden: false,
      ordinal: 2,
    },
  ],
};

function renderEditor(onCreated = vi.fn()) {
  render(
    <TestProviders>
      <CalculatedFieldEditor
        dataset={dataset}
        mobileReadonly={false}
        onCreated={onCreated}
      />
    </TestProviders>,
  );
  return onCreated;
}

it("creates a safe division field and returns the new dataset version", async () => {
  let requestBody: unknown;
  const nextDataset = { ...dataset, id: "dataset-sales-v2", version: 2 };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      requestBody =
        typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      return new Response(JSON.stringify(nextDataset), { status: 201 });
    }),
  );
  const onCreated = renderEditor();
  fireEvent.click(screen.getByRole("button", { name: /计算字段/ }));
  fireEvent.change(screen.getByLabelText("计算字段名称"), {
    target: { value: "profit_rate" },
  });
  fireEvent.change(screen.getByLabelText("计算字段标签"), {
    target: { value: "利润率" },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建新版本" }));

  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(nextDataset));
  expect(requestBody).toEqual({
    name: "profit_rate",
    label: "利润率",
    role: "measure",
    data_type: "decimal",
    hidden: false,
    expression: {
      op: "safe_divide",
      numerator: { op: "field", field_id: "field-revenue" },
      denominator: { op: "field", field_id: "field-cost" },
      fallback: null,
    },
  });
}, 15_000);

it("creates a CASE field with a comparison filter and literal branches", async () => {
  let requestBody: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      requestBody =
        typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      return new Response(JSON.stringify({ ...dataset, version: 2 }), {
        status: 201,
      });
    }),
  );
  const onCreated = renderEditor();
  fireEvent.click(screen.getByRole("button", { name: /计算字段/ }));
  fireEvent.click(screen.getByText("条件 CASE"));
  fireEvent.change(screen.getByLabelText("计算字段名称"), {
    target: { value: "region_score" },
  });
  fireEvent.change(screen.getByLabelText("计算字段标签"), {
    target: { value: "区域评分" },
  });
  fireEvent.change(screen.getByLabelText("CASE比较值"), {
    target: { value: "100" },
  });
  fireEvent.change(screen.getByLabelText("CASE命中值"), {
    target: { value: "100" },
  });
  fireEvent.change(screen.getByLabelText("CASE默认值"), {
    target: { value: "0" },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建新版本" }));

  await waitFor(() => expect(onCreated).toHaveBeenCalled());
  expect(requestBody).toMatchObject({
    expression: {
      op: "case",
      when: {
        kind: "comparison",
        field_id: "field-revenue",
        operator: "eq",
        value: 100,
      },
      then: { op: "literal", value: 100 },
      else: { op: "literal", value: 0 },
    },
  });
}, 15_000);

it("keeps the editor unavailable in mobile read-only mode", () => {
  render(
    <TestProviders>
      <CalculatedFieldEditor
        dataset={dataset}
        mobileReadonly
        onCreated={vi.fn()}
      />
    </TestProviders>,
  );

  expect(screen.getByRole("button", { name: /计算字段/ })).toBeDisabled();
});

it("rejects fractional values for integer literals", () => {
  expect(() => parseCalculatedLiteral("1.5", "integer")).toThrow(
    "请输入有效整数",
  );
  expect(parseCalculatedLiteral("1", "integer")).toBe(1);
});

it("keeps the editor open with an actionable API error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: {
              message: "计算字段类型不兼容",
              action: "调整结果类型后重试",
            },
          }),
          { status: 422 },
        ),
    ),
  );
  renderEditor();
  fireEvent.click(screen.getByRole("button", { name: /计算字段/ }));
  fireEvent.change(screen.getByLabelText("计算字段名称"), {
    target: { value: "invalid_field" },
  });
  fireEvent.change(screen.getByLabelText("计算字段标签"), {
    target: { value: "无效字段" },
  });
  fireEvent.click(screen.getByRole("button", { name: "创建新版本" }));

  expect(await screen.findByText("计算字段创建失败")).toBeInTheDocument();
  expect(screen.getByText(/调整结果类型后重试/)).toBeInTheDocument();
  expect(screen.getByRole("dialog")).toBeInTheDocument();
}, 10_000);
