import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import { TestProviders } from "../../../test/TestProviders";
import { DashboardCreatePage } from "./DashboardCreatePage";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPage(path = "/dashboards/new") {
  return render(
    <TestProviders initialEntries={[path]}>
      <Routes>
        <Route path="/dashboards/new" element={<DashboardCreatePage />} />
        <Route
          path="/dashboards/:dashboardId"
          element={<div>仪表盘编辑器已打开</div>}
        />
      </Routes>
    </TestProviders>,
  );
}

it("creates a blank dashboard without a template mode field", async () => {
  let requestBody: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      requestBody =
        typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      return jsonResponse(dashboardWire("dashboard-new"), 201);
    }),
  );
  const user = userEvent.setup();
  renderPage();

  await user.type(screen.getByLabelText("仪表盘名称"), "经营总览");
  await user.type(screen.getByLabelText("仪表盘说明"), "统一经营视图");
  await user.click(screen.getByRole("button", { name: /创建并进入编辑器/ }));

  expect(await screen.findByText("仪表盘编辑器已打开")).toBeInTheDocument();
  expect(requestBody).toEqual({
    name: "经营总览",
    description: "统一经营视图",
  });
});

it("creates an independent dashboard from a published template version", async () => {
  let createBody: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/dashboard-templates?")) {
        return jsonResponse({
          items: [
            {
              id: "template-sales",
              name: "销售驾驶舱",
              description: "销售经营标准布局",
              latest_version_id: "template-version-3",
              page_count: 2,
              owner_name: "数据管理员",
              updated_at: "2026-07-19T08:00:00Z",
            },
          ],
          total: 1,
          offset: 0,
          limit: 50,
        });
      }
      createBody =
        typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      return jsonResponse(dashboardWire("dashboard-from-template"), 201);
    }),
  );
  const user = userEvent.setup();
  renderPage("/dashboards/new?source=template");

  await user.type(screen.getByLabelText("仪表盘名称"), "区域销售看板");
  await user.click(await screen.findByRole("button", { name: /销售驾驶舱/ }));
  await user.click(screen.getByRole("button", { name: /创建并进入编辑器/ }));

  await waitFor(() =>
    expect(createBody).toEqual({
      name: "区域销售看板",
      template_version_id: "template-version-3",
    }),
  );
  expect(await screen.findByText("仪表盘编辑器已打开")).toBeInTheDocument();
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function dashboardWire(id: string) {
  return {
    id,
    name: "新仪表盘",
    description: null,
    status: "draft",
    owner_name: "数据管理员",
    updated_at: "2026-07-19T08:00:00Z",
    current_version: 1,
    page_count: 1,
    capabilities: ["view", "edit"],
    revision: 1,
    current_version_id: `${id}-version-1`,
    pages: [{ page_id: `${id}-page-1`, title: "页面 1", ordinal: 0 }],
    components: [],
    layouts: [],
  };
}
