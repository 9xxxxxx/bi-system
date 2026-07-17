import {
  ArrowLeftOutlined,
  DatabaseOutlined,
  FieldNumberOutlined,
  PlayCircleOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Checkbox,
  Descriptions,
  Empty,
  Input,
  Result,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../../shared/api/client";
import {
  createDataset,
  createSemanticModel,
  getDataset,
  listDataSources,
  queryDataset,
} from "./api";
import { dataModelingQueryKeys } from "./queryKeys";
import type {
  DataSource,
  DataSourceField,
  DatasetDetail,
  DatasetFieldRole,
  DatasetQueryResult,
} from "./types";

function errorDescription(error: unknown): string {
  if (error instanceof ApiError) {
    return [error.message, error.action].filter(Boolean).join("；");
  }
  if (error instanceof Error) return error.message;
  return "请求未完成，请稍后重试";
}

function defaultRole(field: DataSourceField): DatasetFieldRole {
  return ["integer", "decimal"].includes(field.data_type)
    ? "measure"
    : "dimension";
}

function semanticModelName(datasetName: string): string {
  return `${[...datasetName].slice(0, 126).join("")}模型`;
}

function useMobileLayout(): boolean {
  const mediaQuery = "(max-width: 768px)";
  const [isMobile, setIsMobile] = useState(
    () => window.matchMedia(mediaQuery).matches,
  );
  useEffect(() => {
    const media = window.matchMedia(mediaQuery);
    const update = () => setIsMobile(media.matches);
    media.addEventListener("change", update);
    update();
    return () => media.removeEventListener("change", update);
  }, []);
  return isMobile;
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
      <div className="source-list">
        {visibleSources.length > 0 ? (
          <ul>
            {visibleSources.map((source) => (
              <li key={source.id}>
                <button
                  type="button"
                  className={`source-list-button${selectedId === source.id ? " is-selected" : ""}`}
                  onClick={() => onSelect(source.id)}
                >
                  <span>{source.name}</span>
                  <small>
                    {source.fields.length} 个字段 · {source.active_row_count} 行
                  </small>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="没有可用数据源"
          />
        )}
      </div>
    </aside>
  );
}

function NewDatasetWorkbench() {
  const navigate = useNavigate();
  const isMobile = useMobileLayout();
  const sourcesQuery = useQuery({
    queryKey: dataModelingQueryKeys.dataSources(),
    queryFn: listDataSources,
  });
  const activeSources = useMemo(
    () =>
      (sourcesQuery.data ?? []).filter((source) => source.status === "active"),
    [sourcesQuery.data],
  );
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedSourceId, setSelectedSourceId] = useState<string>();
  const [selectedFieldIds, setSelectedFieldIds] = useState<string[]>([]);
  const [fieldRoles, setFieldRoles] = useState<
    Record<string, DatasetFieldRole>
  >({});
  const selectedSource =
    activeSources.find((source) => source.id === selectedSourceId) ??
    activeSources[0];

  useEffect(() => {
    if (!selectedSource) {
      setSelectedFieldIds([]);
      setFieldRoles({});
      return;
    }
    setSelectedFieldIds(selectedSource.fields.map((field) => field.id));
    setFieldRoles(
      Object.fromEntries(
        selectedSource.fields.map((field) => [field.id, defaultRole(field)]),
      ),
    );
  }, [selectedSource]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!selectedSource) throw new Error("请选择可用数据源");
      const trimmedName = name.trim();
      if (!trimmedName) throw new Error("请输入数据集名称");
      const fields = selectedSource.fields.filter((field) =>
        selectedFieldIds.includes(field.id),
      );
      if (fields.length === 0) throw new Error("至少选择一个字段");
      const normalizedDescription = description.trim() || null;
      const model = await createSemanticModel({
        name: semanticModelName(trimmedName),
        description: normalizedDescription,
        sources: [
          { target_id: selectedSource.id, alias: "fact", role: "fact" },
        ],
        joins: [],
      });
      const modelSource = model.sources[0];
      if (!modelSource) throw new Error("语义模型未返回事实表来源");
      return createDataset({
        semantic_model_id: model.id,
        name: trimmedName,
        description: normalizedDescription,
        fields: fields.map((field, index) => ({
          model_source_id: modelSource.id,
          source_column_id: field.id,
          name: `field_${index + 1}`,
          label: field.display_name,
          role: fieldRoles[field.id] ?? defaultRole(field),
          hidden: false,
        })),
      });
    },
    onSuccess: (dataset) =>
      navigate(`/datasets/${dataset.id}`, { replace: true }),
  });

  if (sourcesQuery.isLoading) {
    return (
      <section className="modeling-workbench loading-workbench">
        <Skeleton active paragraph={{ rows: 9 }} />
      </section>
    );
  }
  if (sourcesQuery.isError) {
    return (
      <Result
        status="error"
        title="建模工作台加载失败"
        subTitle={errorDescription(sourcesQuery.error)}
        extra={
          <Button type="primary" onClick={() => void sourcesQuery.refetch()}>
            重新加载
          </Button>
        }
      />
    );
  }

  const selectedCount = selectedFieldIds.length;
  const canSave =
    Boolean(name.trim()) &&
    Boolean(selectedSource) &&
    selectedCount > 0 &&
    !isMobile;

  return (
    <section className="modeling-workbench" aria-labelledby="workbench-title">
      <header className="workbench-header">
        <div>
          <Link to="/datasets" className="workbench-back-link">
            <ArrowLeftOutlined /> 数据集
          </Link>
          <Typography.Title id="workbench-title" level={2}>
            新建数据集
          </Typography.Title>
          <Typography.Text type="secondary">
            选择一个事实表并定义首版字段语义
          </Typography.Text>
        </div>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={saveMutation.isPending}
          disabled={!canSave}
          onClick={() => saveMutation.mutate()}
        >
          保存草稿
        </Button>
      </header>

      <Alert
        className="mobile-readonly-alert"
        type="info"
        showIcon
        title="移动端为只读模式"
        description="请在桌面端创建或修改数据集。"
      />
      {saveMutation.isError && (
        <Alert
          type="error"
          showIcon
          title="数据集保存失败"
          description={errorDescription(saveMutation.error)}
          closable
        />
      )}

      <div className="model-health-bar" aria-label="数据集配置状态">
        <div>
          <DatabaseOutlined />
          <span>可用数据源</span>
          <strong>{activeSources.length}</strong>
        </div>
        <div>
          <FieldNumberOutlined />
          <span>已选字段</span>
          <strong>{selectedCount}</strong>
        </div>
        <div>
          <SaveOutlined />
          <span>保存状态</span>
          <strong className="health-pending">草稿</strong>
        </div>
      </div>

      <div className="modeling-grid">
        <DataSourceList
          sources={activeSources}
          selectedId={selectedSource?.id}
          onSelect={setSelectedSourceId}
        />
        <main className="modeling-pane relation-pane" aria-label="数据集属性">
          <div className="modeling-pane-heading">
            <div>
              <Typography.Text strong>基本信息</Typography.Text>
              <Typography.Text type="secondary">
                名称将在数据集目录和报表中显示
              </Typography.Text>
            </div>
          </div>
          <Space orientation="vertical" size="large" style={{ width: "100%" }}>
            <label>
              <Typography.Text strong>数据集名称</Typography.Text>
              <Input
                aria-label="数据集名称"
                maxLength={128}
                placeholder="例如：销售经营数据集"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              <Typography.Text strong>描述</Typography.Text>
              <Input.TextArea
                aria-label="数据集描述"
                maxLength={500}
                autoSize={{ minRows: 3, maxRows: 6 }}
                placeholder="说明数据范围、更新频率或适用场景"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            {selectedSource ? (
              <Descriptions size="small" column={1} colon={false}>
                <Descriptions.Item label="事实表">
                  {selectedSource.name}
                </Descriptions.Item>
                <Descriptions.Item label="有效数据">
                  {selectedSource.active_row_count} 行
                </Descriptions.Item>
                <Descriptions.Item label="活动批次">
                  {selectedSource.latest_active_batch_id ?? "暂无"}
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Empty description="导入数据后即可开始建模" />
            )}
          </Space>
        </main>
        <aside className="modeling-pane inspector-pane" aria-label="字段配置">
          <div className="modeling-pane-heading">
            <div>
              <Typography.Text strong>字段配置</Typography.Text>
              <Typography.Text type="secondary">
                选择字段并指定分析角色
              </Typography.Text>
            </div>
          </div>
          {selectedSource?.fields.length ? (
            <Checkbox.Group
              value={selectedFieldIds}
              onChange={(values) => setSelectedFieldIds(values.map(String))}
              style={{ width: "100%" }}
            >
              <ul className="field-list">
                {selectedSource.fields.map((field) => (
                  <li key={field.id}>
                    <Checkbox value={field.id}>{field.display_name}</Checkbox>
                    <Select
                      aria-label={`${field.display_name}字段角色`}
                      size="small"
                      value={fieldRoles[field.id] ?? defaultRole(field)}
                      disabled={!selectedFieldIds.includes(field.id)}
                      style={{ width: 88 }}
                      options={[
                        { value: "dimension", label: "维度" },
                        { value: "measure", label: "度量" },
                      ]}
                      onChange={(role: DatasetFieldRole) =>
                        setFieldRoles((current) => ({
                          ...current,
                          [field.id]: role,
                        }))
                      }
                    />
                  </li>
                ))}
              </ul>
            </Checkbox.Group>
          ) : (
            <Empty description="所选数据源暂无字段" />
          )}
        </aside>
      </div>
    </section>
  );
}

function DatasetPreview({ dataset }: { dataset: DatasetDetail }) {
  const [selectedFieldIds, setSelectedFieldIds] = useState<string[]>([]);
  useEffect(() => {
    setSelectedFieldIds(
      dataset.fields
        .filter(
          (field) =>
            !field.hidden &&
            field.field_kind === "source" &&
            field.source_column_id !== null,
        )
        .map((field) => field.id),
    );
  }, [dataset]);
  const previewMutation = useMutation({
    mutationFn: () =>
      queryDataset({
        dataset_id: dataset.id,
        selections: dataset.fields
          .filter((field) => selectedFieldIds.includes(field.id))
          .map((field) => ({ field_id: field.id, output_name: field.name })),
        limit: 100,
      }),
  });
  const result = previewMutation.data;
  const fieldByName = useMemo(
    () => new Map(dataset.fields.map((field) => [field.name, field])),
    [dataset.fields],
  );
  const columns: ColumnsType<Record<string, unknown>> = (
    result?.columns ?? []
  ).map((name) => ({
    key: name,
    dataIndex: name,
    title: fieldByName.get(name)?.label ?? name,
    ellipsis: true,
    render: (value: unknown) => (value == null ? "—" : String(value)),
  }));

  return (
    <>
      <div className="model-health-bar" aria-label="数据集版本信息">
        <div>
          <FieldNumberOutlined />
          <span>字段</span>
          <strong>{dataset.field_count}</strong>
        </div>
        <div>
          <DatabaseOutlined />
          <span>数据集版本</span>
          <strong>v{result?.dataset_version ?? dataset.version}</strong>
        </div>
        <div>
          <PlayCircleOutlined />
          <span>查询状态</span>
          <strong className="health-pending">
            {previewMutation.isPending
              ? "执行中"
              : result
                ? "已完成"
                : "待执行"}
          </strong>
        </div>
      </div>
      <main className="modeling-pane" aria-label="数据查询预览">
        <Space orientation="vertical" size="large" style={{ width: "100%" }}>
          <div className="modeling-pane-heading">
            <div>
              <Typography.Text strong>查询预览</Typography.Text>
              <Typography.Text type="secondary">
                选择要验证的字段，最多返回 100 行
              </Typography.Text>
            </div>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={previewMutation.isPending}
              disabled={selectedFieldIds.length === 0}
              onClick={() => previewMutation.mutate()}
            >
              运行预览
            </Button>
          </div>
          <Checkbox.Group
            value={selectedFieldIds}
            onChange={(values) => setSelectedFieldIds(values.map(String))}
          >
            <Space wrap>
              {dataset.fields.map((field) => (
                <Checkbox
                  key={field.id}
                  value={field.id}
                  disabled={
                    field.hidden ||
                    field.field_kind !== "source" ||
                    field.source_column_id === null
                  }
                >
                  {field.label}
                </Checkbox>
              ))}
            </Space>
          </Checkbox.Group>
          {previewMutation.isError && (
            <Alert
              type="error"
              showIcon
              title="查询预览失败"
              description={errorDescription(previewMutation.error)}
            />
          )}
          {result ? (
            <PreviewResult result={result} columns={columns} />
          ) : (
            <Empty description="选择字段后运行预览" />
          )}
        </Space>
      </main>
    </>
  );
}

function PreviewResult({
  result,
  columns,
}: {
  result: DatasetQueryResult;
  columns: ColumnsType<Record<string, unknown>>;
}) {
  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Space wrap>
        <Tag color={result.truncated ? "warning" : "success"}>
          {result.truncated ? "结果已截断" : "结果完整"}
        </Tag>
        <Typography.Text type="secondary">
          耗时 {result.elapsed_ms.toFixed(1)} ms
        </Typography.Text>
        <Typography.Text type="secondary">
          版本 v{result.dataset_version}
        </Typography.Text>
        <Typography.Text type="secondary">
          {result.source_batch_ids.length} 个来源批次
        </Typography.Text>
      </Space>
      {result.rows.length > 0 ? (
        <Table<Record<string, unknown>>
          rowKey={(_, index) => String(index)}
          columns={columns}
          dataSource={result.rows}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          scroll={{ x: "max-content" }}
          size="small"
        />
      ) : (
        <Empty description="当前条件没有返回数据" />
      )}
    </Space>
  );
}

function ExistingDatasetWorkbench({ datasetId }: { datasetId: string }) {
  const datasetQuery = useQuery({
    queryKey: ["data-modeling", "dataset", datasetId],
    queryFn: () => getDataset(datasetId),
  });
  if (datasetQuery.isLoading) {
    return (
      <section className="modeling-workbench loading-workbench">
        <Skeleton active paragraph={{ rows: 9 }} />
      </section>
    );
  }
  if (datasetQuery.isError) {
    if (
      datasetQuery.error instanceof ApiError &&
      datasetQuery.error.status === 404
    ) {
      return (
        <Result
          status="404"
          title="数据集不存在"
          subTitle="该数据集可能已被删除或不在当前工作区。"
          extra={<Button href="/datasets">返回数据集</Button>}
        />
      );
    }
    return (
      <Result
        status="error"
        title="数据集加载失败"
        subTitle={errorDescription(datasetQuery.error)}
        extra={
          <Button type="primary" onClick={() => void datasetQuery.refetch()}>
            重新加载
          </Button>
        }
      />
    );
  }
  const dataset = datasetQuery.data;
  if (!dataset) return null;
  return (
    <section className="modeling-workbench" aria-labelledby="workbench-title">
      <header className="workbench-header">
        <div>
          <Link to="/datasets" className="workbench-back-link">
            <ArrowLeftOutlined /> 数据集
          </Link>
          <Typography.Title id="workbench-title" level={2}>
            {dataset.name}
          </Typography.Title>
          <Typography.Text type="secondary">
            {dataset.description || "数据模型工作区"}
          </Typography.Text>
        </div>
        <Tag color={dataset.status === "active" ? "success" : "default"}>
          {dataset.status === "active" ? "可用" : "草稿"}
        </Tag>
      </header>
      <DatasetPreview dataset={dataset} />
    </section>
  );
}

export function DatasetWorkbenchPage() {
  const { datasetId = "new" } = useParams();
  return datasetId === "new" ? (
    <NewDatasetWorkbench />
  ) : (
    <ExistingDatasetWorkbench datasetId={datasetId} />
  );
}
