import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { useState } from "react";

import { TestProviders } from "../../../test/TestProviders";
import { defaultChartConfig } from "../charts/config";
import type { DashboardComponent, DashboardComponentType } from "../types";
import { ChartConfigEditor } from "./ChartConfigEditor";

afterEach(() => {
  vi.unstubAllGlobals();
});

function ChartHarness({ type = "bar" }: { type?: DashboardComponentType }) {
  const [component, setComponent] = useState<DashboardComponent>(() => {
    const config = defaultChartConfig(type);
    config.query.dataset_id = "dataset-active";
    return {
      id: "component-1",
      component_type: type,
      title: "图表",
      description: null,
      ordinal: 0,
      config,
    };
  });
  return (
    <TestProviders>
      <ChartConfigEditor component={component} onChange={setComponent} />
      <output>{JSON.stringify(component.config)}</output>
    </TestProviders>
  );
}

it("uses governed names, role filters and bounded chart controls", async () => {
  vi.stubGlobal("fetch", vi.fn(catalogResponse));
  const user = userEvent.setup();
  render(<ChartHarness />);

  expect(await screen.findByText("销售数据集")).toBeInTheDocument();
  expect(screen.queryByLabelText(/UUID/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("图表 Top N")).toHaveAttribute(
    "aria-valuemax",
    "100",
  );
  expect(screen.getByText("系列维度")).toBeInTheDocument();

  await user.click(screen.getByLabelText("图表主维度"));
  expect(screen.getAllByRole("option", { name: "区域" })).not.toHaveLength(0);
  expect(screen.queryByRole("option", { name: "销售额" })).toBeNull();
  expect(screen.queryByRole("option", { name: "内部字段" })).toBeNull();
  await user.keyboard("{Escape}");

  await user.click(screen.getByRole("button", { name: /添加度量/ }));
  expect(screen.getByRole("status")).toHaveTextContent('"slot_key":"value_2"');
});

it("does not expose a series control for KPI components", async () => {
  vi.stubGlobal("fetch", vi.fn(catalogResponse));
  render(<ChartHarness type="kpi" />);

  expect(await screen.findByText("销售数据集")).toBeInTheDocument();
  expect(screen.queryByText("系列维度")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /添加度量/ })).toBeNull();
});

it("lists previously uploaded dashboard images in the image selector", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse({
        items: [
          {
            id: "asset-1",
            filename: "经营总览.png",
            content_type: "image/png",
            size_bytes: 120,
            created_at: "2026-07-19T00:00:00Z",
          },
        ],
        total: 1,
        offset: 0,
        limit: 100,
      }),
    ),
  );
  const component: DashboardComponent = {
    id: "image-1",
    component_type: "image",
    title: "组织图",
    description: null,
    ordinal: 0,
    config: { schema_version: 1, file_id: "", alt_text: "" },
  };
  render(
    <TestProviders>
      <ChartConfigEditor component={component} onChange={vi.fn()} />
    </TestProviders>,
  );

  await userEvent.click(screen.getByLabelText("选择仪表盘图片"));
  expect(
    screen.getAllByRole("option", { name: "经营总览.png" }),
  ).not.toHaveLength(0);
  expect(screen.getByRole("button", { name: /上传图片/ })).toBeInTheDocument();
});

async function catalogResponse(input: string | URL | Request) {
  const url = String(input);
  if (url.includes("/datasets?")) {
    return jsonResponse({
      items: [
        { id: "dataset-active", name: "销售数据集", status: "active" },
        { id: "dataset-draft", name: "草稿数据集", status: "draft" },
      ],
      total: 2,
      offset: 0,
      limit: 100,
    });
  }
  if (url.includes("/datasets/dataset-active")) {
    return jsonResponse({
      id: "dataset-active",
      fields: [
        {
          id: "field-region",
          label: "区域",
          role: "dimension",
          data_type: "string",
          hidden: false,
        },
        {
          id: "field-amount",
          label: "销售额",
          role: "measure",
          data_type: "decimal",
          hidden: false,
        },
        {
          id: "field-hidden",
          label: "内部字段",
          role: "dimension",
          data_type: "string",
          hidden: true,
        },
      ],
    });
  }
  return jsonResponse({
    items: [
      {
        id: "metric-active",
        dataset_id: "dataset-active",
        name: "成交额",
        version: 2,
        status: "active",
      },
      {
        id: "metric-draft",
        dataset_id: "dataset-active",
        name: "草稿指标",
        version: 1,
        status: "draft",
      },
    ],
    total: 2,
    offset: 0,
    limit: 100,
  });
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
