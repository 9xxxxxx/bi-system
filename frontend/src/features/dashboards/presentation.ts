import { ApiError } from "../../shared/api/client";
import type { DashboardComponentType } from "./types";

export const componentTypeLabels: Record<DashboardComponentType, string> = {
  kpi: "关键指标",
  trend_indicator: "趋势指标",
  target_progress: "目标进度",
  detail_table: "明细表",
  ranking_table: "排行表",
  bar: "柱状图",
  horizontal_bar: "条形图",
  stacked_bar: "堆叠柱图",
  line: "折线图",
  area: "面积图",
  pie: "饼图",
  donut: "环图",
  rich_text: "富文本",
  image: "图片",
};

export function dashboardErrorDescription(error: unknown): string {
  if (error instanceof ApiError) {
    return [error.message, error.action].filter(Boolean).join("；");
  }
  if (error instanceof Error) return error.message;
  return "请稍后重试，或联系工作区管理员";
}
