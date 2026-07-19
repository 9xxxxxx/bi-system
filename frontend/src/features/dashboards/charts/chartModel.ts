import type { DashboardComponentType } from "../types";
import type {
  ChartComponentConfig,
  DashboardChartColumn,
  DashboardChartQueryResponse,
} from "./types";

export interface ChartSeriesModel {
  id: string;
  label: string;
  values: Array<number | null>;
  rawValues: unknown[];
}

export interface ChartModel {
  categories: string[];
  series: ChartSeriesModel[];
  columns: DashboardChartColumn[];
  tableRows: Array<Array<unknown>>;
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function buildChartModel(
  response: DashboardChartQueryResponse,
  config: ChartComponentConfig,
): ChartModel {
  const columnsBySlot = new Map(
    response.columns.map((column) => [column.slot_key, column]),
  );
  const dimensionColumn = columnsBySlot.get(
    config.query.dimensions[0]?.slot_key ?? "dimension",
  );
  const seriesColumn = config.query.series_dimension
    ? columnsBySlot.get(config.query.series_dimension.slot_key)
    : undefined;
  const measureColumns = config.query.measures
    .map((measure) => columnsBySlot.get(measure.slot_key))
    .filter((column): column is DashboardChartColumn => column !== undefined);
  const categories = dimensionColumn
    ? [
        ...new Set(
          response.rows.map((row) =>
            String(row[dimensionColumn.query_alias] ?? "-"),
          ),
        ),
      ]
    : ["当前值"];
  const rowsByCategory = new Map<string, Record<string, unknown>>();
  const rowsByCategoryAndSeries = new Map<
    string,
    Map<string, Record<string, unknown>>
  >();
  if (dimensionColumn) {
    for (const row of response.rows) {
      const category = String(row[dimensionColumn.query_alias] ?? "-");
      rowsByCategory.set(category, row);
      if (seriesColumn) {
        const seriesLabel = String(row[seriesColumn.query_alias] ?? "-");
        const seriesRows = rowsByCategoryAndSeries.get(category) ?? new Map();
        seriesRows.set(seriesLabel, row);
        rowsByCategoryAndSeries.set(category, seriesRows);
      }
    }
  }

  let series: ChartSeriesModel[];
  if (dimensionColumn && seriesColumn && measureColumns[0]) {
    const measure = measureColumns[0];
    const seriesLabels = [
      ...new Set(
        response.rows.map((row) =>
          String(row[seriesColumn.query_alias] ?? "-"),
        ),
      ),
    ];
    series = seriesLabels.map((seriesLabel) => ({
      id: `${measure.slot_key}:${seriesLabel}`,
      label: seriesLabel,
      rawValues: categories.map(
        (category) =>
          rowsByCategoryAndSeries.get(category)?.get(seriesLabel)?.[
            measure.query_alias
          ] ?? null,
      ),
      values: categories.map((category) => {
        const rawValue = rowsByCategoryAndSeries
          .get(category)
          ?.get(seriesLabel)?.[measure.query_alias];
        return finiteNumber(rawValue);
      }),
    }));
  } else {
    series = measureColumns.map((column) => ({
      id: column.slot_key,
      label: column.label,
      rawValues: dimensionColumn
        ? categories.map(
            (category) =>
              rowsByCategory.get(category)?.[column.query_alias] ?? null,
          )
        : [response.rows[0]?.[column.query_alias] ?? null],
      values: dimensionColumn
        ? categories.map((category) =>
            finiteNumber(rowsByCategory.get(category)?.[column.query_alias]),
          )
        : [finiteNumber(response.rows[0]?.[column.query_alias])],
    }));
  }
  return {
    categories,
    series,
    columns: response.columns,
    tableRows: response.rows.map((row) =>
      response.columns.map((column) => row[column.query_alias]),
    ),
  };
}

export function usesCanvas(componentType: DashboardComponentType): boolean {
  return [
    "bar",
    "horizontal_bar",
    "stacked_bar",
    "line",
    "area",
    "pie",
    "donut",
  ].includes(componentType);
}
