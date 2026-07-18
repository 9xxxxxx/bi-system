import {
  BarChartOutlined,
  FileImageOutlined,
  FieldNumberOutlined,
  LineChartOutlined,
  PieChartOutlined,
  TableOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { Button, Typography } from "antd";
import type { ReactNode } from "react";

import type { DashboardComponentType } from "../types";

interface ComponentOption {
  type: DashboardComponentType;
  label: string;
  icon: ReactNode;
}

const componentOptions: ComponentOption[] = [
  { type: "kpi", label: "关键指标", icon: <FieldNumberOutlined /> },
  { type: "trend_indicator", label: "趋势指标", icon: <LineChartOutlined /> },
  { type: "ranking_table", label: "排行表", icon: <UnorderedListOutlined /> },
  { type: "detail_table", label: "明细表", icon: <TableOutlined /> },
  { type: "bar", label: "柱状图", icon: <BarChartOutlined /> },
  { type: "line", label: "折线图", icon: <LineChartOutlined /> },
  { type: "donut", label: "环图", icon: <PieChartOutlined /> },
  { type: "rich_text", label: "富文本", icon: <FileImageOutlined /> },
];

export function ComponentPalette({
  onAdd,
}: {
  onAdd: (componentType: DashboardComponentType) => void;
}) {
  return (
    <aside className="dashboard-pane component-palette" aria-label="组件面板">
      <div className="dashboard-pane-heading">
        <Typography.Text strong>组件</Typography.Text>
        <Typography.Text type="secondary">添加空组件</Typography.Text>
      </div>
      <div className="component-palette-grid">
        {componentOptions.map((option) => (
          <Button
            key={option.type}
            icon={option.icon}
            aria-label={`添加${option.label}组件`}
            onClick={() => onAdd(option.type)}
          >
            {option.label}
          </Button>
        ))}
      </div>
    </aside>
  );
}
