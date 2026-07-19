import { FilterOutlined } from "@ant-design/icons";
import { Button, Drawer, Tag, Typography } from "antd";
import { useState } from "react";

import type { ScopedFilter } from "../charts/types";
import { FilterEditor } from "./FilterEditor";
import { useDatasetFields } from "./useDatasetFields";

function asScopedFilter(value: Record<string, unknown> | null | undefined) {
  return (value ?? null) as ScopedFilter | null;
}

export function DashboardFilterBar({
  globalFilter,
  pageFilter,
  componentFilter,
  datasetId,
  canPreview,
  onGlobalChange,
  onPageChange,
  onComponentChange,
}: {
  globalFilter: Record<string, unknown> | null;
  pageFilter: Record<string, unknown> | null;
  componentFilter: ScopedFilter | null;
  datasetId: string;
  canPreview: boolean;
  onGlobalChange: (value: ScopedFilter | null) => void;
  onPageChange: (value: ScopedFilter | null) => void;
  onComponentChange: (value: ScopedFilter | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const fieldsQuery = useDatasetFields(datasetId);
  const activeCount = [globalFilter, pageFilter, componentFilter].filter(
    Boolean,
  ).length;
  return (
    <>
      <div className="dashboard-filter-bar">
        <Button icon={<FilterOutlined />} onClick={() => setOpen(true)}>
          筛选
        </Button>
        <Typography.Text type="secondary">
          RLS 与三个用户作用域由服务端固定 AND
        </Typography.Text>
        <Tag>{activeCount} 个已配置作用域</Tag>
      </div>
      <Drawer
        title="仪表盘筛选"
        open={open}
        onClose={() => setOpen(false)}
        size="default"
      >
        {canPreview ? (
          <div className="dashboard-filter-stack">
            <FilterEditor
              label="全局筛选"
              value={asScopedFilter(globalFilter)}
              fieldOptions={fieldsQuery.fields}
              fieldsLoading={fieldsQuery.isLoading}
              onChange={onGlobalChange}
            />
            <FilterEditor
              label="页面筛选"
              value={asScopedFilter(pageFilter)}
              fieldOptions={fieldsQuery.fields}
              fieldsLoading={fieldsQuery.isLoading}
              onChange={onPageChange}
            />
            <FilterEditor
              label="组件筛选"
              value={componentFilter}
              fieldOptions={fieldsQuery.fields}
              fieldsLoading={fieldsQuery.isLoading}
              onChange={onComponentChange}
            />
          </div>
        ) : (
          <Typography.Paragraph type="secondary">
            当前主体没有编辑或预览权限，仅可查看已保存筛选结果。
          </Typography.Paragraph>
        )}
      </Drawer>
    </>
  );
}
