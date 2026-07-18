import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import { TestProviders } from "../../../test/TestProviders";
import type { DashboardDetail } from "../types";
import { DashboardEditorPage } from "./DashboardEditorPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

const dashboard: DashboardDetail = {
  id: "dashboard-sales",
  name: "销售经营总览",
  description: "统一销售经营视图",
  status: "draft",
  owner_name: "数据管理员",
  updated_at: "2026-07-19T08:00:00Z",
  current_version: 2,
  page_count: 1,
  capabilities: ["view", "edit"],
  revision: 7,
  current_version_id: "dashboard-version-2",
  pages: [
    {
      id: "page-overview",
      title: "经营概览",
      ordinal: 0,
      components: [
        {
          id: "component-revenue",
          component_type: "kpi",
          title: "总营收",
          description: null,
          ordinal: 0,
          config: { schema_version: 1, state: "placeholder" },
        },
      ],
    },
  ],
  layouts: [
    {
      schema_version: 1,
      profile: "desktop",
      columns: 12,
      row_height: 44,
      items: [
        {
          component_id: "component-revenue",
          x: 0,
          y: 0,
          width: 4,
          height: 4,
          min_width: 2,
          min_height: 3,
        },
      ],
    },
    {
      schema_version: 1,
      profile: "mobile",
      columns: 4,
      row_height: 44,
      items: [
        {
          component_id: "component-revenue",
          x: 0,
          y: 0,
          width: 4,
          height: 4,
          min_width: 2,
          min_height: 3,
        },
      ],
    },
  ],
};

function renderPage() {
  return render(
    <TestProviders initialEntries={["/dashboards/dashboard-sales"]}>
      <Routes>
        <Route
          path="/dashboards/:dashboardId"
          element={<DashboardEditorPage />}
        />
      </Routes>
    </TestProviders>,
  );
}

it("renders a stable editor loading state", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise<Response>(() => undefined)),
  );

  renderPage();

  expect(screen.getByLabelText("正在加载仪表盘编辑器")).toBeInTheDocument();
});

it("renders the component palette, 12-column canvas and property inspector", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse(toWire(dashboard))),
  );
  const user = userEvent.setup();
  renderPage();

  expect(
    await screen.findByRole("heading", { name: "销售经营总览" }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("组件面板")).toBeInTheDocument();
  expect(screen.getByLabelText("12 列仪表盘画布")).toHaveTextContent(
    "12 列 · 44px 行高",
  );
  expect(screen.getByLabelText("属性面板")).toBeInTheDocument();
  expect(screen.getByDisplayValue("总营收")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "添加柱状图组件" }));
  expect(screen.getByText("2 个组件")).toBeInTheDocument();
  expect(screen.getByDisplayValue("柱状图")).toBeInTheDocument();
  expect(screen.getByText("有未保存更改")).toBeInTheDocument();
});

it("shows an explicit empty canvas for a blank draft", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse(
        toWire({
          ...dashboard,
          pages: [{ ...dashboard.pages[0], components: [] }],
          layouts: dashboard.layouts.map((layout) => ({
            ...layout,
            items: [],
          })),
        }),
      ),
    ),
  );

  renderPage();

  expect(await screen.findByText("从左侧添加第一个组件")).toBeInTheDocument();
  expect(screen.getByText("0 个组件")).toBeInTheDocument();
});

it("saves the complete draft aggregate with optimistic concurrency", async () => {
  let saveBody: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === "POST") {
        saveBody =
          typeof init.body === "string" ? JSON.parse(init.body) : undefined;
        return jsonResponse(
          toWire({
            ...dashboard,
            revision: 8,
            current_version: 3,
            current_version_id: "dashboard-version-3",
          }),
        );
      }
      return jsonResponse(toWire(dashboard));
    }),
  );
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole("button", { name: /保存新版本/ }));

  await waitFor(() =>
    expect(screen.getByText("已保存 v3")).toBeInTheDocument(),
  );
  expect(saveBody).toMatchObject({
    base_version: 2,
    expected_revision: 7,
    pages: [{ page_id: "page-overview" }],
    components: [
      {
        component_id: "component-revenue",
        page_id: "page-overview",
        config_version: 1,
      },
    ],
    layouts: [
      { profile: "desktop", columns: 12 },
      { profile: "mobile", columns: 4 },
    ],
  });
});

it("renders a recoverable editor error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse(
        { detail: { message: "仪表盘读取失败", action: "检查网络后重试" } },
        500,
      ),
    ),
  );

  renderPage();

  expect(await screen.findByText("仪表盘加载失败")).toBeInTheDocument();
  expect(screen.getByText(/检查网络后重试/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
});

it("renders editor forbidden without exposing an empty canvas", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse(
        {
          detail: {
            code: "dashboard_forbidden",
            message: "无权查看此仪表盘",
            action: "联系所有者申请权限",
          },
        },
        403,
      ),
    ),
  );

  renderPage();

  expect(await screen.findByText("没有仪表盘访问权限")).toBeInTheDocument();
  expect(screen.queryByLabelText("12 列仪表盘画布")).not.toBeInTheDocument();
});

it("uses the independent mobile profile and removes editing controls at 390px", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query === "(max-width: 768px)",
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(() => false),
    })),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse(toWire(dashboard))),
  );

  renderPage();

  expect(await screen.findByText("移动端为只读模式")).toBeInTheDocument();
  expect(screen.getByLabelText("只读仪表盘画布")).toHaveTextContent("只读布局");
  expect(screen.queryByLabelText("组件面板")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("属性面板")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /保存新版本/ }),
  ).not.toBeInTheDocument();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function toWire(detail: DashboardDetail) {
  return {
    ...detail,
    pages: detail.pages.map((page) => ({
      page_id: page.id,
      title: page.title,
      ordinal: page.ordinal,
    })),
    components: detail.pages.flatMap((page) =>
      page.components.map((component) => ({
        component_id: component.id,
        page_id: page.id,
        component_type: component.component_type,
        config_version: 1,
        config: {
          ...component.config,
          title: component.title,
          description: component.description,
        },
        ordinal: component.ordinal,
      })),
    ),
  };
}
