import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ChartModel } from "./chartModel";
import EChartRenderer from "./EChartRenderer";

let observeSpy: ReturnType<typeof vi.spyOn>;

const mocks = vi.hoisted(() => {
  const chart = {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
  };
  return { chart, init: vi.fn(() => chart), use: vi.fn() };
});

vi.mock("echarts/core", () => ({
  init: mocks.init,
  use: mocks.use,
}));
vi.mock("echarts/charts", () => ({
  BarChart: {},
  LineChart: {},
  PieChart: {},
}));
vi.mock("echarts/components", () => ({
  GridComponent: {},
  LegendComponent: {},
  TooltipComponent: {},
}));
vi.mock("echarts/renderers", () => ({ CanvasRenderer: {} }));

const model: ChartModel = {
  categories: ["华东"],
  series: [
    {
      id: "value",
      label: "销售额",
      values: [120.12345678901235],
      rawValues: ["120.12345678901234567890"],
    },
  ],
  columns: [],
  tableRows: [],
};

beforeEach(() => {
  mocks.init.mockClear();
  mocks.chart.setOption.mockClear();
  mocks.chart.dispose.mockClear();
  mocks.chart.on.mockClear();
  mocks.chart.off.mockClear();
  observeSpy = vi.spyOn(ResizeObserver.prototype, "observe");
});

afterEach(() => {
  observeSpy.mockRestore();
});

it("initializes once while applying option updates separately", async () => {
  const onContext = vi.fn();
  const view = render(
    <EChartRenderer
      componentId="component-1"
      componentType="bar"
      model={model}
      presentation={{
        unit: null,
        show_legend: true,
        show_labels: false,
        show_tooltip: true,
        theme: "light",
      }}
      onContext={onContext}
    />,
  );
  view.rerender(
    <EChartRenderer
      componentId="component-1"
      componentType="bar"
      model={{
        ...model,
        series: [{ ...model.series[0], values: [180] }],
      }}
      presentation={{
        unit: null,
        show_legend: true,
        show_labels: true,
        show_tooltip: true,
        theme: "light",
      }}
      onContext={onContext}
    />,
  );

  await waitFor(() => expect(mocks.chart.setOption).toHaveBeenCalledTimes(2));
  expect(mocks.init).toHaveBeenCalledTimes(1);
  expect(observeSpy).toHaveBeenCalledTimes(1);
  const clickHandler = mocks.chart.on.mock.calls.find(
    ([eventName]) => eventName === "click",
  )?.[1] as (params: Record<string, unknown>) => void;
  clickHandler({
    seriesId: "value",
    dataIndex: 0,
    name: "华东",
  });
  expect(onContext).toHaveBeenCalledWith({
    component_id: "component-1",
    series_id: "value",
    data_index: 0,
    name: "华东",
  });
  const latestOption = mocks.chart.setOption.mock.calls.at(-1)?.[0] as {
    tooltip: { formatter: (params: unknown) => string };
  };
  expect(
    latestOption.tooltip.formatter({
      name: "华东",
      seriesName: "销售额",
      data: { rawValue: "120.12345678901234567890" },
    }),
  ).toContain("120.12345678901234567890");
  view.unmount();
  expect(mocks.chart.dispose).toHaveBeenCalledTimes(1);
  expect(mocks.chart.off).toHaveBeenCalledWith("click", clickHandler);
});
