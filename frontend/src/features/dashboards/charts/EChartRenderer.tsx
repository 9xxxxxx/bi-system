import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import type { EChartsCoreOption, EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef, useState } from "react";

import type { DashboardComponentType } from "../types";
import type { ChartModel } from "./chartModel";
import type { ChartPresentation } from "./types";

export const DASHBOARD_CHART_CONTEXT_EVENT = "dashboard-chart-context";

export interface DashboardChartContext {
  component_id: string;
  series_id: string;
  data_index: number;
  name: string;
}

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reduced;
}

function escapeTooltip(value: unknown): string {
  return String(value ?? "-")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function rawTooltipFormatter(params: unknown): string {
  const items = (Array.isArray(params) ? params : [params]) as Array<{
    name?: unknown;
    seriesName?: unknown;
    data?: { rawValue?: unknown; value?: unknown } | unknown;
    value?: unknown;
  }>;
  const heading = items[0]?.name ? `${escapeTooltip(items[0].name)}<br/>` : "";
  return (
    heading +
    items
      .map((item) => {
        const data =
          typeof item.data === "object" && item.data !== null
            ? (item.data as { rawValue?: unknown; value?: unknown })
            : undefined;
        const rawValue = data?.rawValue ?? data?.value ?? item.value;
        return `${escapeTooltip(item.seriesName)}: ${escapeTooltip(rawValue)}`;
      })
      .join("<br/>")
  );
}

function chartOption(
  componentType: DashboardComponentType,
  model: ChartModel,
  presentation: ChartPresentation,
  reducedMotion: boolean,
): EChartsCoreOption {
  const dark = presentation.theme === "dark";
  const text = dark ? "#d9e1ea" : "#344054";
  const gridLine = dark ? "#344150" : "#e7eaee";
  const common = {
    animation: !reducedMotion,
    animationDuration: reducedMotion ? 0 : 260,
    animationDurationUpdate: reducedMotion ? 0 : 160,
    color: ["#1677ff", "#0f8f83", "#d97706", "#7c3aed", "#cf4f45"],
    textStyle: { color: text },
    legend: {
      show: presentation.show_legend,
      bottom: 0,
      textStyle: { color: text },
    },
    tooltip: {
      show: presentation.show_tooltip,
      trigger:
        componentType === "pie" || componentType === "donut" ? "item" : "axis",
      formatter: rawTooltipFormatter,
    },
  };
  if (componentType === "pie" || componentType === "donut") {
    const values = model.series[0]?.values ?? [];
    return {
      ...common,
      series: [
        {
          id: model.series[0]?.id ?? "value",
          name: model.series[0]?.label ?? "数值",
          type: "pie",
          radius: componentType === "donut" ? ["46%", "68%"] : "68%",
          center: ["50%", "44%"],
          label: { show: presentation.show_labels },
          data: model.categories.map((name, index) => ({
            name,
            value: values[index],
            rawValue: model.series[0]?.rawValues[index] ?? values[index],
          })),
        },
      ],
    };
  }
  const horizontal = componentType === "horizontal_bar";
  const line = componentType === "line" || componentType === "area";
  const categoryAxis = {
    type: "category" as const,
    data: model.categories,
    axisLabel: { color: text, hideOverlap: true },
    axisLine: { lineStyle: { color: gridLine } },
  };
  const valueAxis = {
    type: "value" as const,
    axisLabel: { color: text },
    splitLine: { lineStyle: { color: gridLine } },
  };
  return {
    ...common,
    grid: {
      left: horizontal ? 72 : 48,
      right: 20,
      top: 18,
      bottom: 48,
      containLabel: true,
    },
    xAxis: horizontal ? valueAxis : categoryAxis,
    yAxis: horizontal ? categoryAxis : valueAxis,
    series: model.series.map((series) => ({
      id: series.id,
      name: series.label,
      type: line ? "line" : "bar",
      data: series.values.map((value, index) => ({
        value,
        rawValue: series.rawValues[index] ?? value,
      })),
      stack: componentType === "stacked_bar" ? "total" : undefined,
      smooth: line,
      areaStyle: componentType === "area" ? { opacity: 0.12 } : undefined,
      label: { show: presentation.show_labels, position: "top" },
      barMaxWidth: 34,
      symbolSize: 7,
    })),
  };
}

export default function EChartRenderer({
  componentId,
  componentType,
  model,
  presentation,
  onContext,
}: {
  componentId: string;
  componentType: DashboardComponentType;
  model: ChartModel;
  presentation: ChartPresentation;
  onContext?: (context: DashboardChartContext) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const onContextRef = useRef(onContext);
  onContextRef.current = onContext;
  const reducedMotion = useReducedMotion();
  const option = useMemo(
    () => chartOption(componentType, model, presentation, reducedMotion),
    [componentType, model, presentation, reducedMotion],
  );
  useEffect(() => {
    if (!hostRef.current) return;
    const chart = echarts.init(hostRef.current, undefined, {
      renderer: "canvas",
    });
    chartRef.current = chart;
    const handleClick = (params: {
      seriesId?: string;
      seriesName?: string;
      dataIndex?: number;
      name?: string;
    }) => {
      const context: DashboardChartContext = {
        component_id: componentId,
        series_id: String(params.seriesId ?? params.seriesName ?? ""),
        data_index: Number.isInteger(params.dataIndex) ? params.dataIndex! : 0,
        name: String(params.name ?? ""),
      };
      onContextRef.current?.(context);
      hostRef.current?.dispatchEvent(
        new CustomEvent<DashboardChartContext>(DASHBOARD_CHART_CONTEXT_EVENT, {
          bubbles: true,
          detail: context,
        }),
      );
    };
    chart.on("click", handleClick);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(hostRef.current);
    return () => {
      observer.disconnect();
      chart.off("click", handleClick);
      chart.dispose();
      chartRef.current = null;
    };
  }, [componentId]);
  useEffect(() => {
    chartRef.current?.setOption(option, { notMerge: true });
  }, [option]);
  return (
    <div
      ref={hostRef}
      className="dashboard-chart-canvas"
      role="img"
      aria-label={`${componentId} 图表`}
      data-reduced-motion={reducedMotion ? "true" : "false"}
    />
  );
}
