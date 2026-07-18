import type { Layout } from "react-grid-layout/core";
import type { ChartKind } from "./contracts";

export const regions = ["华东", "华南", "华北", "西部"];
export const revenue = [268, 192, 176, 118];
export const target = [240, 180, 190, 130];
export const months = ["1月", "2月", "3月", "4月", "5月", "6月"];
export const trend = [86, 94, 102, 99, 116, 128];

export const dimensionFieldIds = {
  soldOn: "30000000-0000-0000-0000-000000000004",
  regionName: "30000000-0000-0000-0000-000000000008",
} as const;

const monthKeys = months.map((_, index) => `2026-${String(index + 1).padStart(2, "0")}`);

export interface ChartDimension {
  fieldId: string;
  filterValues: readonly string[];
}

export interface AccessibleTableModel {
  columns: readonly string[];
  rows: ReadonlyArray<readonly [string, ...number[]]>;
}

export const chartDimensions: Record<ChartKind, ChartDimension> = {
  bar: { fieldId: dimensionFieldIds.regionName, filterValues: regions },
  line: { fieldId: dimensionFieldIds.soldOn, filterValues: monthKeys },
  donut: { fieldId: dimensionFieldIds.regionName, filterValues: regions },
};

export const accessibleTables: Record<ChartKind, AccessibleTableModel> = {
  bar: {
    columns: ["分类", "营收", "目标"],
    rows: regions.map((label, index) => [label, revenue[index], target[index]]),
  },
  line: {
    columns: ["分类", "月度指数"],
    rows: months.map((label, index) => [label, trend[index]]),
  },
  donut: {
    columns: ["分类", "营收"],
    rows: regions.map((label, index) => [label, revenue[index]]),
  },
};

export const desktopLayout: Layout = [
  { i: "kpi-revenue", x: 0, y: 0, w: 3, h: 2, minW: 2, minH: 2 },
  { i: "kpi-margin", x: 3, y: 0, w: 3, h: 2, minW: 2, minH: 2 },
  { i: "bar", x: 6, y: 0, w: 6, h: 5, minW: 4, minH: 4 },
  { i: "line", x: 0, y: 2, w: 6, h: 5, minW: 4, minH: 4 },
  { i: "donut", x: 6, y: 5, w: 4, h: 5, minW: 3, minH: 4 },
  { i: "table", x: 0, y: 7, w: 6, h: 5, minW: 4, minH: 4 },
  { i: "kpi-orders", x: 10, y: 5, w: 2, h: 2, minW: 2, minH: 2 },
];

export const mobileOrder = [
  "kpi-revenue",
  "kpi-margin",
  "kpi-orders",
  "line",
  "bar",
  "donut",
  "table",
] as const;
