import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TestProviders } from "../../test/TestProviders";
import { GovernancePage } from "./GovernancePage";

const dataset = {
  id: "dataset-1",
  semantic_model_id: "model-1",
  series_id: "dataset-series-1",
  name: "销售数据集",
  description: null,
  status: "active",
  source_count: 1,
  field_count: 2,
  metric_count: 1,
  owner_name: "数据管理员",
  updated_at: "2026-07-17T08:00:00Z",
  version: 1,
  fields: [
    {
      id: "field-region",
      model_source_id: "source-1",
      source_column_id: "column-region",
      name: "region",
      label: "区域",
      field_kind: "source",
      role: "dimension",
      data_type: "string",
      hidden: false,
      ordinal: 0,
    },
    {
      id: "field-amount",
      model_source_id: "source-1",
      source_column_id: "column-amount",
      name: "amount",
      label: "销售金额",
      field_kind: "source",
      role: "measure",
      data_type: "decimal",
      hidden: false,
      ordinal: 1,
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

it("renders the public metric catalog and creation entry", async () => {
  vi.stubGlobal("fetch", vi.fn(handleGovernanceRequest));

  render(
    <TestProviders>
      <GovernancePage />
    </TestProviders>,
  );

  expect(await screen.findByText("销售额")).toBeInTheDocument();
  expect(screen.getByText("sales_amount · v1")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /新建指标/ })).toBeInTheDocument();
  expect(screen.getByLabelText("规则发布流程")).toHaveTextContent(
    "定义绑定生效",
  );
}, 15_000);

async function handleGovernanceRequest(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  const url = new URL(String(input));
  if (url.pathname.endsWith("/metrics")) {
    return jsonResponse({
      items: [
        {
          id: "metric-1",
          series_id: "metric-series-1",
          dataset_id: dataset.id,
          dataset_name: dataset.name,
          code: "sales_amount",
          name: "销售额",
          version: 1,
          description: "统一销售金额口径",
          result_type: "decimal",
          unit: "元",
          status: "active",
          owner_name: "数据管理员",
          updated_at: "2026-07-17T08:00:00Z",
        },
      ],
      total: 1,
      offset: 0,
      limit: 100,
    });
  }
  if (url.pathname.endsWith("/datasets") && !init?.method) {
    return jsonResponse({ items: [dataset], total: 1, offset: 0, limit: 100 });
  }
  if (url.pathname.endsWith(`/datasets/${dataset.id}`))
    return jsonResponse(dataset);
  if (url.pathname.endsWith("/identity/users")) {
    return jsonResponse([
      { id: "user-1", username: "analyst", display_name: "数据分析员" },
    ]);
  }
  if (url.pathname.endsWith("/identity/roles")) return jsonResponse([]);
  if (url.pathname.endsWith("/row-policies") && !init?.method) {
    return jsonResponse({ items: [], total: 0, offset: 0, limit: 100 });
  }
  if (url.pathname.endsWith("/row-policies") && init?.method === "POST") {
    return jsonResponse(policy("draft"), 201);
  }
  if (url.pathname.endsWith("/row-policies/policy-1/bindings")) {
    return jsonResponse({ ...policy("draft"), user_ids: ["user-1"] });
  }
  if (url.pathname.endsWith("/row-policies/policy-1/activate")) {
    return jsonResponse({ ...policy("active"), user_ids: ["user-1"] });
  }
  return jsonResponse({ detail: "Not found" }, 404);
}

function policy(status: "draft" | "active") {
  return {
    id: "policy-1",
    dataset_id: dataset.id,
    name: "华东区域访问",
    version: 1,
    effect: "allow",
    status,
    user_ids: [],
    role_ids: [],
    updated_at: "2026-07-17T08:00:00Z",
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
