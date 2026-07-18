import { afterEach, expect, it, vi } from "vitest";

import { getDashboard, saveDashboardVersion } from "./api";
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
