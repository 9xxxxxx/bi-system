import type { Layout } from "react-grid-layout/core";

export const stressCounts = [1, 20, 50] as const;
export type StressCount = (typeof stressCounts)[number];

const columns = 12;
const widgetWidth = 3;
const widgetHeight = 2;
const widgetsPerRow = columns / widgetWidth;

export function stressCountFromSearch(search: string): StressCount | null {
  const value = new URLSearchParams(search).get("stress");
  const count = value === null ? Number.NaN : Number(value);
  return stressCounts.find((candidate) => candidate === count) ?? null;
}

export function createStressLayout(count: StressCount): Layout {
  return Array.from({ length: count }, (_, index) => ({
    i: `stress-${String(index + 1).padStart(2, "0")}`,
    x: (index % widgetsPerRow) * widgetWidth,
    y: Math.floor(index / widgetsPerRow) * widgetHeight,
    w: widgetWidth,
    h: widgetHeight,
    minW: 2,
    minH: 2,
  }));
}

export const stressLayouts: Record<StressCount, Layout> = {
  1: createStressLayout(1),
  20: createStressLayout(20),
  50: createStressLayout(50),
};

export const stressComponentIds: Record<StressCount, readonly string[]> = {
  1: stressLayouts[1].map((item) => item.i),
  20: stressLayouts[20].map((item) => item.i),
  50: stressLayouts[50].map((item) => item.i),
};
