import {
  AppstoreAddOutlined,
  DashboardOutlined,
  FileAddOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Empty, Input, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { listDashboards } from "../api";
import {
  DashboardErrorState,
  DashboardLoadingState,
} from "../components/DashboardQueryState";
import { dashboardQueryKeys } from "../queryKeys";
import type { DashboardStatus, DashboardSummary } from "../types";
import "../dashboards.css";

const statusPresentation: Record<
  DashboardStatus,
  { label: string; color: string }
> = {
  draft: { label: "草稿", color: "default" },
  active: { label: "已发布", color: "success" },
  archived: { label: "已归档", color: "warning" },
  deleted: { label: "回收站", color: "error" },
};

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

const columns: ColumnsType<DashboardSummary> = [
  {
    title: "仪表盘",
    dataIndex: "name",
    width: 300,
    render: (name, dashboard) => (
      <div className="dashboard-name-cell">
        <Link to={`/dashboards/${dashboard.id}`}>{name}</Link>
        <Typography.Text type="secondary" ellipsis>
          {dashboard.description || "暂无说明"}
        </Typography.Text>
      </div>
    ),
  },
  {
    title: "状态",
    dataIndex: "status",
    width: 100,
    render: (status: DashboardStatus) => (
      <Tag color={statusPresentation[status].color}>
        {statusPresentation[status].label}
      </Tag>
    ),
  },
  { title: "页面", dataIndex: "page_count", width: 80 },
  {
    title: "版本",
    dataIndex: "current_version",
    width: 90,
    render: (value: number) => `v${value}`,
  },
  { title: "负责人", dataIndex: "owner_name", width: 140, ellipsis: true },
  {
    title: "更新时间",
    dataIndex: "updated_at",
    width: 180,
    render: formatUpdatedAt,
  },
  {
    title: "操作",
    key: "action",
    width: 90,
    fixed: "right",
    render: (_, dashboard) => (
      <Link to={`/dashboards/${dashboard.id}`}>
        {dashboard.capabilities.includes("edit") ? "编辑" : "查看"}
      </Link>
    ),
  },
];

export function DashboardListPage() {
  const [search, setSearch] = useState("");
  const dashboardsQuery = useQuery({
    queryKey: dashboardQueryKeys.list(),
    queryFn: () => listDashboards(),
  });
  const dashboards = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase();
    if (!normalized) return dashboardsQuery.data?.items ?? [];
    return (dashboardsQuery.data?.items ?? []).filter(
      (dashboard) =>
        dashboard.name.toLocaleLowerCase().includes(normalized) ||
        dashboard.owner_name.toLocaleLowerCase().includes(normalized),
    );
  }, [dashboardsQuery.data?.items, search]);

  if (dashboardsQuery.isLoading && !dashboardsQuery.data) {
    return <DashboardLoadingState label="正在加载仪表盘列表" />;
  }
  if (dashboardsQuery.isError) {
    return (
      <DashboardErrorState
        error={dashboardsQuery.error}
        onRetry={() => void dashboardsQuery.refetch()}
      />
    );
  }

  const isFirstDashboard =
    dashboardsQuery.data?.total === 0 && search.length === 0;
  return (
    <section className="dashboard-page" aria-labelledby="dashboard-list-title">
      <header className="dashboard-page-header">
        <div>
          <Typography.Title id="dashboard-list-title" level={2}>
            仪表盘
          </Typography.Title>
          <Typography.Text type="secondary">
            组织经营视图、页面和受治理分析组件
          </Typography.Text>
        </div>
        <Space wrap>
          <Button
            icon={<AppstoreAddOutlined />}
            href="/dashboards/new?source=template"
          >
            从模板创建
          </Button>
          <Button
            type="primary"
            icon={<FileAddOutlined />}
            href="/dashboards/new"
          >
            新建空白仪表盘
          </Button>
        </Space>
      </header>
      <div className="dashboard-toolbar">
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索仪表盘或负责人"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Typography.Text type="secondary" className="dashboard-count">
          {dashboardsQuery.data?.total ?? 0} 个仪表盘
        </Typography.Text>
      </div>
      {isFirstDashboard ? (
        <Empty
          className="dashboard-list-empty"
          image={<DashboardOutlined />}
          description="还没有仪表盘"
        >
          <Space wrap>
            <Button href="/dashboards/new?source=template">浏览模板</Button>
            <Button type="primary" href="/dashboards/new">
              创建第一个仪表盘
            </Button>
          </Space>
        </Empty>
      ) : (
        <Table
          className="dashboard-table"
          rowKey="id"
          columns={columns}
          dataSource={dashboards}
          pagination={false}
          scroll={{ x: 1080 }}
          locale={{
            emptyText: <Empty description="没有符合搜索条件的仪表盘" />,
          }}
        />
      )}
    </section>
  );
}
