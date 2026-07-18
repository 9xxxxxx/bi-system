import { describe, expect, it } from "vitest";
import type { LayoutItem } from "react-grid-layout/core";
import { createStressLayout, stressCountFromSearch, stressCounts } from "./stress";

function overlaps(left: LayoutItem, right: LayoutItem): boolean {
  return !(
    left.x + left.w <= right.x ||
    right.x + right.w <= left.x ||
    left.y + left.h <= right.y ||
    right.y + right.h <= left.y
  );
}

describe("React Grid Layout stress views", () => {
  it.each(stressCounts)("creates %i unique widgets within 12 columns", (count) => {
    const layout = createStressLayout(count);
    expect(layout).toHaveLength(count);
    expect(new Set(layout.map((item) => item.i)).size).toBe(count);
    for (const item of layout) {
      expect(item.x).toBeGreaterThanOrEqual(0);
      expect(item.y).toBeGreaterThanOrEqual(0);
      expect(item.w).toBeGreaterThan(0);
      expect(item.h).toBeGreaterThan(0);
      expect(item.x + item.w).toBeLessThanOrEqual(12);
    }
  });

  it.each(stressCounts)("keeps the %i-widget layout free of overlap", (count) => {
    const layout = createStressLayout(count);
    for (let leftIndex = 0; leftIndex < layout.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < layout.length; rightIndex += 1) {
        expect(overlaps(layout[leftIndex], layout[rightIndex])).toBe(false);
      }
    }
  });

  it("selects only the declared stable query values", () => {
    expect(stressCountFromSearch("?stress=1")).toBe(1);
    expect(stressCountFromSearch("?stress=20&theme=dark")).toBe(20);
    expect(stressCountFromSearch("?stress=50")).toBe(50);
    expect(stressCountFromSearch("?stress=7")).toBeNull();
    expect(stressCountFromSearch("")).toBeNull();
  });
});
