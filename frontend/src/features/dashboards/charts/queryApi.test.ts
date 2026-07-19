import { afterEach, expect, it, vi } from "vitest";

import { queryDashboardChart } from "./queryApi";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("posts only the frozen dashboard chart request and forwards cancellation", async () => {
  let body: unknown;
  let requestSignal: AbortSignal | null | undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string | URL | Request, init?: RequestInit) => {
      body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      requestSignal = init?.signal;
      return new Response(
        JSON.stringify({
          request_id: "request-1",
          component_id: "component-1",
          columns: [],
          rows: [],
          truncated: false,
          elapsed_ms: 1,
          dataset_version: 1,
          metric_version_ids: [],
          source_batch_ids: [],
          resolved_filters: [],
          warnings: [],
        }),
        { status: 200 },
      );
    }),
  );
  const controller = new AbortController();
  const request = {
    dashboard_id: "dashboard-1",
    dashboard_version_id: "dashboard-version-1",
    page_id: "page-1",
    component_id: "component-1",
    runtime_filters: {
      global_filter: null,
      page_filter: null,
      component_filter: null,
    },
  };

  await queryDashboardChart(request, controller.signal);

  expect(body).toEqual(request);
  expect(requestSignal).toBe(controller.signal);
});
