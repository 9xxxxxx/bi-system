import type { DashboardComponentType } from "../types";

export type AggregateFunction =
  "sum" | "avg" | "count" | "count_distinct" | "min" | "max";
export type TimeGrain = "day" | "week" | "month" | "quarter" | "year";

export interface ChartDimensionSlot {
  field_id: string;
  slot_key: string;
  time_grain: TimeGrain | null;
}

export interface ChartFieldMeasure {
  kind: "field";
  field_id: string;
  aggregate: AggregateFunction;
  slot_key: string;
}

export interface ChartMetricMeasure {
  kind: "metric";
  metric_version_id: string;
  slot_key: string;
}

export type ChartMeasure = ChartFieldMeasure | ChartMetricMeasure;

export type ChartSort =
  | {
      kind: "field";
      field_id: string;
      aggregate: AggregateFunction | null;
      direction: "asc" | "desc";
    }
  | {
      kind: "metric";
      metric_version_id: string;
      direction: "asc" | "desc";
    };

export interface ChartQuerySpec {
  dataset_id: string;
  dimensions: ChartDimensionSlot[];
  series_dimension: {
    field_id: string;
    slot_key: string;
    max_series: number;
  } | null;
  measures: ChartMeasure[];
  sort: ChartSort[];
  top_n: number | null;
  query_limit: number;
}

export type ComparisonOperator = "eq" | "ne" | "gt" | "gte" | "lt" | "lte";

export type AtomicFilterExpression =
  | {
      kind: "comparison";
      field_id: string;
      operator: ComparisonOperator;
      value: string | number | boolean;
    }
  | {
      kind: "set";
      field_id: string;
      operator: "in" | "not_in";
      values: Array<string | number | boolean>;
    }
  | { kind: "null"; field_id: string; is_null: boolean }
  | {
      kind: "text";
      field_id: string;
      operator: "contains" | "starts_with" | "ends_with";
      value: string;
    };

export type FilterExpression =
  | AtomicFilterExpression
  | {
      kind: "logical";
      operator: "and";
      predicates: AtomicFilterExpression[];
    };

export type RelativeDatePreset =
  | "today"
  | "yesterday"
  | "last_7_days"
  | "last_30_days"
  | "this_week"
  | "last_week"
  | "this_month"
  | "last_month"
  | "month_to_date"
  | "year_to_date";

export type DashboardDateFilter =
  | {
      kind: "absolute_date_range";
      field_id: string;
      field_type: "date" | "datetime";
      start: string;
      end: string;
    }
  | {
      kind: "relative_date";
      field_id: string;
      field_type: "date" | "datetime";
      period: RelativeDatePreset;
    };

export type ScopedFilter = FilterExpression | DashboardDateFilter;

export interface ChartPresentation {
  unit: string | null;
  show_legend: boolean;
  show_labels: boolean;
  show_tooltip: boolean;
  theme: "light" | "dark";
}

export interface ChartComponentConfig {
  [key: string]: unknown;
  schema_version: 1;
  query: ChartQuerySpec;
  component_filter: ScopedFilter | null;
  presentation: ChartPresentation;
}

export interface RichTextComponentConfig {
  schema_version: 1;
  blocks: RichTextBlock[];
  content?: string;
}

export type RichTextBlockType = "heading" | "paragraph" | "bullet";
export type RichTextMark = "bold" | "italic";

export interface RichTextBlock {
  type: RichTextBlockType;
  text: string;
  marks: RichTextMark[];
}

export interface ImageComponentConfig {
  schema_version: 1;
  file_id: string;
  alt_text: string;
}

export interface DashboardChartQueryRequest {
  dashboard_id: string;
  dashboard_version_id: string;
  page_id: string;
  component_id: string;
  runtime_filters: {
    global_filter: ScopedFilter | null;
    page_filter: ScopedFilter | null;
    component_filter: ScopedFilter | null;
  };
  preview_component?: {
    component_id: string;
    page_id: string;
    component_type: DashboardComponentType;
    config_version: 1;
    config: Record<string, unknown>;
  };
}

export interface DashboardChartColumn {
  slot_key: string;
  query_alias: string;
  resource_kind: "field" | "metric";
  resource_id: string;
  aggregate: AggregateFunction | null;
  label: string;
  data_type: "string" | "integer" | "decimal" | "boolean" | "date" | "datetime";
  unit: string | null;
}

export interface DashboardChartQueryResponse {
  request_id: string;
  component_id: string;
  columns: DashboardChartColumn[];
  rows: Array<Record<string, unknown>>;
  truncated: boolean;
  elapsed_ms: number;
  dataset_version: number;
  metric_version_ids: string[];
  source_batch_ids: string[];
  resolved_filters: Array<Record<string, unknown>>;
  warnings: Array<{ code: string; message: string }>;
}
