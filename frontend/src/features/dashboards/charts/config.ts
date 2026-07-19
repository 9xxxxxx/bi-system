import type { DashboardComponentType } from "../types";
import type {
  ChartComponentConfig,
  ChartMeasure,
  ChartPresentation,
  ChartQuerySpec,
} from "./types";

const chartTypes = new Set<DashboardComponentType>([
  "kpi",
  "trend_indicator",
  "target_progress",
  "detail_table",
  "ranking_table",
  "bar",
  "horizontal_bar",
  "stacked_bar",
  "line",
  "area",
  "pie",
  "donut",
]);

export const aggregateOptions = [
  { value: "sum", label: "求和" },
  { value: "avg", label: "平均值" },
  { value: "count", label: "计数" },
  { value: "count_distinct", label: "去重计数" },
  { value: "min", label: "最小值" },
  { value: "max", label: "最大值" },
] as const;

export function isQueryComponentType(
  componentType: DashboardComponentType,
): boolean {
  return chartTypes.has(componentType);
}

export function isChartComponentConfig(
  config: Record<string, unknown>,
): config is Record<string, unknown> & ChartComponentConfig {
  const query = config.query;
  return (
    config.schema_version === 1 &&
    typeof query === "object" &&
    query !== null &&
    "dataset_id" in query &&
    typeof query.dataset_id === "string"
  );
}

export function defaultChartConfig(
  componentType: DashboardComponentType,
): ChartComponentConfig {
  const needsDimension = !["kpi", "target_progress"].includes(componentType);
  const measureCount = ["target_progress", "stacked_bar"].includes(
    componentType,
  )
    ? 2
    : 1;
  const measures: ChartMeasure[] = Array.from(
    { length: measureCount },
    (_, index) => ({
      kind: "field",
      field_id: "",
      aggregate: "sum",
      slot_key:
        index === 0
          ? "value"
          : componentType === "target_progress"
            ? "target"
            : `value_${index + 1}`,
    }),
  );
  const query: ChartQuerySpec = {
    dataset_id: "",
    dimensions: needsDimension
      ? [{ field_id: "", slot_key: "dimension", time_grain: null }]
      : [],
    series_dimension: null,
    measures,
    sort: [],
    top_n: null,
    query_limit: ["detail_table", "ranking_table"].includes(componentType)
      ? 500
      : 100,
  };
  const presentation: ChartPresentation = {
    unit: null,
    show_legend: true,
    show_labels: false,
    show_tooltip: true,
    theme: "light",
  };
  return {
    schema_version: 1,
    query,
    component_filter: null,
    presentation,
  };
}

export function hasRunnableQuery(config: ChartComponentConfig): boolean {
  if (!config.query.dataset_id || config.query.measures.length === 0)
    return false;
  if (
    config.query.measures.some((measure) =>
      measure.kind === "field" ? !measure.field_id : !measure.metric_version_id,
    )
  )
    return false;
  return config.query.dimensions.every((dimension) => dimension.field_id);
}
