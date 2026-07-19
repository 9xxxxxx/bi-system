import {
  DeleteOutlined,
  PlusOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Typography,
  Upload,
} from "antd";

import { listDatasets } from "../../data-modeling/api";
import { listMetrics } from "../../governance/api";
import {
  aggregateOptions,
  defaultChartConfig,
  isChartComponentConfig,
  isQueryComponentType,
} from "../charts/config";
import type {
  AggregateFunction,
  ChartComponentConfig,
  ChartMeasure,
  ChartSort,
  RichTextBlock,
  RichTextBlockType,
  RichTextMark,
  TimeGrain,
} from "../charts/types";
import { normalizeRichTextBlocks } from "../charts/richTextModel";
import { listDashboardAssets, uploadDashboardAsset } from "../dashboardAssets";
import type { DashboardComponent, DashboardComponentType } from "../types";
import { FilterEditor } from "./FilterEditor";
import { useDatasetFields } from "./useDatasetFields";

const seriesTypes = new Set<DashboardComponentType>([
  "bar",
  "horizontal_bar",
  "stacked_bar",
  "line",
  "area",
]);
const multiMeasureTypes = new Set<DashboardComponentType>([
  "detail_table",
  "ranking_table",
  "bar",
  "horizontal_bar",
  "stacked_bar",
  "line",
  "area",
]);

function replaceMeasure(
  config: ChartComponentConfig,
  index: number,
  measure: ChartMeasure,
): ChartComponentConfig {
  return {
    ...config,
    query: {
      ...config.query,
      measures: config.query.measures.map((item, itemIndex) =>
        itemIndex === index ? measure : item,
      ),
    },
  };
}

function nextMeasureSlot(config: ChartComponentConfig): string {
  const used = new Set(
    config.query.measures.map((measure) => measure.slot_key),
  );
  let index = 2;
  while (used.has(`value_${index}`)) index += 1;
  return `value_${index}`;
}

function sortFor(
  target: "none" | "dimension" | "measure",
  config: ChartComponentConfig,
): ChartSort[] {
  if (target === "none") return [];
  if (target === "dimension") {
    const dimension = config.query.dimensions[0];
    return dimension
      ? [
          {
            kind: "field",
            field_id: dimension.field_id,
            aggregate: null,
            direction: "asc",
          },
        ]
      : [];
  }
  const measure = config.query.measures[0];
  if (!measure) return [];
  return measure.kind === "metric"
    ? [
        {
          kind: "metric",
          metric_version_id: measure.metric_version_id,
          direction: "desc",
        },
      ]
    : [
        {
          kind: "field",
          field_id: measure.field_id,
          aggregate: measure.aggregate,
          direction: "desc",
        },
      ];
}

export function ChartConfigEditor({
  component,
  onChange,
}: {
  component: DashboardComponent;
  onChange: (component: DashboardComponent) => void;
}) {
  if (component.component_type === "rich_text") {
    return <RichTextConfigEditor component={component} onChange={onChange} />;
  }
  if (component.component_type === "image") {
    return <ImageConfigEditor component={component} onChange={onChange} />;
  }
  if (!isQueryComponentType(component.component_type)) return null;
  if (!isChartComponentConfig(component.config)) {
    return (
      <div className="dashboard-property-placeholder">
        <strong>尚未初始化图表配置</strong>
        <Button
          type="primary"
          size="small"
          onClick={() =>
            onChange({
              ...component,
              config: defaultChartConfig(component.component_type),
            })
          }
        >
          初始化字段槽
        </Button>
      </div>
    );
  }
  return (
    <ConfiguredChartEditor
      component={component}
      config={component.config}
      onChange={onChange}
    />
  );
}

function RichTextConfigEditor({
  component,
  onChange,
}: {
  component: DashboardComponent;
  onChange: (component: DashboardComponent) => void;
}) {
  const normalizedBlocks = normalizeRichTextBlocks({
    blocks: component.config.blocks,
    content: component.config.content,
  });
  const blocks = normalizedBlocks.length
    ? normalizedBlocks
    : [{ type: "paragraph", text: "", marks: [] } satisfies RichTextBlock];
  const updateBlocks = (nextBlocks: RichTextBlock[]) =>
    onChange({
      ...component,
      config: { schema_version: 1, blocks: nextBlocks },
    });
  const replaceBlock = (index: number, block: RichTextBlock) =>
    updateBlocks(
      blocks.map((item, itemIndex) => (itemIndex === index ? block : item)),
    );
  const toggleMark = (
    index: number,
    block: RichTextBlock,
    mark: RichTextMark,
  ) =>
    replaceBlock(index, {
      ...block,
      marks: block.marks.includes(mark)
        ? block.marks.filter((item) => item !== mark)
        : [...block.marks, mark],
    });
  return (
    <div className="dashboard-rich-text-editor">
      {blocks.map((block, index) => (
        <div className="dashboard-rich-text-block" key={index}>
          <Select
            aria-label={`文本块 ${index + 1} 类型`}
            value={block.type}
            options={[
              { value: "heading", label: "标题" },
              { value: "paragraph", label: "段落" },
              { value: "bullet", label: "列表项" },
            ]}
            onChange={(type: RichTextBlockType) =>
              replaceBlock(index, { ...block, type })
            }
          />
          <Input.TextArea
            aria-label={`文本块 ${index + 1} 内容`}
            autoSize={{ minRows: 2, maxRows: 5 }}
            value={block.text}
            onChange={(event) =>
              replaceBlock(index, { ...block, text: event.target.value })
            }
          />
          <div className="dashboard-rich-text-tools">
            <Button
              size="small"
              type={block.marks.includes("bold") ? "primary" : "default"}
              aria-label={`文本块 ${index + 1} 加粗`}
              aria-pressed={block.marks.includes("bold")}
              onClick={() => toggleMark(index, block, "bold")}
            >
              B
            </Button>
            <Button
              size="small"
              type={block.marks.includes("italic") ? "primary" : "default"}
              aria-label={`文本块 ${index + 1} 斜体`}
              aria-pressed={block.marks.includes("italic")}
              onClick={() => toggleMark(index, block, "italic")}
            >
              I
            </Button>
            <Button
              size="small"
              danger
              type="text"
              icon={<DeleteOutlined />}
              aria-label={`删除文本块 ${index + 1}`}
              disabled={blocks.length === 1}
              onClick={() =>
                updateBlocks(
                  blocks.filter((_, itemIndex) => itemIndex !== index),
                )
              }
            />
          </div>
        </div>
      ))}
      <Button
        size="small"
        icon={<PlusOutlined />}
        onClick={() =>
          updateBlocks([...blocks, { type: "paragraph", text: "", marks: [] }])
        }
      >
        新增文本块
      </Button>
    </div>
  );
}

function ImageConfigEditor({
  component,
  onChange,
}: {
  component: DashboardComponent;
  onChange: (component: DashboardComponent) => void;
}) {
  const queryClient = useQueryClient();
  const assetsQuery = useQuery({
    queryKey: ["dashboards", "assets"],
    queryFn: listDashboardAssets,
    staleTime: 30_000,
  });
  const selectAsset = (assetId: string) =>
    onChange({
      ...component,
      config: { ...component.config, schema_version: 1, file_id: assetId },
    });
  const uploadMutation = useMutation({
    mutationFn: uploadDashboardAsset,
    onSuccess: (asset) => {
      selectAsset(asset.id);
      void queryClient.invalidateQueries({
        queryKey: ["dashboards", "assets"],
      });
    },
  });
  return (
    <>
      <Form.Item label="仪表盘图片">
        <Select
          showSearch
          aria-label="选择仪表盘图片"
          placeholder="选择已上传图片"
          loading={assetsQuery.isLoading}
          value={String(component.config.file_id ?? "") || undefined}
          optionFilterProp="label"
          options={(assetsQuery.data?.items ?? []).map((asset) => ({
            value: asset.id,
            label: asset.filename,
          }))}
          onChange={selectAsset}
        />
      </Form.Item>
      <Upload
        accept="image/*"
        showUploadList={false}
        beforeUpload={(file) => {
          uploadMutation.mutate(file);
          return false;
        }}
      >
        <Button icon={<UploadOutlined />} loading={uploadMutation.isPending}>
          上传图片
        </Button>
      </Upload>
      {uploadMutation.isError ? (
        <Typography.Text type="danger">图片上传失败</Typography.Text>
      ) : null}
      <Form.Item label="替代文本">
        <Input
          aria-label="图片替代文本"
          value={String(component.config.alt_text ?? "")}
          onChange={(event) =>
            onChange({
              ...component,
              config: {
                ...component.config,
                schema_version: 1,
                alt_text: event.target.value,
              },
            })
          }
        />
      </Form.Item>
    </>
  );
}

function ConfiguredChartEditor({
  component,
  config,
  onChange,
}: {
  component: DashboardComponent;
  config: ChartComponentConfig;
  onChange: (component: DashboardComponent) => void;
}) {
  const datasetsQuery = useQuery({
    queryKey: ["dashboards", "catalog", "datasets"],
    queryFn: () => listDatasets(0, 100),
    staleTime: 30_000,
  });
  const metricsQuery = useQuery({
    queryKey: ["dashboards", "catalog", "metrics"],
    queryFn: listMetrics,
    staleTime: 30_000,
  });
  const fieldsQuery = useDatasetFields(config.query.dataset_id);
  const update = (next: ChartComponentConfig) =>
    onChange({ ...component, config: next });
  const firstDimension = config.query.dimensions[0];
  const firstSort = config.query.sort[0];
  const sortTarget = !firstSort
    ? "none"
    : "aggregate" in firstSort && firstSort.aggregate === null
      ? "dimension"
      : "measure";
  const dimensionFields = fieldsQuery.fields.filter(
    (field) => field.role === "dimension",
  );
  const measureFields = fieldsQuery.fields.filter(
    (field) => field.role === "measure",
  );
  const metricOptions = (metricsQuery.data?.items ?? [])
    .filter(
      (metric) =>
        metric.dataset_id === config.query.dataset_id &&
        metric.status === "active",
    )
    .map((metric) => ({
      value: metric.id,
      label: `${metric.name} v${metric.version}`,
    }));
  const supportsSeries = seriesTypes.has(component.component_type);
  const supportsMultipleMeasures = multiMeasureTypes.has(
    component.component_type,
  );
  const minimumMeasures =
    component.component_type === "stacked_bar" &&
    config.query.series_dimension === null
      ? 2
      : 1;

  return (
    <div className="dashboard-chart-config">
      <Typography.Text strong>查询字段槽</Typography.Text>
      <Form.Item label="数据集">
        <Select
          showSearch
          aria-label="图表数据集"
          placeholder="选择已启用数据集"
          loading={datasetsQuery.isLoading}
          value={config.query.dataset_id || undefined}
          optionFilterProp="label"
          options={(datasetsQuery.data?.items ?? [])
            .filter((dataset) => dataset.status === "active")
            .map((dataset) => ({ value: dataset.id, label: dataset.name }))}
          onChange={(datasetId: string) =>
            update({
              ...config,
              component_filter: null,
              query: {
                ...config.query,
                dataset_id: datasetId,
                dimensions: config.query.dimensions.map((dimension) => ({
                  ...dimension,
                  field_id: "",
                })),
                series_dimension: config.query.series_dimension
                  ? { ...config.query.series_dimension, field_id: "" }
                  : null,
                measures: config.query.measures.map((measure) => ({
                  kind: "field" as const,
                  field_id: "",
                  aggregate:
                    measure.kind === "field" ? measure.aggregate : "sum",
                  slot_key: measure.slot_key,
                })),
                sort: [],
              },
            })
          }
        />
      </Form.Item>
      {firstDimension ? (
        <>
          <Form.Item label="主维度">
            <Select
              showSearch
              aria-label="图表主维度"
              placeholder="选择可见维度"
              loading={fieldsQuery.isLoading}
              value={firstDimension.field_id || undefined}
              optionFilterProp="label"
              options={dimensionFields}
              onChange={(fieldId: string) =>
                update({
                  ...config,
                  query: {
                    ...config.query,
                    dimensions: [
                      { ...firstDimension, field_id: fieldId },
                      ...config.query.dimensions.slice(1),
                    ],
                    sort: [],
                  },
                })
              }
            />
          </Form.Item>
          <Form.Item label="时间粒度">
            <Select
              allowClear
              aria-label="图表时间粒度"
              value={firstDimension.time_grain ?? undefined}
              options={(
                ["day", "week", "month", "quarter", "year"] as TimeGrain[]
              ).map((value) => ({ value, label: value }))}
              onChange={(timeGrain?: TimeGrain) =>
                update({
                  ...config,
                  query: {
                    ...config.query,
                    dimensions: [
                      { ...firstDimension, time_grain: timeGrain ?? null },
                      ...config.query.dimensions.slice(1),
                    ],
                  },
                })
              }
            />
          </Form.Item>
        </>
      ) : null}
      {config.query.measures.map((measure, index) => (
        <div className="dashboard-measure-slot" key={measure.slot_key}>
          <div className="dashboard-measure-heading">
            <Typography.Text strong>度量 {index + 1}</Typography.Text>
            {supportsMultipleMeasures ? (
              <Button
                type="text"
                danger
                size="small"
                icon={<DeleteOutlined />}
                aria-label={`删除度量 ${index + 1}`}
                disabled={config.query.measures.length <= minimumMeasures}
                onClick={() =>
                  update({
                    ...config,
                    query: {
                      ...config.query,
                      measures: config.query.measures.filter(
                        (_, itemIndex) => itemIndex !== index,
                      ),
                      sort: [],
                    },
                  })
                }
              />
            ) : null}
          </div>
          <Select
            aria-label={`${measure.slot_key}来源类型`}
            value={measure.kind}
            options={[
              { value: "field", label: "字段聚合" },
              { value: "metric", label: "公共指标版本" },
            ]}
            onChange={(kind: "field" | "metric") =>
              update(
                replaceMeasure(
                  { ...config, query: { ...config.query, sort: [] } },
                  index,
                  kind === "field"
                    ? {
                        kind,
                        field_id: "",
                        aggregate: "sum",
                        slot_key: measure.slot_key,
                      }
                    : {
                        kind,
                        metric_version_id: "",
                        slot_key: measure.slot_key,
                      },
                ),
              )
            }
          />
          <Select
            showSearch
            aria-label={`${measure.slot_key}资源`}
            placeholder={
              measure.kind === "field" ? "选择可见度量字段" : "选择已启用指标"
            }
            loading={fieldsQuery.isLoading || metricsQuery.isLoading}
            value={
              (measure.kind === "field"
                ? measure.field_id
                : measure.metric_version_id) || undefined
            }
            optionFilterProp="label"
            options={measure.kind === "field" ? measureFields : metricOptions}
            onChange={(resourceId: string) =>
              update(
                replaceMeasure(
                  { ...config, query: { ...config.query, sort: [] } },
                  index,
                  measure.kind === "field"
                    ? { ...measure, field_id: resourceId }
                    : { ...measure, metric_version_id: resourceId },
                ),
              )
            }
          />
          {measure.kind === "field" ? (
            <Select
              aria-label={`${measure.slot_key}聚合方式`}
              value={measure.aggregate}
              options={[...aggregateOptions]}
              onChange={(aggregate: AggregateFunction) =>
                update(
                  replaceMeasure(
                    { ...config, query: { ...config.query, sort: [] } },
                    index,
                    { ...measure, aggregate },
                  ),
                )
              }
            />
          ) : null}
        </div>
      ))}
      {supportsMultipleMeasures ? (
        <Button
          icon={<PlusOutlined />}
          onClick={() =>
            update({
              ...config,
              query: {
                ...config.query,
                measures: [
                  ...config.query.measures,
                  {
                    kind: "field",
                    field_id: "",
                    aggregate: "sum",
                    slot_key: nextMeasureSlot(config),
                  },
                ],
                sort: [],
              },
            })
          }
        >
          添加度量
        </Button>
      ) : null}
      {supportsSeries ? (
        <>
          <Form.Item label="系列维度">
            <Switch
              checked={config.query.series_dimension !== null}
              onChange={(checked) =>
                update({
                  ...config,
                  query: {
                    ...config.query,
                    measures:
                      checked && component.component_type === "stacked_bar"
                        ? config.query.measures.slice(0, 1)
                        : !checked &&
                            component.component_type === "stacked_bar" &&
                            config.query.measures.length === 1
                          ? [
                              ...config.query.measures,
                              {
                                kind: "field",
                                field_id: "",
                                aggregate: "sum",
                                slot_key: nextMeasureSlot(config),
                              },
                            ]
                          : config.query.measures,
                    series_dimension: checked
                      ? { field_id: "", slot_key: "series", max_series: 12 }
                      : null,
                    top_n: checked ? null : config.query.top_n,
                    sort: [],
                  },
                })
              }
            />
          </Form.Item>
          {config.query.series_dimension ? (
            <Select
              showSearch
              aria-label="图表系列维度"
              placeholder="选择可见维度"
              loading={fieldsQuery.isLoading}
              value={config.query.series_dimension.field_id || undefined}
              optionFilterProp="label"
              options={dimensionFields.filter(
                (field) => field.value !== firstDimension?.field_id,
              )}
              onChange={(fieldId: string) =>
                update({
                  ...config,
                  query: {
                    ...config.query,
                    series_dimension: {
                      ...config.query.series_dimension!,
                      field_id: fieldId,
                    },
                  },
                })
              }
            />
          ) : null}
        </>
      ) : null}
      <Form.Item label="排序目标">
        <Select
          aria-label="图表排序目标"
          value={sortTarget}
          options={[
            { value: "none", label: "不指定" },
            { value: "dimension", label: "主维度" },
            { value: "measure", label: "首个度量" },
          ]}
          onChange={(target: "none" | "dimension" | "measure") =>
            update({
              ...config,
              query: { ...config.query, sort: sortFor(target, config) },
            })
          }
        />
      </Form.Item>
      <Form.Item label="Top N">
        <InputNumber
          aria-label="图表 Top N"
          min={1}
          max={100}
          disabled={config.query.series_dimension !== null}
          value={config.query.top_n}
          onChange={(value) =>
            update({
              ...config,
              query: { ...config.query, top_n: value },
            })
          }
        />
      </Form.Item>
      <Form.Item label="单位">
        <Input
          aria-label="图表单位"
          value={config.presentation.unit ?? ""}
          onChange={(event) =>
            update({
              ...config,
              presentation: {
                ...config.presentation,
                unit: event.target.value || null,
              },
            })
          }
        />
      </Form.Item>
      <div className="dashboard-presentation-switches">
        <label>
          图例{" "}
          <Switch
            checked={config.presentation.show_legend}
            onChange={(checked) =>
              update({
                ...config,
                presentation: { ...config.presentation, show_legend: checked },
              })
            }
          />
        </label>
        <label>
          标签{" "}
          <Switch
            checked={config.presentation.show_labels}
            onChange={(checked) =>
              update({
                ...config,
                presentation: { ...config.presentation, show_labels: checked },
              })
            }
          />
        </label>
        <label>
          提示{" "}
          <Switch
            checked={config.presentation.show_tooltip}
            onChange={(checked) =>
              update({
                ...config,
                presentation: {
                  ...config.presentation,
                  show_tooltip: checked,
                },
              })
            }
          />
        </label>
      </div>
      <Form.Item label="主题">
        <Select
          value={config.presentation.theme}
          options={[
            { value: "light", label: "浅色" },
            { value: "dark", label: "深色" },
          ]}
          onChange={(theme: "light" | "dark") =>
            update({
              ...config,
              presentation: { ...config.presentation, theme },
            })
          }
        />
      </Form.Item>
      <FilterEditor
        label="组件筛选"
        value={config.component_filter}
        fieldOptions={fieldsQuery.fields}
        fieldsLoading={fieldsQuery.isLoading}
        onChange={(componentFilter) =>
          update({ ...config, component_filter: componentFilter })
        }
      />
    </div>
  );
}
