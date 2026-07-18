import type { Layout, LayoutItem } from "react-grid-layout/core";

const numericKeys = ["x", "y", "w", "h"] as const;
const optionalNumericKeys = ["minW", "minH", "maxW", "maxH"] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseLayoutItem(value: unknown): LayoutItem {
  if (!isRecord(value) || typeof value.i !== "string" || value.i.length === 0) {
    throw new Error("布局项目必须包含非空组件 ID");
  }

  for (const key of numericKeys) {
    if (!Number.isInteger(value[key]) || Number(value[key]) < 0) {
      throw new Error(`布局项目 ${value.i} 的 ${key} 必须是非负整数`);
    }
  }
  if (Number(value.w) === 0 || Number(value.h) === 0) {
    throw new Error(`布局项目 ${value.i} 的宽高必须大于零`);
  }
  for (const key of optionalNumericKeys) {
    if (value[key] !== undefined && (!Number.isInteger(value[key]) || Number(value[key]) <= 0)) {
      throw new Error(`布局项目 ${value.i} 的 ${key} 必须是正整数`);
    }
  }

  return {
    i: value.i,
    x: Number(value.x),
    y: Number(value.y),
    w: Number(value.w),
    h: Number(value.h),
    ...(value.minW === undefined ? {} : { minW: Number(value.minW) }),
    ...(value.minH === undefined ? {} : { minH: Number(value.minH) }),
    ...(value.maxW === undefined ? {} : { maxW: Number(value.maxW) }),
    ...(value.maxH === undefined ? {} : { maxH: Number(value.maxH) }),
  };
}

export function cloneLayout(layout: Layout): Layout {
  return layout.map((item) => ({ ...item }));
}

export function serializeLayout(layout: Layout): string {
  return JSON.stringify(cloneLayout(layout));
}

export function deserializeLayout(serialized: string, expectedIds: readonly string[]): Layout {
  const parsed: unknown = JSON.parse(serialized);
  if (!Array.isArray(parsed)) {
    throw new Error("布局快照必须是数组");
  }

  const layout = parsed.map(parseLayoutItem);
  const actualIds = layout.map((item) => item.i);
  if (new Set(actualIds).size !== actualIds.length) {
    throw new Error("布局快照包含重复组件 ID");
  }
  if (
    actualIds.length !== expectedIds.length ||
    expectedIds.some((id) => !actualIds.includes(id))
  ) {
    throw new Error("布局快照与当前仪表盘组件不匹配");
  }
  return layout;
}
