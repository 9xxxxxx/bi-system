import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "../../test/TestProviders";
import { DatasetListPage } from "./DatasetListPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  return render(
    <TestProviders>
      <DatasetListPage />
    </TestProviders>,
  );
}

it("renders the loading state while datasets are requested", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => undefined)),
  );

  renderPage();

  expect(document.querySelector(".ant-spin-spinning")).toBeInTheDocument();
});

it("invites the user to create the first dataset", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ items: [], total: 0, offset: 0, limit: 50 }),
          { status: 200 },
        ),
    ),
  );

  renderPage();

  expect(await screen.findByText("还没有数据集")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "创建第一个数据集" }),
  ).toBeInTheDocument();
});

it("renders an actionable error when the dataset request fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: {
              code: "dataset_unavailable",
              message: "数据集服务暂不可用",
              action: "检查服务状态后重试",
            },
          }),
          { status: 503 },
        ),
    ),
  );

  renderPage();

  expect(await screen.findByText("数据集加载失败")).toBeInTheDocument();
  expect(screen.getByText(/检查服务状态后重试/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
});

it("renders dataset metadata and a workbench link", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            items: [
              {
                id: "dataset-sales",
                name: "销售经营数据集",
                description: "统一销售事实与组织维度",
                status: "active",
                source_count: 3,
                field_count: 24,
                metric_count: 8,
                owner_name: "数据管理员",
                updated_at: "2026-07-15T08:00:00Z",
              },
            ],
            total: 1,
            offset: 0,
            limit: 50,
          }),
          { status: 200 },
        ),
    ),
  );

  renderPage();

  expect(await screen.findByText("销售经营数据集")).toBeInTheDocument();
  expect(screen.getByText("统一销售事实与组织维度")).toBeInTheDocument();
  expect(screen.getByText("数据管理员")).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "打开" })[0]).toHaveAttribute(
    "href",
    "/datasets/dataset-sales",
  );
});
