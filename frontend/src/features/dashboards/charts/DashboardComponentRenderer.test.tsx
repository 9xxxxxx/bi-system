import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "../../../test/TestProviders";
import type { DashboardComponent } from "../types";
import { defaultChartConfig } from "./config";
import { DashboardComponentRenderer } from "./DashboardComponentRenderer";

vi.mock("./EChartRenderer", () => ({
  default: () => (
    <div role="img" aria-label="mock-echart">
      canvas
    </div>
  ),
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

function chartComponent(type: DashboardComponent["component_type"] = "kpi") {
  const config = defaultChartConfig(type);
  config.query.dataset_id = "dataset-1";
  if (config.query.dimensions[0])
    config.query.dimensions[0].field_id = "field-region";
  config.query.measures = config.query.measures.map((measure, index) => ({
    kind: "field" as const,
    field_id: index === 0 ? "field-amount" : "field-target",
    aggregate: "sum" as const,
    slot_key: measure.slot_key,
  }));
  return {
    id: "component-1",
    component_type: type,
    title: "销售额",
    description: null,
    ordinal: 0,
    config,
  } satisfies DashboardComponent;
}

function renderComponent(component: DashboardComponent = chartComponent()) {
  return render(
    <TestProviders>
      <DashboardComponentRenderer
        dashboardId="dashboard-1"
        dashboardVersionId="dashboard-version-1"
        pageId="page-1"
        component={component}
        preview
        globalFilter={{
          kind: "comparison",
          field_id: "field-region",
          operator: "eq",
          value: "华东",
        }}
        pageFilter={null}
      />
    </TestProviders>,
  );
}

it("renders loading and exposes cancellation", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => undefined)),
  );
  renderComponent();
  expect(screen.getByLabelText("正在加载图表数据")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "取消查询" })).toBeInTheDocument();
});

it("renders KPI success with source evidence and the exact preview wire", async () => {
  let body: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      return chartResponse([{ value_1: "128.5" }]);
    }),
  );
  renderComponent();

  expect(await screen.findAllByText("128.5")).toHaveLength(2);
  expect(screen.getByText("数据集 v3")).toBeInTheDocument();
  expect(screen.getByText("1 个来源批次")).toBeInTheDocument();
  expect(screen.getByText("Dataset version")).toBeInTheDocument();
  expect(screen.getByText("Metric version IDs")).toBeInTheDocument();
  expect(screen.getByText("Source batch IDs")).toBeInTheDocument();
  expect(screen.getByText("Resolved filters")).toBeInTheDocument();
  expect(body).toMatchObject({
    dashboard_id: "dashboard-1",
    dashboard_version_id: "dashboard-version-1",
    page_id: "page-1",
    component_id: "component-1",
    runtime_filters: {
      global_filter: {
        kind: "comparison",
        field_id: "field-region",
        operator: "eq",
        value: "华东",
      },
      page_filter: null,
      component_filter: null,
    },
    preview_component: {
      component_id: "component-1",
      page_id: "page-1",
      component_type: "kpi",
      config_version: 1,
    },
  });
  expect(
    (body as { preview_component: Record<string, unknown> }).preview_component,
  ).not.toHaveProperty("ordinal");
});

it("renders empty, forbidden and timeout as distinct states", async () => {
  const responses = [
    chartResponse([]),
    problem(403, "dataset_query_forbidden", "无权查询底层数据"),
    problem(504, "dataset_query_timeout", "查询超过限制"),
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => responses.shift()!),
  );
  const first = renderComponent();
  expect(await screen.findByText("当前筛选条件下暂无数据")).toBeInTheDocument();
  first.unmount();
  const second = renderComponent();
  expect(await screen.findByText("无权查询图表数据")).toBeInTheDocument();
  second.unmount();
  renderComponent();
  expect(await screen.findByText("图表查询超时")).toBeInTheDocument();
});

it("lazy renders canvas charts, truncation, warnings and accessible data", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      chartResponse(
        [{ dimension: "超长区域标签用于验证布局不会改变", value_1: "128.5" }],
        true,
      ),
    ),
  );
  renderComponent(chartComponent("bar"));

  expect(await screen.findByText("结果已截断")).toBeInTheDocument();
  expect(
    await screen.findByRole("img", { name: "mock-echart" }),
  ).toBeInTheDocument();
  expect(screen.getByText("查看无障碍数据表")).toBeInTheDocument();
  expect(
    screen.getByText("超长区域标签用于验证布局不会改变"),
  ).toBeInTheDocument();
});

it("renders governed rich text and controlled image resources without a query", () => {
  const richText: DashboardComponent = {
    id: "component-text",
    component_type: "rich_text",
    title: "说明",
    description: null,
    ordinal: 0,
    config: { schema_version: 1, content: "经营口径说明" },
  };
  const first = renderComponent(richText);
  expect(screen.getByText("经营口径说明")).toBeInTheDocument();
  first.unmount();
  const image: DashboardComponent = {
    id: "component-image",
    component_type: "image",
    title: "组织图",
    description: null,
    ordinal: 0,
    config: {
      schema_version: 1,
      file_id: "file-controlled",
      alt_text: "销售组织结构",
    },
  };
  renderComponent(image);
  expect(
    screen.getByRole("img", { name: "销售组织结构" }).getAttribute("src"),
  ).toMatch(/\/api\/v1\/dashboard-assets\/file-controlled\/content$/);
});

function chartResponse(
  rows: Array<Record<string, unknown>>,
  truncated = false,
) {
  const columns = rows[0]?.dimension
    ? [
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
        valueColumn,
      ]
    : [valueColumn];
  return new Response(
    JSON.stringify({
      request_id: "request-1",
      component_id: "component-1",
      columns,
      rows,
      truncated,
      elapsed_ms: 12.5,
      dataset_version: 3,
      metric_version_ids: [],
      source_batch_ids: ["batch-1"],
      resolved_filters: [],
      warnings: truncated
        ? [{ code: "top_n_applied", message: "已应用 Top N" }]
        : [],
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

const valueColumn = {
  slot_key: "value",
  query_alias: "value_1",
  resource_kind: "field",
  resource_id: "field-amount",
  aggregate: "sum",
  label: "销售额",
  data_type: "decimal",
  unit: null,
};

function problem(status: number, code: string, message: string) {
  return new Response(
    JSON.stringify({ detail: { code, message, action: "调整后重试" } }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}
