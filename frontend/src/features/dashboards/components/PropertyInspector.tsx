import { Form, Input, Tag, Typography } from "antd";

import { componentTypeLabels } from "../presentation";
import type { DashboardComponent } from "../types";

export function PropertyInspector({
  component,
  onChange,
}: {
  component: DashboardComponent | null;
  onChange: (component: DashboardComponent) => void;
}) {
  return (
    <aside className="dashboard-pane property-inspector" aria-label="属性面板">
      <div className="dashboard-pane-heading">
        <Typography.Text strong>属性</Typography.Text>
        <Typography.Text type="secondary">基础配置</Typography.Text>
      </div>
      {component ? (
        <Form layout="vertical" className="dashboard-property-form">
          <Form.Item label="组件类型">
            <Tag>{componentTypeLabels[component.component_type]}</Tag>
          </Form.Item>
          <Form.Item label="标题">
            <Input
              aria-label="组件标题"
              maxLength={128}
              value={component.title}
              onChange={(event) =>
                onChange({ ...component, title: event.target.value })
              }
            />
          </Form.Item>
          <Form.Item label="说明">
            <Input.TextArea
              aria-label="组件说明"
              maxLength={500}
              rows={3}
              value={component.description ?? ""}
              onChange={(event) =>
                onChange({
                  ...component,
                  description: event.target.value || null,
                })
              }
            />
          </Form.Item>
          <div className="dashboard-property-placeholder">
            <strong>数据配置待接入</strong>
            <span>M3-R2 将在此配置数据集、字段槽、排序和筛选。</span>
          </div>
        </Form>
      ) : (
        <div className="dashboard-inspector-empty">
          <Typography.Text type="secondary">
            选择画布中的组件后查看属性
          </Typography.Text>
        </div>
      )}
    </aside>
  );
}
