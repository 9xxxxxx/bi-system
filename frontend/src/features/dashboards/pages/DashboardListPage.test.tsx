import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "../../../test/TestProviders";
import { DashboardListPage } from "./DashboardListPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage() {
  return render(
    <TestProviders>
      <DashboardListPage />
    </TestProviders>,
  );
}

it("renders a dedicated loading state", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => undefined)),
  );

  renderPage();

  expect(screen.getByLabelText("正在加载仪表盘列表")).toBeInTheDocument();
  expect(document.querySelector(".ant-skeleton-active")).toBeInTheDocument();
});

it("renders blank and template entries for the first dashboard", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse({ items: [], total: 0, offset: 0, limit: 50 }),
    ),
  );

  renderPage();

  expect(await screen.findByText("还没有仪表盘")).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "创建第一个仪表盘" }),
  ).toHaveAttribute("href", "/dashboards/new");
  expect(screen.getByRole("link", { name: "浏览模板" })).toHaveAttribute(
    "href",
    "/dashboards/new?source=template",
  );
});

it("renders dashboard metadata and capability-aware actions", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse({
        items: [
          {
            id: "dashboard-sales",
            name: "销售经营总览",
            description: "销售目标与区域表现",
            status: "draft",
            owner_name: "数据管理员",
            updated_at: "2026-07-19T08:00:00Z",
            current_version: 2,
            page_count: 3,
            capabilities: ["view", "edit"],
          },
        ],
        total: 1,
        offset: 0,
        limit: 50,
      }),
    ),
  );

  renderPage();

  expect(await screen.findByText("销售经营总览")).toBeInTheDocument();
  expect(screen.getByText("销售目标与区域表现")).toBeInTheDocument();
  expect(screen.getByText("v2")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "编辑" })).toHaveAttribute(
    "href",
    "/dashboards/dashboard-sales",
  );
});

it("renders an actionable error state", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse(
        {
          detail: {
            code: "dashboard_service_unavailable",
            message: "仪表盘服务暂不可用",
            action: "稍后重新加载",
          },
        },
        503,
      ),
    ),
  );

  renderPage();

  expect(await screen.findByText("仪表盘加载失败")).toBeInTheDocument();
  expect(screen.getByText(/稍后重新加载/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
});

it("keeps forbidden distinct from an empty list", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse(
        {
          detail: {
            code: "dashboard_forbidden",
            message: "无权查看工作区仪表盘",
            action: "联系管理员申请权限",
          },
        },
        403,
      ),
    ),
  );

  renderPage();

  expect(await screen.findByText("没有仪表盘访问权限")).toBeInTheDocument();
  expect(screen.getByText(/联系管理员申请权限/)).toBeInTheDocument();
  expect(screen.queryByText("还没有仪表盘")).not.toBeInTheDocument();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
