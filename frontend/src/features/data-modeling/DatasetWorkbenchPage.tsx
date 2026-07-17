import {
  ArrowLeftOutlined,
  ApartmentOutlined,
  CheckCircleOutlined,
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
  Divider,
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
import { CalculatedFieldEditor } from "./CalculatedFieldEditor";
import {
  activateDataset,
  activateSemanticModel,
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

interface JoinConfiguration {
  joinType: "inner" | "left";
  cardinality: "one_to_one" | "many_to_one";
  factColumnId?: string;
  dimensionColumnId?: string;
}

function DataSourceList({
  sources,
  factSourceId,
  dimensionSourceIds,
  onSelectFact,
  onSelectDimensions,
}: {
  sources: DataSource[];
  factSourceId?: string;
  dimensionSourceIds: string[];
  onSelectFact: (sourceId: string) => void;
  onSelectDimensions: (sourceIds: string[]) => void;
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
          <Typography.Text strong>事实表</Typography.Text>
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
                  className={`source-list-button${factSourceId === source.id ? " is-selected" : ""}`}
                  onClick={() => onSelectFact(source.id)}
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
      <Divider />
      <Typography.Text strong>维度表</Typography.Text>
      <Typography.Paragraph type="secondary">
        可选 0–7 个来源，总来源不超过 8 个
      </Typography.Paragraph>
      <Checkbox.Group
        aria-label="维度表"
        value={dimensionSourceIds}
        onChange={(values) => onSelectDimensions(values.map(String))}
      >
        <Space orientation="vertical">
          {sources
            .filter((source) => source.id !== factSourceId)
            .map((source) => (
              <Checkbox
                key={source.id}
                value={source.id}
                disabled={
                  dimensionSourceIds.length >= 7 &&
                  !dimensionSourceIds.includes(source.id)
                }
              >
                {source.name}
              </Checkbox>
            ))}
        </Space>
      </Checkbox.Group>
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
  const [factSourceId, setFactSourceId] = useState<string>();
  const [dimensionSourceIds, setDimensionSourceIds] = useState<string[]>([]);
  const [joinConfigurations, setJoinConfigurations] = useState<
    Record<string, JoinConfiguration>
  >({});
  const [selectedFieldIds, setSelectedFieldIds] = useState<string[]>([]);
  const [fieldRoles, setFieldRoles] = useState<
    Record<string, DatasetFieldRole>
  >({});
  const factSource =
    activeSources.find((source) => source.id === factSourceId) ??
    activeSources[0];
  const dimensionSources = useMemo(
    () =>
      dimensionSourceIds
        .map((sourceId) =>
          activeSources.find((source) => source.id === sourceId),
        )
        .filter((source): source is DataSource => source !== undefined),
    [activeSources, dimensionSourceIds],
  );
  const selectedSources = useMemo(
    () => (factSource ? [factSource, ...dimensionSources] : dimensionSources),
    [dimensionSources, factSource],
  );

  useEffect(() => {
    if (!factSource) {
      setSelectedFieldIds([]);
      setFieldRoles({});
      return;
    }
    const fields = selectedSources.flatMap((source) => source.fields);
    setSelectedFieldIds(fields.map((field) => field.id));
    setFieldRoles(
      Object.fromEntries(fields.map((field) => [field.id, defaultRole(field)])),
    );
  }, [factSource, selectedSources]);

  useEffect(() => {
    setDimensionSourceIds((current) =>
      current.filter((sourceId) => sourceId !== factSource?.id).slice(0, 7),
    );
  }, [factSource?.id]);

  useEffect(() => {
    setJoinConfigurations((current) =>
      Object.fromEntries(
        dimensionSourceIds.map((sourceId) => [
          sourceId,
          current[sourceId] ?? {
            joinType: "left",
            cardinality: "many_to_one",
          },
        ]),
      ),
    );
  }, [dimensionSourceIds]);

  const saveMutation = useMutation({
    mutationFn: async (activateAfterSave: boolean) => {
      if (!factSource) throw new Error("请选择事实表");
      const trimmedName = name.trim();
      if (!trimmedName) throw new Error("请输入数据集名称");
      const fields = selectedSources.flatMap((source) =>
        source.fields
          .filter((field) => selectedFieldIds.includes(field.id))
          .map((field) => ({ source, field })),
      );
      if (fields.length === 0) throw new Error("至少选择一个字段");
      const incompleteRelation = dimensionSources.find((source) => {
        const configuration = joinConfigurations[source.id];
        return !configuration?.factColumnId || !configuration.dimensionColumnId;
      });
      if (incompleteRelation) {
        throw new Error(`请完整配置“${incompleteRelation.name}”的连接字段`);
      }
      const normalizedDescription = description.trim() || null;
      const model = await createSemanticModel({
        name: semanticModelName(trimmedName),
        description: normalizedDescription,
        sources: [
          { target_id: factSource.id, alias: "fact", role: "fact" },
          ...dimensionSources.map((source, index) => ({
            target_id: source.id,
            alias: `dim_${index + 1}`,
            role: "dimension" as const,
          })),
        ],
        joins: dimensionSources.map((source, index) => {
          const configuration = joinConfigurations[source.id];
          if (
            !configuration?.factColumnId ||
            !configuration.dimensionColumnId
          ) {
            throw new Error(`请完整配置“${source.name}”的连接字段`);
          }
          return {
            left_source: "fact",
            right_source: `dim_${index + 1}`,
            join_type: configuration.joinType,
            cardinality: configuration.cardinality,
            keys: [
              {
                left_column_id: configuration.factColumnId,
                right_column_id: configuration.dimensionColumnId,
              },
            ],
          };
        }),
      });
      if (activateAfterSave) await activateSemanticModel(model.id);
      const modelSourceByTarget = new Map(
        model.sources.map((source) => [source.target_id, source]),
      );
      const createdDataset = await createDataset({
        semantic_model_id: model.id,
        name: trimmedName,
        description: normalizedDescription,
        fields: fields.map(({ source, field }, index) => {
          const modelSource = modelSourceByTarget.get(source.id);
          if (!modelSource)
            throw new Error(`语义模型未返回“${source.name}”来源`);
          return {
            model_source_id: modelSource.id,
            source_column_id: field.id,
            name: `field_${index + 1}`,
            label: field.display_name,
            role: fieldRoles[field.id] ?? defaultRole(field),
            hidden: false,
          };
        }),
      });
      return activateAfterSave
        ? activateDataset(createdDataset.id)
        : createdDataset;
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
  const relationsReady = dimensionSources.every((source) => {
    const configuration = joinConfigurations[source.id];
    return Boolean(
      configuration?.factColumnId && configuration.dimensionColumnId,
    );
  });
  const canSave =
    Boolean(name.trim()) &&
    Boolean(factSource) &&
    selectedCount > 0 &&
    relationsReady &&
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
            配置事实表、维度关系与首版字段语义
          </Typography.Text>
        </div>
        <Space wrap>
          <Button
            icon={<SaveOutlined />}
            loading={saveMutation.isPending}
            disabled={!canSave}
            onClick={() => saveMutation.mutate(false)}
          >
            保存草稿
          </Button>
          <Button
            type="primary"
            icon={<CheckCircleOutlined />}
            loading={saveMutation.isPending}
            disabled={!canSave}
            onClick={() => saveMutation.mutate(true)}
          >
            保存并激活
          </Button>
        </Space>
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
          <span>已选来源</span>
          <strong>{selectedSources.length}/8</strong>
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
          factSourceId={factSource?.id}
          dimensionSourceIds={dimensionSourceIds}
          onSelectFact={setFactSourceId}
          onSelectDimensions={(values) =>
            setDimensionSourceIds(values.slice(0, 7))
          }
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
            {factSource ? (
              <Descriptions size="small" column={1} colon={false}>
                <Descriptions.Item label="事实表">
                  {factSource.name}
                </Descriptions.Item>
                <Descriptions.Item label="维度表">
                  {dimensionSources.length > 0
                    ? dimensionSources.map((source) => source.name).join("、")
                    : "未配置"}
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Empty description="导入数据后即可开始建模" />
            )}
            <Divider />
            <Typography.Text strong>星型关系</Typography.Text>
            {dimensionSources.length > 0 ? (
              dimensionSources.map((source) => {
                const configuration = joinConfigurations[source.id] ?? {
                  joinType: "left" as const,
                  cardinality: "many_to_one" as const,
                };
                return (
                  <Space
                    key={source.id}
                    orientation="vertical"
                    size="small"
                    style={{ width: "100%" }}
                  >
                    <Typography.Text strong>
                      <ApartmentOutlined /> {factSource?.name} → {source.name}
                    </Typography.Text>
                    <Space wrap>
                      <Select
                        aria-label={`${source.name}连接类型`}
                        value={configuration.joinType}
                        style={{ width: 110 }}
                        options={[
                          { value: "inner", label: "INNER" },
                          { value: "left", label: "LEFT" },
                        ]}
                        onChange={(joinType: JoinConfiguration["joinType"]) =>
                          setJoinConfigurations((current) => ({
                            ...current,
                            [source.id]: { ...configuration, joinType },
                          }))
                        }
                      />
                      <Select
                        aria-label={`${source.name}连接基数`}
                        value={configuration.cardinality}
                        style={{ width: 120 }}
                        options={[
                          { value: "one_to_one", label: "1:1" },
                          { value: "many_to_one", label: "N:1" },
                        ]}
                        onChange={(
                          cardinality: JoinConfiguration["cardinality"],
                        ) =>
                          setJoinConfigurations((current) => ({
                            ...current,
                            [source.id]: { ...configuration, cardinality },
                          }))
                        }
                      />
                    </Space>
                    <Select
                      aria-label={`${source.name}事实键`}
                      placeholder="选择事实表连接字段"
                      value={configuration.factColumnId}
                      options={(factSource?.fields ?? []).map((field) => ({
                        value: field.id,
                        label: `${field.display_name} · ${field.data_type}`,
                      }))}
                      onChange={(factColumnId: string) =>
                        setJoinConfigurations((current) => ({
                          ...current,
                          [source.id]: { ...configuration, factColumnId },
                        }))
                      }
                    />
                    <Select
                      aria-label={`${source.name}维度键`}
                      placeholder="选择维度表连接字段"
                      value={configuration.dimensionColumnId}
                      options={source.fields.map((field) => ({
                        value: field.id,
                        label: `${field.display_name} · ${field.data_type}`,
                      }))}
                      onChange={(dimensionColumnId: string) =>
                        setJoinConfigurations((current) => ({
                          ...current,
                          [source.id]: { ...configuration, dimensionColumnId },
                        }))
                      }
                    />
                  </Space>
                );
              })
            ) : (
              <Typography.Text type="secondary">
                单来源模型无需配置连接
              </Typography.Text>
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
          {selectedSources.some((source) => source.fields.length > 0) ? (
            <Checkbox.Group
              value={selectedFieldIds}
              onChange={(values) => setSelectedFieldIds(values.map(String))}
              style={{ width: "100%" }}
            >
              <ul className="field-list">
                {selectedSources.flatMap((source) =>
                  source.fields.map((field) => (
                    <li key={`${source.id}:${field.id}`}>
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
                      <Typography.Text type="secondary">
                        {source.id === factSource?.id ? "事实" : "维度"}
                      </Typography.Text>
                    </li>
                  )),
                )}
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
            (field.field_kind === "calculated" ||
              field.source_column_id !== null),
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
                    (field.field_kind === "source" &&
                      field.source_column_id === null)
                  }
                >
                  {field.label}
                  {field.field_kind === "calculated" && (
                    <Tag color="processing">计算</Tag>
                  )}
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
  const navigate = useNavigate();
  const isMobile = useMobileLayout();
  const datasetQuery = useQuery({
    queryKey: ["data-modeling", "dataset", datasetId],
    queryFn: () => getDataset(datasetId),
  });
  const activateMutation = useMutation({
    mutationFn: async () => {
      const dataset = datasetQuery.data;
      if (!dataset) throw new Error("数据集尚未加载完成");
      await activateSemanticModel(dataset.semantic_model_id);
      return activateDataset(dataset.id);
    },
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
  const dataset = activateMutation.data ?? datasetQuery.data;
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
        <Space wrap>
          <Tag color={dataset.status === "active" ? "success" : "default"}>
            {dataset.status === "active" ? "可用" : "草稿"}
          </Tag>
          <CalculatedFieldEditor
            dataset={dataset}
            mobileReadonly={isMobile}
            onCreated={(created) => {
              if (created.id === dataset.id) {
                void datasetQuery.refetch();
              } else {
                navigate(`/datasets/${created.id}`, { replace: true });
              }
            }}
          />
          {dataset.status === "draft" && (
            <Button
              type="primary"
              icon={<CheckCircleOutlined />}
              loading={activateMutation.isPending}
              disabled={isMobile}
              onClick={() => activateMutation.mutate()}
            >
              激活数据集
            </Button>
          )}
        </Space>
      </header>
      <Alert
        className="mobile-readonly-alert"
        type="info"
        showIcon
        title="移动端为只读模式"
        description="请在桌面端激活或修改数据集。"
      />
      {activateMutation.isError && (
        <Alert
          type="error"
          showIcon
          title="数据集激活失败"
          description={errorDescription(activateMutation.error)}
        />
      )}
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
