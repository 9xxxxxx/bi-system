import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption, EChartsType } from "echarts/core";
import { Download } from "lucide-react";
import {
  accessibleTables,
  chartDimensions,
  months,
  regions,
  revenue,
  target,
  trend,
} from "./data";
import { makeInteraction, type ChartInteraction, type ChartKind, type DataState } from "./contracts";

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

const rowsByKind: Record<ChartKind, Array<[string, number]>> = {
  bar: regions.map((label, index) => [label, revenue[index]]),
  line: months.map((label, index) => [label, trend[index]]),
  donut: regions.map((label, index) => [label, revenue[index]]),
};

export function chartAnimationSettings(reducedMotion: boolean) {
  return {
    animation: !reducedMotion,
    animationDuration: reducedMotion ? 0 : 280,
    animationDurationUpdate: reducedMotion ? 0 : 180,
  } as const;
}

function usePrefersReducedMotion() {
  const [reducedMotion, setReducedMotion] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return reducedMotion;
}

function optionFor(kind: ChartKind, dark: boolean, reducedMotion: boolean): EChartsCoreOption {
  const text = dark ? "#d9e1ea" : "#344054";
  const gridLine = dark ? "#344150" : "#e7eaee";
  const common = {
    ...chartAnimationSettings(reducedMotion),
    textStyle: { color: text, fontFamily: "Aptos, Microsoft YaHei, sans-serif" },
    tooltip: { trigger: kind === "donut" ? "item" : "axis" },
    color: ["#0b7a75", "#d97706", "#2563a6", "#cb4b4b"],
  };

  if (kind === "donut") {
    return {
      ...common,
      legend: { bottom: 0, textStyle: { color: text } },
      series: [
        {
          id: "share",
          name: "区域占比",
          type: "pie",
          radius: ["48%", "70%"],
          center: ["50%", "42%"],
          itemStyle: { borderColor: dark ? "#17202b" : "#ffffff", borderWidth: 2 },
          label: { show: false },
          data: rowsByKind.donut.map(([name, value]) => ({ name, value })),
        },
      ],
    };
  }

  const isBar = kind === "bar";
  const labels = isBar ? regions : months;
  return {
    ...common,
    grid: { left: 42, right: 18, top: 18, bottom: 34 },
    xAxis: {
      type: "category",
      data: labels,
      axisLabel: { color: text },
      axisLine: { lineStyle: { color: gridLine } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: text },
      splitLine: { lineStyle: { color: gridLine } },
    },
    series: isBar
      ? [
          { id: "actual", name: "营收", type: "bar", data: revenue, barMaxWidth: 30 },
          { id: "target", name: "目标", type: "bar", data: target, barMaxWidth: 30 },
        ]
      : [
          {
            id: "monthly",
            name: "月度指数",
            type: "line",
            data: trend,
            smooth: true,
            symbolSize: 7,
            areaStyle: { opacity: 0.08 },
          },
        ],
  };
}

interface EChartProps {
  componentId: string;
  title: string;
  kind: ChartKind;
  dark: boolean;
  state: DataState;
  onInteraction: (interaction: ChartInteraction) => void;
}

export function EChart({ componentId, title, kind, dark, state, onInteraction }: EChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const reducedMotion = usePrefersReducedMotion();
  const option = useMemo(() => optionFor(kind, dark, reducedMotion), [dark, kind, reducedMotion]);
  const table = accessibleTables[kind];
  const dimension = chartDimensions[kind];

  useEffect(() => {
    if (!hostRef.current || state !== "ready") return;
    const chart = echarts.init(hostRef.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    chart.setOption(option);
    chart.on("click", (params) => {
      const value = Array.isArray(params.value) ? Number(params.value.at(-1)) : Number(params.value);
      onInteraction(
        makeInteraction({
          componentId,
          seriesId: String(params.seriesId ?? params.seriesName ?? "series"),
          dimensionFieldId: dimension.fieldId,
          dataIndex: params.dataIndex,
          dataLabel: String(params.name),
          dataValue: value,
          filterValue: dimension.filterValues[params.dataIndex] ?? String(params.name),
        }),
      );
    });
    const resize = new ResizeObserver(() => chart.resize());
    resize.observe(hostRef.current);
    return () => {
      resize.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, [componentId, dimension, onInteraction, option, state]);

  const exportPng = () => {
    const chart = chartRef.current;
    if (!chart) return;
    const anchor = document.createElement("a");
    anchor.href = chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: dark ? "#17202b" : "#ffffff" });
    anchor.download = `${componentId}@2x.png`;
    anchor.click();
  };

  return (
    <article className="widget chart-widget" data-component-id={componentId}>
      <header className="widget-header drag-handle">
        <div>
          <h2 id={`${componentId}-title`}>{title}</h2>
          <span>金额：万元</span>
        </div>
        <button className="icon-button no-drag" type="button" onClick={exportPng} title="导出 2 倍 PNG" aria-label={`导出${title}为 2 倍 PNG`}>
          <Download size={16} aria-hidden="true" />
        </button>
      </header>
      <div className="widget-body chart-body">
        {state === "loading" ? <div className="state-panel" aria-live="polite"><span className="spinner" />正在加载查询结果</div> : null}
        {state === "empty" ? <div className="state-panel">当前筛选条件下暂无数据</div> : null}
        {state === "error" ? <div className="state-panel error-state"><strong>图表加载失败</strong><span>QUERY_TIMEOUT · 请缩小时间范围后重试</span></div> : null}
        {state === "ready" ? <div ref={hostRef} className="chart-canvas" role="img" aria-labelledby={`${componentId}-title`} /> : null}
      </div>
      <details className="accessible-data no-drag">
        <summary>查看无障碍数据表</summary>
        <table>
          <caption>{title}的文本替代</caption>
          <thead><tr>{table.columns.map((column) => <th scope="col" key={column}>{column}</th>)}</tr></thead>
          <tbody>{table.rows.map(([label, ...values]) => <tr key={label}><th scope="row">{label}</th>{values.map((value, index) => <td key={table.columns[index + 1]}>{value}</td>)}</tr>)}</tbody>
        </table>
      </details>
    </article>
  );
}
