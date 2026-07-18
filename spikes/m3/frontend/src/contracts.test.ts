import { describe, expect, it } from "vitest";
import { makeInteraction, toggleReadonlyFilterPanel } from "./contracts";
import {
  accessibleTables,
  chartDimensions,
  desktopLayout,
  dimensionFieldIds,
  mobileOrder,
} from "./data";
import { deserializeLayout, serializeLayout } from "./layout";
import { chartAnimationSettings } from "./EChart";

describe("chart interaction contract", () => {
  it("preserves component, series, datum, and filter context", () => {
    expect(makeInteraction({
      componentId: "revenue",
      seriesId: "actual",
      dimensionFieldId: dimensionFieldIds.regionName,
      dataIndex: 1,
      dataLabel: "华南",
      dataValue: 192,
      filterValue: "华南",
    })).toEqual({
      componentId: "revenue",
      seriesId: "actual",
      dataIndex: 1,
      dataLabel: "华南",
      dataValue: 192,
      filter: { fieldId: dimensionFieldIds.regionName, operator: "eq", value: "华南" },
    });
  });

  it("uses the governed sold-on field and canonical bucket for month clicks", () => {
    expect(chartDimensions.line).toEqual({
      fieldId: dimensionFieldIds.soldOn,
      filterValues: ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"],
    });
    expect(makeInteraction({
      componentId: "line",
      seriesId: "monthly",
      dimensionFieldId: dimensionFieldIds.soldOn,
      dataIndex: 0,
      dataLabel: "1月",
      dataValue: 86,
      filterValue: "2026-01",
    }).filter).toEqual({
      fieldId: "30000000-0000-0000-0000-000000000004",
      operator: "eq",
      value: "2026-01",
    });
  });

  it("keeps a complete mobile layout independent from desktop coordinates", () => {
    const desktopIds = desktopLayout.map((item) => item.i).sort();
    expect([...mobileOrder].sort()).toEqual(desktopIds);
    expect(mobileOrder).toEqual([
      "kpi-revenue",
      "kpi-margin",
      "kpi-orders",
      "line",
      "bar",
      "donut",
      "table",
    ]);
  });

  it("round-trips a complete desktop layout and rejects incomplete snapshots", () => {
    const serialized = serializeLayout(desktopLayout);
    const restored = deserializeLayout(serialized, desktopLayout.map((item) => item.i));
    expect(restored).toEqual(desktopLayout);
    expect(restored).not.toBe(desktopLayout);
    expect(() => deserializeLayout("[]", desktopLayout.map((item) => item.i))).toThrow(
      "布局快照与当前仪表盘组件不匹配",
    );
  });

  it("exposes both bar series in the accessibility table", () => {
    expect(accessibleTables.bar.columns).toEqual(["分类", "营收", "目标"]);
    expect(accessibleTables.bar.rows[0]).toEqual(["华东", 268, 240]);
  });

  it("toggles the observable read-only filter panel", () => {
    expect(toggleReadonlyFilterPanel(false)).toBe(true);
    expect(toggleReadonlyFilterPanel(true)).toBe(false);
  });

  it("fully disables ECharts animation for reduced-motion users", () => {
    expect(chartAnimationSettings(true)).toEqual({
      animation: false,
      animationDuration: 0,
      animationDurationUpdate: 0,
    });
  });
});
