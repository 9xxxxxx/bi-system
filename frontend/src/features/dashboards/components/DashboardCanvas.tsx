import {
  AppstoreOutlined,
  LockOutlined,
  MoreOutlined,
} from "@ant-design/icons";
import { Button, Empty, Tag, Typography } from "antd";
import type { CSSProperties } from "react";

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

export function DashboardCanvas({
  components,
  layout,
  selectedComponentId,
  readonly,
  onSelect,
}: {
  components: DashboardComponent[];
  layout: DashboardLayoutProfile;
  selectedComponentId: string | null;
  readonly: boolean;
  onSelect: (componentId: string) => void;
}) {
  const layoutByComponent = new Map(
    layout.items.map((item) => [item.component_id, item]),
  );
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
        <div
          className="dashboard-canvas-grid"
          style={
            {
              "--dashboard-columns": layout.columns,
              "--dashboard-row-height": `${layout.row_height}px`,
            } as CSSProperties
          }
        >
          {components.map((component, index) => {
            const item =
              layoutByComponent.get(component.id) ??
              automaticItem(component.id, index, layout.columns);
            const style = {
              gridColumn: `${item.x + 1} / span ${item.width}`,
              gridRow: `${item.y + 1} / span ${item.height}`,
            };
            return (
              <article
                key={component.id}
                className={`dashboard-component-placeholder${selectedComponentId === component.id ? " is-selected" : ""}`}
                style={style}
                data-component-id={component.id}
              >
                <header>
                  <div>
                    <strong>{component.title}</strong>
                    <span>{componentTypeLabels[component.component_type]}</span>
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
                <button
                  className="dashboard-placeholder-body"
                  type="button"
                  disabled={readonly}
                  onClick={() => onSelect(component.id)}
                >
                  <AppstoreOutlined aria-hidden />
                  <span>组件合同已创建</span>
                  <small>数据字段将在 M3-R2 配置</small>
                </button>
              </article>
            );
          })}
        </div>
      )}
    </main>
  );
}
