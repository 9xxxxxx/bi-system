import { ClockCircleOutlined, DatabaseOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, Progress, Skeleton, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { lazy, Suspense, useMemo } from "react";

import { ApiError } from "../../../shared/api/client";
import type { DashboardComponent } from "../types";
import { dashboardAssetContentUrl } from "../dashboardAssets";
import { buildChartModel, usesCanvas } from "./chartModel";
import {
  hasRunnableQuery,
  isChartComponentConfig,
  isQueryComponentType,
} from "./config";
import { useDashboardChartQuery } from "./useChartQuery";
import { RichTextBlocks } from "./richText";
import type {
  ChartComponentConfig,
  DashboardChartQueryRequest,
  DashboardChartQueryResponse,
  ImageComponentConfig,
  RichTextComponentConfig,
  ScopedFilter,
} from "./types";

const EChartRenderer = lazy(() => import("./EChartRenderer"));

function chartError(error: unknown): { title: string; description: string } {
  if (error instanceof ApiError) {
    if (error.status === 403)
      return {
        title: "无权查询图表数据",
        description: error.action || error.message,
      };
    if (error.status === 504 || error.code === "dataset_query_timeout")
      return {
        title: "图表查询超时",
        description: error.action || "请缩小时间范围后重试",
      };
    return {
      title: "图表查询失败",
      description: [error.message, error.action].filter(Boolean).join("；"),
    };
  }
  return {
    title: "图表查询失败",
    description: error instanceof Error ? error.message : "请稍后重试",
  };
}

function displayValue(
  value: unknown,
  unit: string | null,
  dataType?: DashboardChartQueryResponse["columns"][number]["data_type"],
): string {
  if (value === null || value === undefined) return "-";
  if (dataType === "decimal" && typeof value === "string") {
    return unit ? `${value} ${unit}` : value;
  }
  const numeric = typeof value === "number" ? value : Number(value);
  const text = Number.isFinite(numeric)
    ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(
        numeric,
      )
    : String(value);
  return unit ? `${text} ${unit}` : text;
}

function QueryEvidence({
  response,
}: {
  response: DashboardChartQueryResponse;
}) {
  return (
    <details className="dashboard-query-evidence">
      <summary>
        <ClockCircleOutlined /> {response.elapsed_ms.toFixed(1)} ms
        <span>
          <DatabaseOutlined /> 数据集 v{response.dataset_version}
        </span>
        <span>{response.source_batch_ids.length} 个来源批次</span>
      </summary>
      <dl>
        <dt>Dataset version</dt>
        <dd>{response.dataset_version}</dd>
        <dt>Metric version IDs</dt>
        <dd>{response.metric_version_ids.join(", ") || "无"}</dd>
        <dt>Source batch IDs</dt>
        <dd>{response.source_batch_ids.join(", ") || "无"}</dd>
        <dt>Resolved filters</dt>
        <dd>
          <pre>{JSON.stringify(response.resolved_filters, null, 2)}</pre>
        </dd>
      </dl>
    </details>
  );
}

function AccessibleDataTable({
  response,
}: {
  response: DashboardChartQueryResponse;
}) {
  return (
    <details className="dashboard-accessible-data">
      <summary>查看无障碍数据表</summary>
      <div className="dashboard-accessible-scroll">
        <table>
          <thead>
            <tr>
              {response.columns.map((column) => (
                <th scope="col" key={column.slot_key}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {response.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {response.columns.map((column, columnIndex) =>
                  columnIndex === 0 ? (
                    <th scope="row" key={column.slot_key}>
                      {String(row[column.query_alias] ?? "-")}
                    </th>
                  ) : (
                    <td key={column.slot_key}>
                      {displayValue(
                        row[column.query_alias],
                        column.unit,
                        column.data_type,
                      )}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function LightweightResult({
  component,
  config,
  response,
}: {
  component: DashboardComponent;
  config: ChartComponentConfig;
  response: DashboardChartQueryResponse;
}) {
  const model = buildChartModel(response, config);
  const firstValue = model.series[0]?.values.at(-1) ?? null;
  const firstRawValue = model.series[0]?.rawValues.at(-1) ?? firstValue;
  const firstColumn = response.columns.find(
    (column) => column.slot_key === model.series[0]?.id,
  );
  if (component.component_type === "kpi") {
    return (
      <div className="dashboard-kpi-result">
        <strong>
          {displayValue(
            firstRawValue,
            config.presentation.unit,
            firstColumn?.data_type,
          )}
        </strong>
        <span>{model.series[0]?.label}</span>
      </div>
    );
  }
  if (component.component_type === "trend_indicator") {
    const values = model.series[0]?.values ?? [];
    const previous = values.at(-2);
    const delta =
      previous && firstValue !== null
        ? ((firstValue - previous) / Math.abs(previous)) * 100
        : null;
    return (
      <div className="dashboard-kpi-result">
        <strong>
          {displayValue(
            firstRawValue,
            config.presentation.unit,
            firstColumn?.data_type,
          )}
        </strong>
        <span>
          {delta === null
            ? "暂无环比"
            : `环比 ${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`}
        </span>
      </div>
    );
  }
  if (component.component_type === "target_progress") {
    const actual = model.series[0]?.values[0] ?? 0;
    const target = model.series[1]?.values[0] ?? 0;
    const percent =
      actual !== null && target
        ? Math.max(0, Math.round((actual / target) * 100))
        : 0;
    return (
      <div className="dashboard-progress-result">
        <Progress
          percent={percent}
          status={percent >= 100 ? "success" : "active"}
        />
        <span>
          {displayValue(
            model.series[0]?.rawValues[0] ?? actual,
            config.presentation.unit,
            response.columns.find(
              (column) => column.slot_key === model.series[0]?.id,
            )?.data_type,
          )}{" "}
          /{" "}
          {displayValue(
            model.series[1]?.rawValues[0] ?? target,
            config.presentation.unit,
            response.columns.find(
              (column) => column.slot_key === model.series[1]?.id,
            )?.data_type,
          )}
        </span>
      </div>
    );
  }
  const columns: ColumnsType<Record<string, unknown>> = response.columns.map(
    (column) => ({
      title: column.label,
      dataIndex: column.query_alias,
      key: column.slot_key,
      ellipsis: true,
      render: (value) => displayValue(value, column.unit, column.data_type),
    }),
  );
  return (
    <Table
      size="small"
      rowKey={(_, index) => String(index)}
      columns={columns}
      dataSource={response.rows}
      pagination={false}
      scroll={{ x: true, y: 220 }}
    />
  );
}

function ImageResult({ config }: { config: ImageComponentConfig }) {
  return config.file_id ? (
    <img
      className="dashboard-image-component"
      src={dashboardAssetContentUrl(config.file_id)}
      alt={config.alt_text || "仪表盘图片"}
    />
  ) : (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description="尚未选择图片资源"
    />
  );
}

export function DashboardComponentRenderer({
  dashboardId,
  dashboardVersionId,
  pageId,
  component,
  preview,
  globalFilter,
  pageFilter,
}: {
  dashboardId: string;
  dashboardVersionId: string;
  pageId: string;
  component: DashboardComponent;
  preview: boolean;
  globalFilter: ScopedFilter | null;
  pageFilter: ScopedFilter | null;
}) {
  if (component.component_type === "rich_text")
    return (
      <RichTextBlocks
        config={component.config as unknown as RichTextComponentConfig}
      />
    );
  if (component.component_type === "image")
    return (
      <ImageResult
        config={component.config as unknown as ImageComponentConfig}
      />
    );
  if (
    !isQueryComponentType(component.component_type) ||
    !isChartComponentConfig(component.config)
  ) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="请配置数据集与字段槽"
      />
    );
  }
  return (
    <QueryBackedComponent
      dashboardId={dashboardId}
      dashboardVersionId={dashboardVersionId}
      pageId={pageId}
      component={component}
      config={component.config}
      preview={preview}
      globalFilter={globalFilter}
      pageFilter={pageFilter}
    />
  );
}

function QueryBackedComponent({
  dashboardId,
  dashboardVersionId,
  pageId,
  component,
  config,
  preview,
  globalFilter,
  pageFilter,
}: {
  dashboardId: string;
  dashboardVersionId: string;
  pageId: string;
  component: DashboardComponent;
  config: ChartComponentConfig;
  preview: boolean;
  globalFilter: ScopedFilter | null;
  pageFilter: ScopedFilter | null;
}) {
  const request = useMemo<DashboardChartQueryRequest>(
    () => ({
      dashboard_id: dashboardId,
      dashboard_version_id: dashboardVersionId,
      page_id: pageId,
      component_id: component.id,
      runtime_filters: {
        global_filter: globalFilter,
        page_filter: pageFilter,
        component_filter: config.component_filter,
      },
      ...(preview
        ? {
            preview_component: {
              component_id: component.id,
              page_id: pageId,
              component_type: component.component_type,
              config_version: 1,
              config: {
                ...component.config,
                title: component.title,
                description: component.description,
              },
            },
          }
        : {}),
    }),
    [
      component,
      config.component_filter,
      dashboardId,
      dashboardVersionId,
      globalFilter,
      pageFilter,
      pageId,
      preview,
    ],
  );
  const runnable = hasRunnableQuery(config);
  const query = useDashboardChartQuery(request, runnable);
  if (!runnable)
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="请补全数据集和字段"
      />
    );
  if (query.isLoading)
    return (
      <div className="dashboard-chart-state" aria-label="正在加载图表数据">
        <Skeleton active paragraph={{ rows: 3 }} />
        <Button size="small" onClick={() => void query.cancel()}>
          取消查询
        </Button>
      </div>
    );
  if (query.isError) {
    const error = chartError(query.error);
    return (
      <Alert
        type="error"
        showIcon
        title={error.title}
        description={error.description}
        action={
          <Button size="small" onClick={() => void query.refetch()}>
            重试
          </Button>
        }
      />
    );
  }
  if (!query.data || query.data.rows.length === 0)
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="当前筛选条件下暂无数据"
      />
    );
  const model = buildChartModel(query.data, config);
  return (
    <div className="dashboard-chart-result">
      {query.data.truncated ? (
        <Alert
          type="warning"
          showIcon
          title="结果已截断"
          description="当前仅展示服务端限制内的数据。"
        />
      ) : null}
      {query.data.warnings.map((warning) => (
        <Tag color="warning" key={warning.code}>
          {warning.message}
        </Tag>
      ))}
      {usesCanvas(component.component_type) ? (
        <Suspense
          fallback={
            <div
              className="dashboard-chart-fallback"
              role="status"
              aria-label="正在载入图表模块"
            >
              <Skeleton active paragraph={{ rows: 3 }} />
            </div>
          }
        >
          <EChartRenderer
            componentId={component.id}
            componentType={component.component_type}
            model={model}
            presentation={config.presentation}
          />
        </Suspense>
      ) : (
        <LightweightResult
          component={component}
          config={config}
          response={query.data}
        />
      )}
      <AccessibleDataTable response={query.data} />
      <QueryEvidence response={query.data} />
    </div>
  );
}
