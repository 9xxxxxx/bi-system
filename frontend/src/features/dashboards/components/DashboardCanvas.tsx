import {
  AppstoreOutlined,
  LockOutlined,
  MoreOutlined,
} from "@ant-design/icons";
import { Button, Empty, Tag, Typography } from "antd";
import type { KeyboardEvent } from "react";
import {
  GridLayout,
  useContainerWidth,
  type Layout,
  type LayoutItem,
} from "react-grid-layout";
import "react-grid-layout/css/styles.css";

import { DashboardComponentRenderer } from "../charts/DashboardComponentRenderer";
import type { ScopedFilter } from "../charts/types";
import { componentTypeLabels } from "../presentation";
import type {
  DashboardComponent,
  DashboardLayoutItem,
  DashboardLayoutProfile,
} from "../types";

function automaticItem(
  componentId: string,
  index: number,
  columns: number,
): DashboardLayoutItem {
  const width = columns <= 4 ? columns : 4;
  const itemsPerRow = Math.max(1, Math.floor(columns / width));
  return {
    component_id: componentId,
    x: (index % itemsPerRow) * width,
    y: Math.floor(index / itemsPerRow) * 4,
    width,
    height: 4,
    min_width: Math.min(2, width),
    min_height: 3,
  };
}

function toGridItem(item: DashboardLayoutItem, readonly: boolean): LayoutItem {
  return {
    i: item.component_id,
    x: item.x,
    y: item.y,
    w: item.width,
    h: item.height,
    minW: item.min_width,
    minH: item.min_height,
    static: readonly,
  };
}

function toDashboardItems(layout: Layout): DashboardLayoutItem[] {
  return layout
    .map((item) => ({
      component_id: item.i,
      x: item.x,
      y: item.y,
      width: item.w,
      height: item.h,
      min_width: item.minW ?? 1,
      min_height: item.minH ?? 1,
    }))
    .toSorted((left, right) =>
      left.component_id.localeCompare(right.component_id),
    );
}

function overlaps(left: LayoutItem, right: LayoutItem): boolean {
  return !(
    left.x + left.w <= right.x ||
    right.x + right.w <= left.x ||
    left.y + left.h <= right.y ||
    right.y + right.h <= left.y
  );
}

export function DashboardCanvas({
  dashboardId,
  dashboardVersionId,
  pageId,
  components,
  globalFilter,
  pageFilter,
  layout,
  selectedComponentId,
  readonly,
  preview,
  onSelect,
  onLayoutChange,
}: {
  dashboardId: string;
  dashboardVersionId: string;
  pageId: string;
  components: DashboardComponent[];
  globalFilter: ScopedFilter | null;
  pageFilter: ScopedFilter | null;
  layout: DashboardLayoutProfile;
  selectedComponentId: string | null;
  readonly: boolean;
  preview: boolean;
  onSelect: (componentId: string) => void;
  onLayoutChange?: (items: DashboardLayoutItem[]) => void;
}) {
  const { width: containerWidth, containerRef } = useContainerWidth({
    initialWidth: layout.columns <= 4 ? 390 : 1200,
  });
  const layoutByComponent = new Map(
    layout.items.map((item) => [item.component_id, item]),
  );
  const gridLayout = components.map((component, index) =>
    toGridItem(
      layoutByComponent.get(component.id) ??
        automaticItem(component.id, index, layout.columns),
      readonly,
    ),
  );

  function commitLayout(nextLayout: Layout) {
    if (!readonly) onLayoutChange?.(toDashboardItems(nextLayout));
  }

  function handleKeyboardLayout(
    event: KeyboardEvent<HTMLElement>,
    componentId: string,
  ) {
    if (readonly || !event.key.startsWith("Arrow")) return;
    if (
      event.target instanceof HTMLElement &&
      event.target.closest("button, input, textarea, select")
    )
      return;
    const current = gridLayout.find((item) => item.i === componentId);
    if (!current) return;
    const next = { ...current };
    if (event.shiftKey) {
      if (event.key === "ArrowLeft")
        next.w = Math.max(current.minW ?? 1, current.w - 1);
      if (event.key === "ArrowRight")
        next.w = Math.min(layout.columns - current.x, current.w + 1);
      if (event.key === "ArrowUp")
        next.h = Math.max(current.minH ?? 1, current.h - 1);
      if (event.key === "ArrowDown") next.h = current.h + 1;
    } else {
      if (event.key === "ArrowLeft") next.x = Math.max(0, current.x - 1);
      if (event.key === "ArrowRight")
        next.x = Math.min(layout.columns - current.w, current.x + 1);
      if (event.key === "ArrowUp") next.y = Math.max(0, current.y - 1);
      if (event.key === "ArrowDown") next.y = current.y + 1;
    }
    if (
      (next.x === current.x &&
        next.y === current.y &&
        next.w === current.w &&
        next.h === current.h) ||
      gridLayout.some((item) => item.i !== componentId && overlaps(next, item))
    )
      return;
    event.preventDefault();
    commitLayout(
      gridLayout.map((item) => (item.i === componentId ? next : item)),
    );
  }

  return (
    <main
      className="dashboard-canvas-pane"
      aria-label={readonly ? "只读仪表盘画布" : "12 列仪表盘画布"}
    >
      <div className="dashboard-canvas-meta">
        <Typography.Text type="secondary">
          {readonly ? (
            <>
              <LockOutlined /> 只读布局
            </>
          ) : (
            `${layout.columns} 列 · ${layout.row_height}px 行高`
          )}
        </Typography.Text>
        <Tag>{components.length} 个组件</Tag>
      </div>
      {components.length === 0 ? (
        <div className="dashboard-canvas-empty">
          <Empty
            image={<AppstoreOutlined />}
            description={readonly ? "此页面尚无组件" : "从左侧添加第一个组件"}
          />
        </div>
      ) : (
        <div ref={containerRef} className="dashboard-canvas-grid-shell">
          <GridLayout
            className="dashboard-canvas-grid"
            width={containerWidth}
            layout={gridLayout}
            gridConfig={{
              cols: layout.columns,
              rowHeight: layout.row_height,
              margin: [10, 10],
              containerPadding: [0, 0],
            }}
            dragConfig={{
              enabled: !readonly,
              handle: ".dashboard-drag-handle",
              cancel: "button, .dashboard-placeholder-body",
            }}
            resizeConfig={{ enabled: !readonly, handles: ["se"] }}
            onDragStop={commitLayout}
            onResizeStop={commitLayout}
          >
            {components.map((component) => {
              const item = gridLayout.find(
                (layoutItem) => layoutItem.i === component.id,
              )!;
              return (
                <article
                  key={component.id}
                  className={`dashboard-component-placeholder${selectedComponentId === component.id ? " is-selected" : ""}`}
                  data-component-id={component.id}
                  data-layout-x={item.x}
                  data-layout-y={item.y}
                  data-layout-width={item.w}
                  data-layout-height={item.h}
                  tabIndex={readonly ? -1 : 0}
                  onKeyDown={(event) =>
                    handleKeyboardLayout(event, component.id)
                  }
                  onClick={() => {
                    if (!readonly) onSelect(component.id);
                  }}
                >
                  <header className="dashboard-drag-handle">
                    <div>
                      <strong>{component.title}</strong>
                      <span>
                        {componentTypeLabels[component.component_type]}
                      </span>
                    </div>
                    {readonly ? null : (
                      <Button
                        type="text"
                        size="small"
                        icon={<MoreOutlined />}
                        aria-label={`选择${component.title}`}
                        onClick={() => onSelect(component.id)}
                      />
                    )}
                  </header>
                  <div className="dashboard-placeholder-body">
                    <DashboardComponentRenderer
                      dashboardId={dashboardId}
                      dashboardVersionId={dashboardVersionId}
                      pageId={pageId}
                      component={component}
                      preview={preview}
                      globalFilter={globalFilter}
                      pageFilter={pageFilter}
                    />
                  </div>
                </article>
              );
            })}
          </GridLayout>
        </div>
      )}
    </main>
  );
}
