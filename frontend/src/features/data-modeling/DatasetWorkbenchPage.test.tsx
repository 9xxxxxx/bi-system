import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";

import { TestProviders } from "../../test/TestProviders";
import { DatasetWorkbenchPage } from "./DatasetWorkbenchPage";

afterEach(() => {
  vi.unstubAllGlobals();
});

const source = {
  id: "source-sales",
  name: "销售明细",
  status: "active",
  active_row_count: 1800,
  latest_active_batch_id: "batch-1",
  fields: [
    {
      id: "column-city",
      display_name: "城市",
      data_type: "string",
      nullable: false,
    },
    {
      id: "column-amount",
      display_name: "销售金额",
      data_type: "decimal",
      nullable: false,
    },
  ],
};

const dimensionSource = {
  id: "source-city",
  name: "城市维度",
  status: "active",
  active_row_count: 40,
  latest_active_batch_id: "batch-city",
  fields: [
    {
      id: "column-dimension-city",
      display_name: "城市编码",
      data_type: "string",
      nullable: false,
    },
    {
      id: "column-city-name",
      display_name: "城市名称",
      data_type: "string",
      nullable: false,
    },
  ],
};

const dataset = {
  id: "dataset-sales",
  semantic_model_id: "model-sales",
  series_id: "series-sales",
  version: 1,
  name: "销售经营数据集",
  description: "统一销售分析口径",
  status: "draft",
  source_count: 1,
  field_count: 2,
  metric_count: 0,
  owner_name: "数据管理员",
  updated_at: "2026-07-17T08:00:00Z",
  fields: [
    {
      id: "field-city",
      model_source_id: "model-source-sales",
      source_column_id: "column-city",
      name: "field_1",
      label: "城市",
      field_kind: "source",
      role: "dimension",
      data_type: "string",
      hidden: false,
      ordinal: 0,
    },
    {
      id: "field-amount",
      model_source_id: "model-source-sales",
      source_column_id: "column-amount",
      name: "field_2",
      label: "销售金额",
      field_kind: "source",
      role: "measure",
      data_type: "decimal",
      hidden: false,
      ordinal: 1,
    },
  ],
};

function renderWorkbench(path: string) {
  return render(
    <TestProviders initialEntries={[path]}>
      <Routes>
        <Route path="/datasets/:datasetId" element={<DatasetWorkbenchPage />} />
      </Routes>
    </TestProviders>,
  );
}

it("creates a single-source model before saving the dataset draft", async () => {
  const requests: Array<{ url: string; method: string; body?: unknown }> = [];
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
      if (url.endsWith("/data-sources")) {
        return new Response(JSON.stringify([source]), { status: 200 });
      }
      if (url.endsWith("/semantic-models") && method === "POST") {
        return new Response(
          JSON.stringify({
            id: "model-sales",
            series_id: "model-series-sales",
            name: "销售经营数据集模型",
            version: 1,
            description: "统一销售分析口径",
            status: "draft",
            sources: [
              {
                id: "model-source-sales",
                target_id: source.id,
                alias: "fact",
                role: "fact",
                ordinal: 0,
              },
            ],
            joins: [],
          }),
          { status: 201 },
        );
      }
      if (url.endsWith("/datasets") && method === "POST") {
        return new Response(JSON.stringify(dataset), { status: 201 });
      }
      if (url.endsWith("/datasets/dataset-sales")) {
        return new Response(JSON.stringify(dataset), { status: 200 });
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    }),
  );
  renderWorkbench("/datasets/new");

  fireEvent.change(await screen.findByLabelText("数据集名称"), {
    target: { value: "销售经营数据集" },
  });
  fireEvent.change(screen.getByLabelText("数据集描述"), {
    target: { value: "统一销售分析口径" },
  });
  const saveButton = screen.getByRole("button", { name: /保存草稿/ });
  await waitFor(() => expect(saveButton).toBeEnabled());
  fireEvent.click(saveButton);

  expect(
    await screen.findByRole("heading", { name: "销售经营数据集" }),
  ).toBeInTheDocument();
  const modelRequest = requests.find(
    ({ url, method }) => url.endsWith("/semantic-models") && method === "POST",
  );
  const datasetRequest = requests.find(
    ({ url, method }) => url.endsWith("/datasets") && method === "POST",
  );
  expect(modelRequest?.body).toMatchObject({
    name: "销售经营数据集模型",
    sources: [{ target_id: "source-sales", alias: "fact", role: "fact" }],
    joins: [],
  });
  expect(datasetRequest?.body).toMatchObject({
    semantic_model_id: "model-sales",
    name: "销售经营数据集",
    fields: [
      {
        model_source_id: "model-source-sales",
        source_column_id: "column-city",
        role: "dimension",
      },
      {
        model_source_id: "model-source-sales",
        source_column_id: "column-amount",
        role: "measure",
      },
    ],
  });
  expect(
    requests.findIndex(({ url }) => url.endsWith("/semantic-models")),
  ).toBeLessThan(
    requests.findIndex(
      ({ url, method }) => url.endsWith("/datasets") && method === "POST",
    ),
  );
}, 10_000);

it("shows only active sources and an actionable empty state", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify([{ ...source, status: "inactive" }]), {
          status: 200,
        }),
    ),
  );

  renderWorkbench("/datasets/new");

  expect(await screen.findByText("没有可用数据源")).toBeInTheDocument();
  expect(screen.getByText("导入数据后即可开始建模")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /保存草稿/ })).toBeDisabled();
});

it("builds a star model and activates model and dataset in order", async () => {
  const requests: Array<{ url: string; method: string; body?: unknown }> = [];
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
      if (url.endsWith("/data-sources")) {
        return new Response(JSON.stringify([source, dimensionSource]), {
          status: 200,
        });
      }
      if (url.endsWith("/semantic-models") && method === "POST") {
        return new Response(
          JSON.stringify({
            id: "model-star",
            series_id: "model-series-star",
            name: "星型销售模型",
            version: 1,
            description: null,
            status: "draft",
            sources: [
              {
                id: "model-source-fact",
                target_id: source.id,
                alias: "fact",
                role: "fact",
                ordinal: 0,
              },
              {
                id: "model-source-city",
                target_id: dimensionSource.id,
                alias: "dim_1",
                role: "dimension",
                ordinal: 1,
              },
            ],
            joins: [],
          }),
          { status: 201 },
        );
      }
      if (url.endsWith("/semantic-models/model-star/activate")) {
        return new Response("{}", { status: 200 });
      }
      if (url.endsWith("/datasets") && method === "POST") {
        return new Response(
          JSON.stringify({ ...dataset, id: "dataset-star" }),
          { status: 201 },
        );
      }
      if (url.endsWith("/datasets/dataset-star/activate")) {
        return new Response(
          JSON.stringify({ ...dataset, id: "dataset-star", status: "active" }),
          { status: 200 },
        );
      }
      if (url.endsWith("/datasets/dataset-star")) {
        return new Response(
          JSON.stringify({ ...dataset, id: "dataset-star", status: "active" }),
          { status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${method} ${url}`);
    }),
  );
  renderWorkbench("/datasets/new");

  fireEvent.click(await screen.findByRole("checkbox", { name: "城市维度" }));
  fireEvent.mouseDown(screen.getByLabelText("城市维度事实键"));
  fireEvent.click(await screen.findByText("城市 · string"));
  fireEvent.mouseDown(screen.getByLabelText("城市维度维度键"));
  fireEvent.click(await screen.findByText("城市编码 · string"));
  fireEvent.change(screen.getByLabelText("数据集名称"), {
    target: { value: "星型销售" },
  });
  const activateButton = screen.getByRole("button", { name: /保存并激活/ });
  await waitFor(() => expect(activateButton).toBeEnabled());
  fireEvent.click(activateButton);

  await waitFor(
    () =>
      expect(requests.filter(({ method }) => method === "POST")).toHaveLength(
        4,
      ),
    { timeout: 10_000 },
  );
  expect(
    await screen.findByRole(
      "heading",
      { name: "销售经营数据集" },
      { timeout: 10_000 },
    ),
  ).toBeInTheDocument();
  const modelRequest = requests.find(
    ({ url, method }) => url.endsWith("/semantic-models") && method === "POST",
  );
  const datasetRequest = requests.find(
    ({ url, method }) => url.endsWith("/datasets") && method === "POST",
  );
  expect(modelRequest?.body).toMatchObject({
    sources: [
      { target_id: "source-sales", alias: "fact", role: "fact" },
      { target_id: "source-city", alias: "dim_1", role: "dimension" },
    ],
    joins: [
      {
        left_source: "fact",
        right_source: "dim_1",
        join_type: "left",
        cardinality: "many_to_one",
        keys: [
          {
            left_column_id: "column-city",
            right_column_id: "column-dimension-city",
          },
        ],
      },
    ],
  });
  if (!datasetRequest) throw new Error("Dataset creation request was not sent");
  expect((datasetRequest.body as { fields: unknown[] }).fields).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        model_source_id: "model-source-city",
        source_column_id: "column-city-name",
      }),
    ]),
  );
  const orderedPaths = requests
    .filter(({ method }) => method === "POST")
    .map(({ url }) => new URL(url).pathname);
  expect(orderedPaths).toEqual([
    "/api/v1/semantic-models",
    "/api/v1/semantic-models/model-star/activate",
    "/api/v1/datasets",
    "/api/v1/datasets/dataset-star/activate",
  ]);
}, 20_000);

it("activates the related model before an existing draft dataset", async () => {
  const activationOrder: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith("/datasets/dataset-sales")) {
        return new Response(JSON.stringify(dataset), { status: 200 });
      }
      if (url.endsWith("/semantic-models/model-sales/activate")) {
        activationOrder.push("model");
        return new Response("{}", { status: 200 });
      }
      if (url.endsWith("/datasets/dataset-sales/activate")) {
        activationOrder.push("dataset");
        return new Response(JSON.stringify({ ...dataset, status: "active" }), {
          status: 200,
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const user = userEvent.setup();
  renderWorkbench("/datasets/dataset-sales");

  await user.click(await screen.findByRole("button", { name: /激活数据集/ }));

  expect(await screen.findByText("可用")).toBeInTheDocument();
  expect(activationOrder).toEqual(["model", "dataset"]);
  expect(
    screen.queryByRole("button", { name: /激活数据集/ }),
  ).not.toBeInTheDocument();
});

it("queries selected fields and renders rows with execution metadata", async () => {
  let queryBody: unknown;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/datasets/dataset-sales")) {
        return new Response(JSON.stringify(dataset), { status: 200 });
      }
      if (url.endsWith("/dataset-queries")) {
        queryBody =
          typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
        return new Response(
          JSON.stringify({
            columns: ["field_1", "field_2"],
            rows: [{ field_1: "北京", field_2: 128.5 }],
            truncated: true,
            elapsed_ms: 12.34,
            dataset_version: 1,
            source_batch_ids: ["batch-1", "batch-2"],
          }),
          { status: 200 },
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    }),
  );
  const user = userEvent.setup();
  renderWorkbench("/datasets/dataset-sales");

  await user.click(await screen.findByRole("button", { name: /运行预览/ }));

  expect(await screen.findByText("北京")).toBeInTheDocument();
  expect(screen.getByText("128.5")).toBeInTheDocument();
  expect(screen.getByText("结果已截断")).toBeInTheDocument();
  expect(screen.getByText("耗时 12.3 ms")).toBeInTheDocument();
  expect(screen.getByText("2 个来源批次")).toBeInTheDocument();
  expect(queryBody).toEqual({
    dataset_id: "dataset-sales",
    selections: [
      { field_id: "field-city", output_name: "field_1" },
      { field_id: "field-amount", output_name: "field_2" },
    ],
    limit: 100,
  });
});

it("renders empty query results and exposes recoverable query errors", async () => {
  let queryCount = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith("/datasets/dataset-sales")) {
        return new Response(JSON.stringify(dataset), { status: 200 });
      }
      queryCount += 1;
      if (queryCount === 1) {
        return new Response(
          JSON.stringify({
            columns: ["field_1", "field_2"],
            rows: [],
            truncated: false,
            elapsed_ms: 2,
            dataset_version: 1,
            source_batch_ids: [],
          }),
          { status: 200 },
        );
      }
      return new Response(
        JSON.stringify({
          detail: {
            message: "数据集查询暂不可用",
            action: "检查字段权限后重试",
          },
        }),
        { status: 422 },
      );
    }),
  );
  const user = userEvent.setup();
  renderWorkbench("/datasets/dataset-sales");
  const button = await screen.findByRole("button", { name: /运行预览/ });

  await user.click(button);
  expect(await screen.findByText("当前条件没有返回数据")).toBeInTheDocument();
  await user.click(button);
  expect(await screen.findByText("查询预览失败")).toBeInTheDocument();
  expect(screen.getByText(/检查字段权限后重试/)).toBeInTheDocument();
});

it("renders a recoverable error when the dataset detail fails", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ detail: { message: "数据集读取失败" } }),
          {
            status: 500,
          },
        ),
    ),
  );

  renderWorkbench("/datasets/dataset-sales");

  expect(await screen.findByText("数据集加载失败")).toBeInTheDocument();
  expect(screen.getByText("数据集读取失败")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByText("销售经营数据集")).not.toBeInTheDocument(),
  );
});
