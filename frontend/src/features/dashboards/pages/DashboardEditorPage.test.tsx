import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import { TestProviders } from "../../../test/TestProviders";
import { defaultChartConfig } from "../charts/config";
import { dashboardQueryKeys } from "../queryKeys";
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

function QueryClientCapture({
  onCapture,
}: {
  onCapture: (queryClient: QueryClient) => void;
}) {
  onCapture(useQueryClient());
  return null;
}

function renderPage(onQueryClient?: (queryClient: QueryClient) => void) {
  return render(
    <TestProviders initialEntries={["/dashboards/dashboard-sales"]}>
      {onQueryClient ? <QueryClientCapture onCapture={onQueryClient} /> : null}
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
  expect(document.querySelector(".react-grid-layout")).toBeInTheDocument();
  expect(document.querySelector(".react-resizable-handle")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "添加柱状图组件" }));
  expect(screen.getByText("2 个组件")).toBeInTheDocument();
  expect(screen.getByDisplayValue("柱状图")).toBeInTheDocument();
  expect(screen.getByText("有未保存更改")).toBeInTheDocument();
});

it("persists stable layout changes and copied components in both profiles", async () => {
  let saveBody: unknown;
  let queryClient: QueryClient | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === "POST") {
        saveBody = JSON.parse(String(init.body));
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
  const view = renderPage((client) => {
    queryClient = client;
  });

  await screen.findByRole("heading", { name: "销售经营总览" });
  const revenue = view.container.querySelector<HTMLElement>(
    '[data-component-id="component-revenue"]',
  )!;
  expect(revenue).toHaveAttribute("data-layout-x", "0");
  fireEvent.keyDown(revenue, { key: "ArrowRight" });
  await waitFor(() =>
    expect(
      view.container.querySelector('[data-component-id="component-revenue"]'),
    ).toHaveAttribute("data-layout-x", "1"),
  );
  fireEvent.keyDown(
    view.container.querySelector('[data-component-id="component-revenue"]')!,
    { key: "ArrowRight", shiftKey: true },
  );
  await waitFor(() =>
    expect(
      view.container.querySelector('[data-component-id="component-revenue"]'),
    ).toHaveAttribute("data-layout-width", "5"),
  );

  await user.click(screen.getByRole("button", { name: "复制当前组件" }));
  await user.click(screen.getByRole("button", { name: "粘贴组件" }));
  expect(screen.getByText("2 个组件")).toBeInTheDocument();
  expect(screen.getByDisplayValue("总营收 副本")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /保存新版本/ }));
  await waitFor(() => expect(saveBody).toBeDefined());
  const wire = saveBody as {
    components: Array<{
      component_id: string;
      config: { title: string };
    }>;
    layouts: Array<{
      profile: "desktop" | "mobile";
      items: Array<{
        component_id: string;
        x: number;
        y: number;
        width: number;
      }>;
    }>;
  };
  const copied = wire.components.find(
    (component) => component.component_id !== "component-revenue",
  )!;
  expect(copied.config.title).toBe("总营收 副本");
  const desktop = wire.layouts.find((layout) => layout.profile === "desktop")!;
  const mobile = wire.layouts.find((layout) => layout.profile === "mobile")!;
  expect(desktop.items).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        component_id: "component-revenue",
        x: 1,
      }),
      expect.objectContaining({
        component_id: copied.component_id,
        x: 0,
        y: 4,
        width: 5,
      }),
    ]),
  );
  expect(mobile.items).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        component_id: "component-revenue",
        x: 0,
      }),
      expect.objectContaining({
        component_id: copied.component_id,
        x: 0,
        y: 4,
        width: 4,
      }),
    ]),
  );
  await waitFor(() =>
    expect(
      queryClient?.getQueryData<DashboardDetail>(
        dashboardQueryKeys.detail(dashboard.id),
      )?.revision,
    ).toBe(8),
  );

  act(() => {
    queryClient?.setQueryData(
      dashboardQueryKeys.detail(dashboard.id),
      dashboard,
    );
  });
  await waitFor(() =>
    expect(
      queryClient?.getQueryData<DashboardDetail>(
        dashboardQueryKeys.detail(dashboard.id),
      )?.revision,
    ).toBe(8),
  );

  const newerDashboard: DashboardDetail = {
    ...dashboard,
    revision: 9,
    current_version: 4,
    current_version_id: "dashboard-version-4",
    pages: [{ ...dashboard.pages[0], title: "服务端推进页面" }],
  };
  act(() => {
    queryClient?.setQueryData(
      dashboardQueryKeys.detail(dashboard.id),
      newerDashboard,
    );
  });
  expect(
    await screen.findByRole("button", { name: "服务端推进页面" }),
  ).toBeInTheDocument();
  expect(screen.getByText("已同步最新版本")).toBeInTheDocument();
});

it("navigates multiple pages without mixing component layout snapshots", async () => {
  const secondComponent = {
    ...dashboard.pages[0].components[0],
    id: "component-margin",
    title: "区域利润率",
  };
  const multiPage: DashboardDetail = {
    ...dashboard,
    page_count: 2,
    pages: [
      dashboard.pages[0],
      {
        id: "page-region",
        title: "区域分析",
        ordinal: 1,
        components: [secondComponent],
      },
    ],
    layouts: dashboard.layouts.map((layout) => ({
      ...layout,
      items: [
        ...layout.items,
        {
          ...layout.items[0],
          component_id: secondComponent.id,
          x: layout.profile === "desktop" ? 4 : 0,
          y: layout.profile === "desktop" ? 0 : 4,
        },
      ],
    })),
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse(toWire(multiPage))),
  );
  const user = userEvent.setup();
  const view = renderPage();

  await screen.findByDisplayValue("总营收");
  await user.click(screen.getByRole("button", { name: "区域分析" }));
  expect(screen.getByDisplayValue("区域利润率")).toBeInTheDocument();
  expect(
    view.container.querySelector('[data-component-id="component-revenue"]'),
  ).not.toBeInTheDocument();
  expect(
    view.container.querySelector('[data-component-id="component-margin"]'),
  ).toHaveAttribute("data-layout-x", "4");
});

it("adds, renames, reorders and deletes pages with both layout profiles cleaned", async () => {
  let saveBody: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === "POST") {
        saveBody = JSON.parse(String(init.body));
        return jsonResponse(toWire(dashboard));
      }
      return jsonResponse(toWire(dashboard));
    }),
  );
  const user = userEvent.setup();
  renderPage();

  await screen.findByDisplayValue("总营收");
  expect(screen.getByRole("button", { name: "删除页面" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "新增页面" }));
  let dialog = await screen.findByRole("dialog", { name: "新增页面" });
  const pageName = within(dialog).getByLabelText("页面名称");
  await user.clear(pageName);
  await user.type(pageName, "区域分析");
  await user.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
  expect(screen.getByRole("button", { name: "经营概览" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "区域分析" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "重命名页面" }));
  dialog = await screen.findByRole("dialog", { name: "重命名页面" });
  const renamedPage = within(dialog).getByLabelText("页面名称");
  await user.clear(renamedPage);
  await user.type(renamedPage, "经营分析");
  await user.click(within(dialog).getByRole("button", { name: /确\s*定/ }));
  expect(screen.getByRole("button", { name: "经营分析" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "经营概览" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "页面左移" }));
  expect(screen.getByRole("button", { name: "经营分析" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "经营概览" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "页面右移" }));
  expect(screen.getByRole("button", { name: "经营分析" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "经营概览" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "页面左移" }));
  expect(screen.getByRole("button", { name: "经营分析" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "经营概览" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "经营概览" }));
  expect(screen.getByRole("button", { name: "经营分析" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "经营概览" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "删除页面" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "删除页面" }));
  expect(await screen.findByText("删除当前页面？")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^删\s*除$/ }));

  expect(
    screen.queryByRole("button", { name: "经营概览" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "删除页面" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: /保存新版本/ }));
  await waitFor(() => expect(saveBody).toBeDefined());
  expect(saveBody).toMatchObject({
    pages: [{ title: "经营分析", ordinal: 0 }],
    components: [],
    layouts: [
      { profile: "desktop", items: [] },
      { profile: "mobile", items: [] },
    ],
  });
});

it("creates and publishes a template from the current saved version", async () => {
  const requests: Array<{ url: string; body: unknown }> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/dashboard-templates")) {
        requests.push({ url, body: JSON.parse(String(init?.body)) });
        return jsonResponse(
          templateDetail({ revision: 3, status: "draft" }),
          201,
        );
      }
      if (url.endsWith("/dashboard-templates/template-sales/publish")) {
        requests.push({ url, body: JSON.parse(String(init?.body)) });
        return jsonResponse(
          templateDetail({ revision: 4, status: "published" }),
        );
      }
      return jsonResponse(toWire(dashboard));
    }),
  );
  const user = userEvent.setup();
  renderPage();

  await user.click(
    await screen.findByRole("button", {
      name: "发布当前已保存版本为模板",
    }),
  );
  let dialog = await screen.findByRole("dialog", {
    name: "发布当前版本为模板",
  });
  const templateName = within(dialog).getByLabelText("模板名称");
  await user.clear(templateName);
  await user.type(templateName, "销售经营模板");
  await user.click(within(dialog).getByRole("button", { name: /发\s*布/ }));

  expect(await screen.findByText("模板已发布")).toBeInTheDocument();
  expect(requests).toHaveLength(2);
  expect(requests[0].body).toEqual({
    name: "销售经营模板",
    description: dashboard.description,
    source_dashboard_version_id: "dashboard-version-2",
    visibility: "workspace",
  });
  expect(requests[1].body).toEqual({ expected_revision: 3 });
});

it("retains unsaved editor state and reuses the draft when template publication retries", async () => {
  let createAttempts = 0;
  let publishAttempts = 0;
  let queryClient: QueryClient | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith("/dashboard-templates")) {
        createAttempts += 1;
        return jsonResponse(
          templateDetail({ revision: 3, status: "draft" }),
          201,
        );
      }
      if (url.endsWith("/dashboard-templates/template-sales/publish")) {
        publishAttempts += 1;
        if (publishAttempts > 1) {
          return jsonResponse(
            templateDetail({ revision: 4, status: "published" }),
          );
        }
        return jsonResponse(
          { detail: { message: "模板发布失败", action: "稍后重试" } },
          500,
        );
      }
      return jsonResponse(toWire(dashboard));
    }),
  );
  const user = userEvent.setup();
  renderPage((client) => {
    queryClient = client;
    client.setQueryData(dashboardQueryKeys.templates(), {
      items: [],
      total: 0,
      offset: 0,
      limit: 50,
    });
  });

  await user.click(
    await screen.findByRole("button", { name: "添加柱状图组件" }),
  );
  await user.click(
    screen.getByRole("button", { name: "发布当前已保存版本为模板" }),
  );
  let dialog = await screen.findByRole("dialog", {
    name: "发布当前版本为模板",
  });
  await user.click(within(dialog).getByRole("button", { name: /发\s*布/ }));

  expect(await within(dialog).findByText("模板发布失败")).toBeInTheDocument();
  expect(screen.getByDisplayValue("柱状图")).toBeInTheDocument();
  expect(screen.getByText("有未保存更改")).toBeInTheDocument();
  await user.click(within(dialog).getByRole("button", { name: /取\s*消/ }));
  await user.click(
    screen.getByRole("button", { name: "发布当前已保存版本为模板" }),
  );
  dialog = await screen.findByRole("dialog", {
    name: "发布当前版本为模板",
  });
  await user.click(within(dialog).getByRole("button", { name: /发\s*布/ }));

  expect(await screen.findByText("模板已发布")).toBeInTheDocument();
  expect(createAttempts).toBe(1);
  expect(publishAttempts).toBe(2);
  expect(screen.getByDisplayValue("柱状图")).toBeInTheDocument();
  await waitFor(() =>
    expect(
      queryClient?.getQueryState(dashboardQueryKeys.templates())?.isInvalidated,
    ).toBe(true),
  );
});

it("activates the dashboard with the current revision", async () => {
  let activateBody: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).endsWith("/dashboards/dashboard-sales/activate")) {
        activateBody = JSON.parse(String(init?.body));
        return jsonResponse(
          toWire({ ...dashboard, status: "active", revision: 8 }),
        );
      }
      return jsonResponse(toWire(dashboard));
    }),
  );
  const user = userEvent.setup();
  renderPage();

  await user.click(await screen.findByRole("button", { name: "激活仪表盘" }));

  expect(await screen.findByText("仪表盘已激活")).toBeInTheDocument();
  expect(activateBody).toEqual({ expected_revision: 7 });
  expect(
    screen.queryByRole("button", { name: "激活仪表盘" }),
  ).not.toBeInTheDocument();
});

it("keeps the local draft on save conflict until reload is explicitly confirmed", async () => {
  let dashboardReads = 0;
  let saveAttempts = 0;
  const latest = {
    ...dashboard,
    revision: 8,
    current_version: 3,
    current_version_id: "dashboard-version-3",
    pages: [{ ...dashboard.pages[0], title: "服务端最新页面" }],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === "POST") {
        saveAttempts += 1;
        return jsonResponse(
          {
            detail: {
              code: "dashboard_revision_conflict",
              message: "仪表盘已被其他用户更新",
              action: "重新加载最新版本",
            },
          },
          409,
        );
      }
      if (String(input).endsWith("/dashboards/dashboard-sales")) {
        dashboardReads += 1;
        return jsonResponse(toWire(dashboardReads === 1 ? dashboard : latest));
      }
      return jsonResponse(toWire(dashboard));
    }),
  );
  const user = userEvent.setup();
  renderPage();

  await user.click(
    await screen.findByRole("button", { name: "添加柱状图组件" }),
  );
  await user.click(screen.getByRole("button", { name: /保存新版本/ }));
  expect(await screen.findByText("仪表盘保存失败")).toBeInTheDocument();
  expect(screen.getByDisplayValue("柱状图")).toBeInTheDocument();
  expect(saveAttempts).toBe(1);
  expect(dashboardReads).toBe(1);

  await user.click(
    screen.getByRole("button", { name: /放弃本地更改并重新加载/ }),
  );
  const dialog = await screen.findByRole("dialog", { name: "放弃本地更改" });
  expect(screen.getByDisplayValue("柱状图")).toBeInTheDocument();
  await user.click(
    within(dialog).getByRole("button", { name: /放弃并重新加载/ }),
  );

  expect(
    await screen.findByRole("button", { name: "服务端最新页面" }),
  ).toBeInTheDocument();
  expect(screen.queryByDisplayValue("柱状图")).not.toBeInTheDocument();
  expect(screen.getByText("已重新加载最新版本")).toBeInTheDocument();
  expect(saveAttempts).toBe(1);
  expect(dashboardReads).toBe(2);
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

it("keeps mobile preview filters out of the saved desktop contract", async () => {
  let mobile = true;
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      get matches() {
        return mobile && query === "(max-width: 768px)";
      },
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(
        (_type: string, listener: (event: MediaQueryListEvent) => void) => {
          listeners.add(listener);
        },
      ),
      removeEventListener: vi.fn(
        (_type: string, listener: (event: MediaQueryListEvent) => void) => {
          listeners.delete(listener);
        },
      ),
      dispatchEvent: vi.fn(() => false),
    })),
  );
  const config = defaultChartConfig("kpi");
  config.query.dataset_id = "00000000-0000-0000-0000-000000000001";
  config.query.measures[0] = {
    kind: "field",
    field_id: "00000000-0000-0000-0000-000000000002",
    aggregate: "sum",
    slot_key: "value",
  };
  const mobileDashboard: DashboardDetail = {
    ...dashboard,
    pages: [
      {
        ...dashboard.pages[0],
        components: [{ ...dashboard.pages[0].components[0], config }],
      },
    ],
  };
  let saveBody: Record<string, unknown> | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/dashboard-chart-queries")) return chartResponse();
      if (url.includes("/datasets/")) {
        return jsonResponse({
          id: config.query.dataset_id,
          name: "销售数据集",
          status: "active",
          fields: [
            {
              id: "00000000-0000-0000-0000-000000000003",
              label: "订单日期",
              role: "dimension",
              data_type: "date",
              hidden: false,
            },
          ],
        });
      }
      if (init?.method === "POST") {
        saveBody = JSON.parse(String(init.body)) as Record<string, unknown>;
        return jsonResponse(
          toWire({ ...mobileDashboard, revision: 8, current_version: 3 }),
        );
      }
      return jsonResponse(toWire(mobileDashboard));
    }),
  );
  const user = userEvent.setup();
  renderPage();

  expect(await screen.findByText("移动端为只读模式")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /筛选/ }));
  await user.click(screen.getAllByText("相对日期")[0]);
  fireEvent.mouseDown(screen.getByLabelText("全局筛选字段"));
  fireEvent.click(screen.getAllByText("订单日期").at(-1)!);
  expect(screen.getByText("当前为已保存版本")).toBeInTheDocument();

  mobile = false;
  act(() => {
    for (const listener of listeners) {
      listener({
        matches: false,
        media: "(max-width: 768px)",
      } as MediaQueryListEvent);
    }
  });
  await user.click(screen.getByRole("button", { name: /保存新版本/ }));
  await waitFor(() => expect(saveBody).toBeDefined());
  expect(saveBody).toMatchObject({ global_filter: null });
});

it("labels archived dashboards without presenting them as drafts", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      jsonResponse(toWire({ ...dashboard, status: "archived" })),
    ),
  );

  renderPage();

  expect(await screen.findByText("已归档")).toBeInTheDocument();
  expect(screen.queryByText("草稿")).not.toBeInTheDocument();
});

it("lets a read-only viewer apply global and page filters without saving", async () => {
  const config = defaultChartConfig("kpi");
  config.query.dataset_id = "00000000-0000-0000-0000-000000000001";
  config.query.measures[0] = {
    kind: "field",
    field_id: "00000000-0000-0000-0000-000000000002",
    aggregate: "sum",
    slot_key: "value",
  };
  const readonlyDashboard: DashboardDetail = {
    ...dashboard,
    capabilities: ["view"],
    pages: [
      {
        ...dashboard.pages[0],
        components: [{ ...dashboard.pages[0].components[0], config }],
      },
    ],
  };
  const queryBodies: Array<Record<string, unknown>> = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).endsWith("/dashboard-chart-queries")) {
        queryBodies.push(
          JSON.parse(String(init?.body)) as Record<string, unknown>,
        );
        return chartResponse();
      }
      if (String(input).includes("/datasets/")) {
        return jsonResponse({
          id: config.query.dataset_id,
          name: "销售数据集",
          status: "active",
          fields: [
            {
              id: "00000000-0000-0000-0000-000000000003",
              label: "订单日期",
              role: "dimension",
              data_type: "date",
              hidden: false,
            },
            {
              id: "00000000-0000-0000-0000-000000000004",
              label: "支付时间",
              role: "dimension",
              data_type: "datetime",
              hidden: false,
            },
          ],
        });
      }
      return jsonResponse(toWire(readonlyDashboard));
    }),
  );
  const user = userEvent.setup();
  renderPage();

  expect(await screen.findByText("当前仪表盘为只读")).toBeInTheDocument();
  await waitFor(() => expect(queryBodies).toHaveLength(1));
  expect(queryBodies[0]).toMatchObject({
    dashboard_version_id: "dashboard-version-2",
    runtime_filters: {
      global_filter: null,
      page_filter: null,
      component_filter: null,
    },
  });

  await user.click(screen.getByRole("button", { name: /筛选/ }));
  await user.click(screen.getAllByText("相对日期")[0]);
  fireEvent.mouseDown(screen.getByLabelText("全局筛选字段"));
  fireEvent.click(screen.getAllByText("订单日期").at(-1)!);
  await user.click(screen.getAllByText("相对日期")[1]);
  fireEvent.mouseDown(screen.getByLabelText("页面筛选字段"));
  fireEvent.click(screen.getAllByText("支付时间").at(-1)!);

  await waitFor(() =>
    expect(queryBodies.at(-1)).toMatchObject({
      dashboard_version_id: "dashboard-version-2",
      runtime_filters: {
        global_filter: {
          kind: "relative_date",
          field_id: "00000000-0000-0000-0000-000000000003",
          period: "last_30_days",
        },
        page_filter: {
          kind: "relative_date",
          field_id: "00000000-0000-0000-0000-000000000004",
          period: "last_30_days",
        },
        component_filter: null,
      },
    }),
  );
  expect(
    screen.queryByRole("button", { name: /保存新版本/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByText("当前为已保存版本")).toBeInTheDocument();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function chartResponse() {
  return jsonResponse({
    request_id: "request-1",
    component_id: "component-revenue",
    columns: [
      {
        slot_key: "value",
        query_alias: "value_1",
        resource_kind: "field",
        resource_id: "00000000-0000-0000-0000-000000000002",
        aggregate: "sum",
        label: "总营收",
        data_type: "decimal",
        unit: null,
      },
    ],
    rows: [{ value_1: "128.5" }],
    truncated: false,
    elapsed_ms: 8.5,
    dataset_version: 3,
    metric_version_ids: [],
    source_batch_ids: ["batch-1"],
    resolved_filters: [],
    warnings: [],
  });
}

function templateDetail({
  revision,
  status,
}: {
  revision: number;
  status: "draft" | "published";
}) {
  return {
    id: "template-sales",
    name: "销售经营模板",
    description: dashboard.description,
    status,
    visibility: "workspace",
    owner_name: dashboard.owner_name,
    revision,
    version_id: "template-version-3",
    source_dashboard_version_id: dashboard.current_version_id,
    updated_at: dashboard.updated_at,
  };
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
