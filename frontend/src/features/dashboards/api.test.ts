import { afterEach, expect, it, vi } from "vitest";

import { API_BASE_URL } from "../../shared/api/client";
import {
  activateDashboard,
  createDashboardTemplate,
  deleteDashboard,
  getDashboard,
  instantiateDashboardTemplate,
  listDashboards,
  listDashboardTemplates,
  publishDashboardTemplate,
  restoreDashboard,
  saveDashboardVersion,
} from "./api";
import { dashboardQueryKeys } from "./queryKeys";
import type {
  DashboardLayoutProfile,
  SaveDashboardVersionRequest,
} from "./types";

afterEach(() => {
  vi.unstubAllGlobals();
});

const dashboardLayouts: DashboardLayoutProfile[] = [
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
];

const detailWire = {
  id: "dashboard-sales",
  name: "销售经营总览",
  description: null,
  status: "draft",
  owner_name: "数据管理员",
  updated_at: "2026-07-19T08:00:00Z",
  current_version: 1,
  page_count: 1,
  capabilities: ["view", "edit"],
  revision: 4,
  current_version_id: "dashboard-version-1",
  global_filter: { kind: "comparison", operator: "eq" },
  pages: [
    {
      page_id: "page-overview",
      title: "经营概览",
      ordinal: 0,
      page_filter: null,
      components: [
        {
          component_id: "component-revenue",
          page_id: "page-overview",
          component_type: "kpi",
          config_version: 1,
          config: {
            schema_version: 1,
            title: "总营收",
            description: "含税收入",
          },
          ordinal: 0,
        },
      ],
    },
  ],
  layouts: dashboardLayouts,
  permissions: [],
};

it("maps nested wire pages and components into the editor view model", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => jsonResponse(detailWire)),
  );

  const detail = await getDashboard("dashboard-sales");

  expect(detail.pages).toEqual([
    {
      id: "page-overview",
      title: "经营概览",
      ordinal: 0,
      page_filter: null,
      components: [
        {
          id: "component-revenue",
          component_type: "kpi",
          title: "总营收",
          description: "含税收入",
          ordinal: 0,
          config: {
            schema_version: 1,
            title: "总营收",
            description: "含税收入",
          },
        },
      ],
    },
  ]);
});

it("serializes dashboard list options including deleted dashboards", async () => {
  const fetchMock = vi.fn(async () =>
    jsonResponse({ items: [detailWire], total: 1, offset: 10, limit: 20 }),
  );
  vi.stubGlobal("fetch", fetchMock);

  const response = await listDashboards({
    offset: 10,
    limit: 20,
    status: "deleted",
    includeDeleted: true,
  });

  expect(fetchMock).toHaveBeenCalledWith(
    `${API_BASE_URL}/dashboards?offset=10&limit=20&status=deleted&include_deleted=true`,
    expect.objectContaining({ credentials: "include" }),
  );
  expect(response.items[0]?.revision).toBe(4);
});

it("sends lifecycle revisions and maps every dashboard detail response", async () => {
  const fetchMock = vi.fn(async () => jsonResponse(detailWire));
  vi.stubGlobal("fetch", fetchMock);

  const activated = await activateDashboard("dashboard-sales", 4);
  const deleted = await deleteDashboard("dashboard-sales", 5);
  const restored = await restoreDashboard("dashboard-sales", 6);
  const instantiated = await instantiateDashboardTemplate("template-sales", {
    name: "销售模板实例",
    description: "按模板创建",
    template_version_id: "template-version-1",
  });

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    `${API_BASE_URL}/dashboards/dashboard-sales/activate`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_revision: 4 }),
    }),
  );
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    `${API_BASE_URL}/dashboards/dashboard-sales?expected_revision=5`,
    expect.objectContaining({ method: "DELETE" }),
  );
  expect(fetchMock).toHaveBeenNthCalledWith(
    3,
    `${API_BASE_URL}/dashboards/dashboard-sales/restore`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_revision: 6 }),
    }),
  );
  expect(fetchMock).toHaveBeenNthCalledWith(
    4,
    `${API_BASE_URL}/dashboard-templates/template-sales/instantiate`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "销售模板实例",
        description: "按模板创建",
        template_version_id: "template-version-1",
      }),
    }),
  );
  for (const detail of [activated, deleted, restored, instantiated]) {
    expect(detail.pages[0]?.id).toBe("page-overview");
    expect(detail.pages[0]?.components[0]?.id).toBe("component-revenue");
  }
});

it("sends template list, create, and publish contracts", async () => {
  const templateWire = {
    id: "template-sales",
    name: "销售经营模板",
    description: null,
    status: "draft",
    visibility: "workspace",
    owner_name: "数据管理员",
    revision: 1,
    version_id: "template-version-1",
    source_dashboard_version_id: "dashboard-version-1",
    updated_at: "2026-07-19T08:00:00Z",
  };
  const fetchMock = vi.fn(async () => jsonResponse(templateWire));
  vi.stubGlobal("fetch", fetchMock);

  await listDashboardTemplates(5, 10, "draft");
  const created = await createDashboardTemplate({
    name: "销售经营模板",
    description: null,
    source_dashboard_version_id: "dashboard-version-1",
    visibility: "workspace",
  });
  await publishDashboardTemplate("template-sales", 1);

  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    `${API_BASE_URL}/dashboard-templates?offset=5&limit=10&status=draft`,
    expect.objectContaining({ credentials: "include" }),
  );
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    `${API_BASE_URL}/dashboard-templates`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "销售经营模板",
        description: null,
        source_dashboard_version_id: "dashboard-version-1",
        visibility: "workspace",
      }),
    }),
  );
  expect(fetchMock).toHaveBeenNthCalledWith(
    3,
    `${API_BASE_URL}/dashboard-templates/template-sales/publish`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ expected_revision: 1 }),
    }),
  );
  expect(created).toEqual(templateWire);
});

it("keeps list filters and template status in distinct query keys", () => {
  expect(dashboardQueryKeys.list()).not.toEqual(
    dashboardQueryKeys.list({ includeDeleted: true }),
  );
  expect(dashboardQueryKeys.templates("draft")).not.toEqual(
    dashboardQueryKeys.templates("published"),
  );
});

it("flattens editor pages and merges presentation fields into wire config", async () => {
  let body: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      return jsonResponse({ ...detailWire, current_version: 2, revision: 5 });
    }),
  );
  const request: SaveDashboardVersionRequest = {
    base_version: 1,
    expected_revision: 4,
    pages: [
      {
        id: "page-overview",
        title: "经营概览",
        ordinal: 0,
        page_filter: null,
        components: [
          {
            id: "component-revenue",
            component_type: "kpi",
            title: "收入总额",
            description: null,
            ordinal: 0,
            config: { schema_version: 1, state: "placeholder" },
          },
        ],
      },
    ],
    layouts: dashboardLayouts,
  };

  await saveDashboardVersion("dashboard-sales", request);

  expect(body).toEqual({
    base_version: 1,
    expected_revision: 4,
    global_filter: null,
    pages: [
      {
        page_id: "page-overview",
        title: "经营概览",
        ordinal: 0,
        page_filter: null,
      },
    ],
    components: [
      {
        component_id: "component-revenue",
        page_id: "page-overview",
        component_type: "kpi",
        config_version: 1,
        config: {
          schema_version: 1,
          state: "placeholder",
          title: "收入总额",
          description: null,
        },
      },
    ],
    layouts: detailWire.layouts,
  });
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
