import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
            revision: 4,
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
  expect(
    screen.getByRole("link", { name: "编辑 销售经营总览" }),
  ).toHaveAttribute("href", "/dashboards/dashboard-sales");
  expect(
    screen.getByRole("button", { name: "删除 销售经营总览" }),
  ).toBeInTheDocument();
});

it("confirms deletion with the current revision and refreshes the list", async () => {
  const requests: Array<{ url: string; method: string; body?: unknown }> = [];
  let currentListRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      requests.push({
        url,
        method,
        body:
          typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      });
      if (method === "DELETE") {
        return jsonResponse(dashboardWire("dashboard-sales", "deleted", 5));
      }
      currentListRequests += 1;
      return jsonResponse(
        currentListRequests === 1
          ? dashboardList([
              dashboardSummary("dashboard-sales", "销售经营总览", "draft", 4),
            ])
          : dashboardList([]),
      );
    }),
  );
  const user = userEvent.setup();
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "删除 销售经营总览" }),
  );
  await user.click(screen.getByRole("button", { name: "移入回收站" }));

  expect(await screen.findByText("还没有仪表盘")).toBeInTheDocument();
  expect(requests).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        url: expect.stringContaining(
          "/dashboards/dashboard-sales?expected_revision=4",
        ),
        method: "DELETE",
      }),
    ]),
  );
  expect(currentListRequests).toBe(2);
});

it("queries the recycle bin explicitly and restores an item", async () => {
  const requests: Array<{ url: string; method: string; body?: unknown }> = [];
  let recycleBinRequests = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      requests.push({
        url,
        method,
        body:
          typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      });
      if (method === "POST" && url.includes("/restore")) {
        return jsonResponse(dashboardWire("dashboard-trash", "draft", 7));
      }
      if (url.includes("status=deleted")) {
        recycleBinRequests += 1;
        return jsonResponse(
          recycleBinRequests === 1
            ? dashboardList([
                dashboardSummary(
                  "dashboard-trash",
                  "历史经营看板",
                  "deleted",
                  6,
                ),
              ])
            : dashboardList([]),
        );
      }
      return jsonResponse(dashboardList([]));
    }),
  );
  const user = userEvent.setup();
  renderPage();

  await screen.findByText("还没有仪表盘");
  await user.click(screen.getByText("回收站"));
  await user.click(
    await screen.findByRole("button", { name: "恢复 历史经营看板" }),
  );

  expect(await screen.findByText("回收站为空")).toBeInTheDocument();
  expect(requests).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        url: expect.stringMatching(
          /\/dashboards\?.*status=deleted.*include_deleted=true/,
        ),
        method: "GET",
      }),
      expect.objectContaining({
        url: expect.stringContaining("/dashboards/dashboard-trash/restore"),
        method: "POST",
        body: { expected_revision: 6 },
      }),
    ]),
  );
  expect(recycleBinRequests).toBe(2);
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

function dashboardList(items: ReturnType<typeof dashboardSummary>[]) {
  return { items, total: items.length, offset: 0, limit: 50 };
}

function dashboardSummary(
  id: string,
  name: string,
  status: "draft" | "active" | "archived" | "deleted",
  revision: number,
) {
  return {
    id,
    name,
    description: null,
    status,
    owner_name: "数据管理员",
    updated_at: "2026-07-19T08:00:00Z",
    current_version: 1,
    page_count: 1,
    capabilities: ["view", "edit"],
    revision,
  };
}

function dashboardWire(
  id: string,
  status: "draft" | "deleted",
  revision: number,
) {
  return {
    ...dashboardSummary(id, "经营看板", status, revision),
    current_version_id: `${id}-version-1`,
    pages: [],
    components: [],
    layouts: [],
  };
}
