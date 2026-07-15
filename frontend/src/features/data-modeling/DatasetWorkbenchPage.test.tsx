import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "../../test/TestProviders";
import { DatasetWorkbenchPage } from "./DatasetWorkbenchPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function responseFor(url: string): Response {
  if (url.includes("/datasets?")) {
    return new Response(
      JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }),
      { status: 200 },
    );
  }
  if (url.endsWith("/data-sources")) {
    return new Response(
      JSON.stringify([
        {
          id: "source-sales",
          name: "销售明细",
          status: "active",
          active_row_count: 1800,
          latest_batch_id: "batch-1",
          fields: [
            {
              id: "field-amount",
              display_name: "销售金额",
              data_type: "decimal",
              nullable: false,
            },
          ],
        },
      ]),
      { status: 200 },
    );
  }
  throw new Error(`Unexpected request: ${url}`);
}

it("renders a source-led modeling workspace and mobile boundary", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => responseFor(String(input))),
  );

  render(
    <TestProviders initialEntries={["/datasets/new"]}>
      <DatasetWorkbenchPage />
    </TestProviders>,
  );

  expect(await screen.findByText("未命名数据集")).toBeInTheDocument();
  expect(screen.getAllByText("销售明细").length).toBeGreaterThan(0);
  expect(screen.getByText("销售金额")).toBeInTheDocument();
  expect(screen.getByText("移动端为只读模式")).toBeInTheDocument();
  expect(screen.getByText("维度关系待配置")).toBeInTheDocument();
});

it("renders the empty modeling state when no source is available", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.includes("/datasets?")) {
        return new Response(
          JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }),
          { status: 200 },
        );
      }
      return new Response("[]", { status: 200 });
    }),
  );

  render(
    <TestProviders initialEntries={["/datasets/new"]}>
      <DatasetWorkbenchPage />
    </TestProviders>,
  );

  expect(await screen.findByText("导入数据后即可开始建模")).toBeInTheDocument();
  expect(screen.getByText("没有可用数据源")).toBeInTheDocument();
  expect(screen.getByText("未选择数据源")).toBeInTheDocument();
});

it("renders a recoverable error when modeling resources fail", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ detail: { message: "数据源读取失败" } }),
          { status: 500 },
        ),
    ),
  );

  render(
    <TestProviders initialEntries={["/datasets/new"]}>
      <DatasetWorkbenchPage />
    </TestProviders>,
  );

  expect(await screen.findByText("建模工作台加载失败")).toBeInTheDocument();
  expect(screen.getByText("数据源读取失败")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
});
