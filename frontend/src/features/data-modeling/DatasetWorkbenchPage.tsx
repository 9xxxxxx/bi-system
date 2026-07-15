import {
  ApartmentOutlined,
  ArrowLeftOutlined,
  DatabaseOutlined,
  FieldNumberOutlined,
  LinkOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Input,
  List,
  Result,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import { listDatasets, listDataSources } from "./api";
import { dataModelingQueryKeys } from "./queryKeys";
import type { DataSource } from "./types";

function errorDescription(error: unknown): string {
  if (error instanceof ApiError) {
    return [error.message, error.action].filter(Boolean).join("；");
  }
  if (error instanceof Error) return error.message;
  return "无法加载建模资源，请稍后重试";
}

function DataSourceList({
  sources,
  selectedId,
  onSelect,
}: {
  sources: DataSource[];
  selectedId?: string;
  onSelect: (sourceId: string) => void;
}) {
  const [search, setSearch] = useState("");
  const visibleSources = useMemo(() => {
    const value = search.trim().toLocaleLowerCase();
    return value
      ? sources.filter((source) =>
          source.name.toLocaleLowerCase().includes(value),
        )
      : sources;
  }, [search, sources]);

  return (
    <aside className="modeling-pane source-pane" aria-label="可用数据源">
      <div className="modeling-pane-heading">
        <div>
          <Typography.Text strong>数据源</Typography.Text>
          <Typography.Text type="secondary">
            {sources.length} 个可用资源
          </Typography.Text>
        </div>
        <DatabaseOutlined aria-hidden />
      </div>
      <Input.Search
        allowClear
        placeholder="搜索数据源"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <List
        className="source-list"
        dataSource={visibleSources}
        locale={{ emptyText: "没有可用数据源" }}
        renderItem={(source) => (
          <List.Item>
            <button
              type="button"
              className={`source-list-button${selectedId === source.id ? " is-selected" : ""}`}
              onClick={() => onSelect(source.id)}
            >
              <span>{source.name}</span>
              <small>
                {source.fields.length} 个字段
                {` · ${source.active_row_count} 行`}
              </small>
            </button>
          </List.Item>
        )}
      />
    </aside>
  );
}

function ModelCanvas({ source }: { source?: DataSource }) {
  return (
    <main className="modeling-pane relation-pane" aria-label="关系模型">
      <div className="modeling-pane-heading relation-heading">
        <div>
          <Typography.Text strong>关系模型</Typography.Text>
          <Typography.Text type="secondary">
            事实表、维度表与连接基数
          </Typography.Text>
        </div>
        <Tag icon={<LinkOutlined />}>尚未校验</Tag>
      </div>
      {source ? (
        <div className="relation-surface">
          <div className="model-node fact-node">
            <span className="model-node-kicker">事实表候选</span>
            <strong>{source.name}</strong>
            <span>{source.fields.length} 个字段</span>
          </div>
          <div className="relation-connector" aria-hidden>
            <span />
            <LinkOutlined />
            <span />
          </div>
          <div className="model-node empty-node">
            <ApartmentOutlined />
            <strong>维度关系待配置</strong>
            <span>选择其他数据源后建立关联</span>
          </div>
        </div>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="导入数据后即可开始建模"
        />
      )}
    </main>
  );
}

function SourceInspector({ source }: { source?: DataSource }) {
  return (
    <aside className="modeling-pane inspector-pane" aria-label="模型检查器">
      <div className="modeling-pane-heading">
        <div>
          <Typography.Text strong>检查器</Typography.Text>
          <Typography.Text type="secondary">字段与模型属性</Typography.Text>
        </div>
        <SafetyCertificateOutlined aria-hidden />
      </div>
      {source ? (
        <>
          <Descriptions size="small" column={1} colon={false}>
            <Descriptions.Item label="资源名称">
              {source.name}
            </Descriptions.Item>
            <Descriptions.Item label="资源状态">
              <Tag color={source.status === "active" ? "success" : "default"}>
                {source.status === "active" ? "可用" : source.status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="数据行数">
              {source.active_row_count}
            </Descriptions.Item>
            <Descriptions.Item label="字段数量">
              {source.fields.length}
            </Descriptions.Item>
          </Descriptions>
          <div className="field-preview">
            <Typography.Text strong>字段预览</Typography.Text>
            <List
              size="small"
              dataSource={source.fields.slice(0, 8)}
              locale={{ emptyText: "暂无字段" }}
              renderItem={(field) => (
                <List.Item>
                  <span className="field-name">
                    <FieldNumberOutlined aria-hidden />
                    {field.display_name}
                  </span>
                  <Typography.Text type="secondary">
                    {field.data_type}
                  </Typography.Text>
                </List.Item>
              )}
            />
          </div>
        </>
      ) : (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="未选择数据源"
        />
      )}
    </aside>
  );
}

export function DatasetWorkbenchPage() {
  const { datasetId = "new" } = useParams();
  const isNew = datasetId === "new";
  const datasetsQuery = useQuery({
    queryKey: dataModelingQueryKeys.datasetList(0, 50),
    queryFn: () => listDatasets(0, 50),
  });
  const sourcesQuery = useQuery({
    queryKey: dataModelingQueryKeys.dataSources(),
    queryFn: listDataSources,
  });
  const dataset = datasetsQuery.data?.items.find(
    (item) => item.id === datasetId,
  );
  const [selectedSourceId, setSelectedSourceId] = useState<string>();
  const selectedSource =
    sourcesQuery.data?.find((source) => source.id === selectedSourceId) ??
    sourcesQuery.data?.[0];

  if (datasetsQuery.isLoading || sourcesQuery.isLoading) {
    return (
      <section className="modeling-workbench loading-workbench">
        <Skeleton active paragraph={{ rows: 9 }} />
      </section>
    );
  }

  if (datasetsQuery.isError || sourcesQuery.isError) {
    const error = datasetsQuery.error ?? sourcesQuery.error;
    return (
      <Result
        status="error"
        title="建模工作台加载失败"
        subTitle={errorDescription(error)}
        extra={
          <Button
            type="primary"
            onClick={() => {
              void datasetsQuery.refetch();
              void sourcesQuery.refetch();
            }}
          >
            重新加载
          </Button>
        }
      />
    );
  }

  if (!isNew && !dataset) {
    return (
      <Result
        status="404"
        title="数据集不存在"
        subTitle="该数据集可能已被删除或移入回收站。"
        extra={<Button href="/datasets">返回数据集</Button>}
      />
    );
  }

  const sourceCount = sourcesQuery.data?.length ?? 0;
  const datasetName = dataset?.name ?? "未命名数据集";

  return (
    <section className="modeling-workbench" aria-labelledby="workbench-title">
      <header className="workbench-header">
        <div>
          <Link to="/datasets" className="workbench-back-link">
            <ArrowLeftOutlined /> 数据集
          </Link>
          <Typography.Title id="workbench-title" level={2}>
            {datasetName}
          </Typography.Title>
          <Typography.Text type="secondary">
            {isNew
              ? "配置首个事实表与字段语义"
              : dataset?.description || "数据模型工作区"}
          </Typography.Text>
        </div>
        <Space wrap>
          <Tag color={dataset?.status === "active" ? "success" : "default"}>
            {dataset?.status === "active" ? "可用" : "草稿"}
          </Tag>
        </Space>
      </header>

      <Alert
        className="mobile-readonly-alert"
        type="info"
        showIcon
        title="移动端为只读模式"
        description="请在桌面端配置关系、计算字段和权限。"
      />

      <div className="model-health-bar" aria-label="模型健康状态">
        <div>
          <DatabaseOutlined />
          <span>可用数据源</span>
          <strong>{sourceCount}</strong>
        </div>
        <div>
          <LinkOutlined />
          <span>已配置关系</span>
          <strong>0</strong>
        </div>
        <div>
          <SafetyCertificateOutlined />
          <span>模型校验</span>
          <strong className="health-pending">待配置</strong>
        </div>
      </div>

      <div className="modeling-grid">
        <DataSourceList
          sources={sourcesQuery.data ?? []}
          selectedId={selectedSource?.id}
          onSelect={setSelectedSourceId}
        />
        <ModelCanvas source={selectedSource} />
        <SourceInspector source={selectedSource} />
      </div>
    </section>
  );
}
