import {
  AppstoreAddOutlined,
  DashboardOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FileAddOutlined,
  RollbackOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Empty,
  Input,
  Popconfirm,
  Segmented,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  deleteDashboard,
  listDashboards,
  restoreDashboard,
  type DashboardListOptions,
} from "../api";
import {
  DashboardErrorState,
  DashboardLoadingState,
} from "../components/DashboardQueryState";
import { dashboardErrorDescription } from "../presentation";
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

type DashboardListMode = "current" | "recycle-bin";

const listModeOptions: Array<{
  label: string;
  value: DashboardListMode;
}> = [
  { label: "当前", value: "current" },
  { label: "回收站", value: "recycle-bin" },
];

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

const metadataColumns: ColumnsType<DashboardSummary> = [
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
];

export function DashboardListPage() {
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState<DashboardListMode>("current");
  const queryClient = useQueryClient();
  const listOptions = useMemo<DashboardListOptions>(
    () =>
      mode === "recycle-bin" ? { status: "deleted", includeDeleted: true } : {},
    [mode],
  );
  const dashboardsQuery = useQuery({
    queryKey: dashboardQueryKeys.list(listOptions),
    queryFn: () => listDashboards(listOptions),
  });
  const deleteMutation = useMutation({
    mutationFn: (dashboard: DashboardSummary) =>
      deleteDashboard(dashboard.id, dashboard.revision),
    onSuccess: async (_, dashboard) => {
      queryClient.removeQueries({
        queryKey: dashboardQueryKeys.detail(dashboard.id),
        exact: true,
      });
      await queryClient.invalidateQueries({
        queryKey: dashboardQueryKeys.lists(),
      });
    },
  });
  const restoreMutation = useMutation({
    mutationFn: (dashboard: DashboardSummary) =>
      restoreDashboard(dashboard.id, dashboard.revision),
    onSuccess: async (restored, dashboard) => {
      queryClient.setQueryData(
        dashboardQueryKeys.detail(dashboard.id),
        restored,
      );
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: dashboardQueryKeys.lists(),
        }),
        queryClient.invalidateQueries({
          queryKey: dashboardQueryKeys.detail(dashboard.id),
          exact: true,
        }),
      ]);
    },
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
  const columns = useMemo<ColumnsType<DashboardSummary>>(
    () => [
      ...metadataColumns,
      {
        title: "操作",
        key: "action",
        width: mode === "recycle-bin" ? 72 : 112,
        fixed: "right",
        render: (_, dashboard) => {
          if (mode === "recycle-bin") {
            return (
              <Tooltip title="恢复仪表盘">
                <Button
                  type="text"
                  icon={<RollbackOutlined />}
                  aria-label={`恢复 ${dashboard.name}`}
                  loading={
                    restoreMutation.isPending &&
                    restoreMutation.variables?.id === dashboard.id
                  }
                  onClick={() => restoreMutation.mutate(dashboard)}
                />
              </Tooltip>
            );
          }
          const canEdit = dashboard.capabilities.includes("edit");
          return (
            <Space size={0}>
              <Tooltip title={canEdit ? "编辑仪表盘" : "查看仪表盘"}>
                <Button
                  type="text"
                  href={`/dashboards/${dashboard.id}`}
                  icon={canEdit ? <EditOutlined /> : <EyeOutlined />}
                  aria-label={`${canEdit ? "编辑" : "查看"} ${dashboard.name}`}
                />
              </Tooltip>
              {canEdit ? (
                <Popconfirm
                  title="移入回收站？"
                  description="仪表盘将在回收站保留 30 天。"
                  okText="移入回收站"
                  cancelText="取消"
                  onConfirm={() => deleteMutation.mutate(dashboard)}
                >
                  <Tooltip title="移入回收站">
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      aria-label={`删除 ${dashboard.name}`}
                      loading={
                        deleteMutation.isPending &&
                        deleteMutation.variables?.id === dashboard.id
                      }
                    />
                  </Tooltip>
                </Popconfirm>
              ) : null}
            </Space>
          );
        },
      },
    ],
    [deleteMutation, mode, restoreMutation],
  );

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

  const mutationError = deleteMutation.error ?? restoreMutation.error;
  const isEmpty = dashboardsQuery.data?.total === 0 && search.length === 0;
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
        <Segmented<DashboardListMode>
          aria-label="仪表盘视图"
          options={listModeOptions}
          value={mode}
          onChange={setMode}
        />
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索仪表盘或负责人"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Typography.Text type="secondary" className="dashboard-count">
          {dashboardsQuery.data?.total ?? 0} 个
        </Typography.Text>
      </div>
      {mutationError ? (
        <Alert
          className="dashboard-lifecycle-alert"
          type="error"
          showIcon
          title={mode === "recycle-bin" ? "恢复失败" : "删除失败"}
          description={dashboardErrorDescription(mutationError)}
          closable
          onClose={() => {
            deleteMutation.reset();
            restoreMutation.reset();
          }}
        />
      ) : null}
      {isEmpty ? (
        <Empty
          className="dashboard-list-empty"
          image={<DashboardOutlined />}
          description={mode === "recycle-bin" ? "回收站为空" : "还没有仪表盘"}
        >
          {mode === "current" ? (
            <Space wrap>
              <Button href="/dashboards/new?source=template">浏览模板</Button>
              <Button type="primary" href="/dashboards/new">
                创建第一个仪表盘
              </Button>
            </Space>
          ) : null}
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
            emptyText: (
              <Empty
                description={
                  mode === "recycle-bin"
                    ? "没有符合搜索条件的回收站项目"
                    : "没有符合搜索条件的仪表盘"
                }
              />
            ),
          }}
        />
      )}
    </section>
  );
}
