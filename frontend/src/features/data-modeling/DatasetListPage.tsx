import {
  ApartmentOutlined,
  PlusOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { listDatasets } from "./api";
import { dataModelingQueryKeys } from "./queryKeys";
import type { DatasetStatus, DatasetSummary } from "./types";

const statusPresentation: Record<
  DatasetStatus,
  { label: string; color: string }
> = {
  draft: { label: "草稿", color: "default" },
  active: { label: "可用", color: "success" },
  archived: { label: "已归档", color: "warning" },
};

function errorDescription(error: unknown): string {
  if (error instanceof ApiError) {
    return [error.message, error.action].filter(Boolean).join("；");
  }
  if (error instanceof Error) return error.message;
  return "无法加载数据集，请稍后重试";
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

export function DatasetListPage() {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<DatasetStatus | "all">("all");
  const datasetsQuery = useQuery({
    queryKey: dataModelingQueryKeys.datasetList(0, 50),
    queryFn: () => listDatasets(0, 50),
  });

  const datasets = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase();
    return (datasetsQuery.data?.items ?? []).filter((dataset) => {
      const matchesStatus = status === "all" || dataset.status === status;
      const matchesSearch =
        !normalizedSearch ||
        dataset.name.toLocaleLowerCase().includes(normalizedSearch) ||
        dataset.owner_name.toLocaleLowerCase().includes(normalizedSearch);
      return matchesStatus && matchesSearch;
    });
  }, [datasetsQuery.data?.items, search, status]);

  const columns: ColumnsType<DatasetSummary> = [
    {
      title: "数据集",
      dataIndex: "name",
      width: 260,
      render: (name, record) => (
        <div className="dataset-name-cell">
          <Link to={`/datasets/${record.id}`}>{name}</Link>
          <Typography.Text type="secondary" ellipsis>
            {record.description || "暂无说明"}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (value: DatasetStatus) => (
        <Tag color={statusPresentation[value].color}>
          {statusPresentation[value].label}
        </Tag>
      ),
    },
    { title: "数据源", dataIndex: "source_count", width: 90 },
    { title: "字段", dataIndex: "field_count", width: 80 },
    { title: "指标", dataIndex: "metric_count", width: 80 },
    { title: "负责人", dataIndex: "owner_name", width: 130, ellipsis: true },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 180,
      render: formatUpdatedAt,
    },
    {
      title: "操作",
      key: "action",
      width: 100,
      fixed: "right",
      render: (_, record) => <Link to={`/datasets/${record.id}`}>打开</Link>,
    },
  ];

  const isInitialLoading = datasetsQuery.isLoading && !datasetsQuery.data;
  const isEmpty =
    !isInitialLoading && !datasetsQuery.isError && datasets.length === 0;

  return (
    <section className="modeling-page" aria-labelledby="dataset-list-title">
      <header className="modeling-page-header">
        <div>
          <Typography.Title id="dataset-list-title" level={2}>
            数据集
          </Typography.Title>
          <Typography.Text type="secondary">
            管理关联模型、字段语义和可复用分析口径
          </Typography.Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} href="/datasets/new">
          新建数据集
        </Button>
      </header>

      <div className="dataset-toolbar">
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索数据集或负责人"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Select
          aria-label="数据集状态"
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: "全部状态" },
            { value: "active", label: "可用" },
            { value: "draft", label: "草稿" },
            { value: "archived", label: "已归档" },
          ]}
        />
        <Typography.Text type="secondary" className="dataset-count">
          {datasetsQuery.data?.total ?? 0} 个数据集
        </Typography.Text>
      </div>

      {datasetsQuery.isError && (
        <Alert
          showIcon
          type="error"
          title="数据集加载失败"
          description={errorDescription(datasetsQuery.error)}
          action={
            <Button size="small" onClick={() => datasetsQuery.refetch()}>
              重新加载
            </Button>
          }
        />
      )}

      {!datasetsQuery.isError && (
        <Table
          className="dataset-table"
          rowKey="id"
          size="middle"
          loading={isInitialLoading}
          columns={columns}
          dataSource={datasets}
          scroll={{ x: 1040 }}
          pagination={false}
          locale={{
            emptyText: isEmpty ? (
              <Empty
                image={<ApartmentOutlined className="dataset-empty-icon" />}
                description={
                  search || status !== "all"
                    ? "没有符合条件的数据集"
                    : "还没有数据集"
                }
              >
                {!search && status === "all" && (
                  <Button type="primary" href="/datasets/new">
                    创建第一个数据集
                  </Button>
                )}
              </Empty>
            ) : null,
          }}
        />
      )}

      {!datasetsQuery.isError && datasetsQuery.data && datasets.length > 0 && (
        <footer className="dataset-list-footer">
          <Space size="small">
            <Typography.Text type="secondary">
              当前显示 {datasets.length} 项
            </Typography.Text>
          </Space>
        </footer>
      )}
    </section>
  );
}
