import {
  CloudUploadOutlined,
  DatabaseOutlined,
  FileExcelOutlined,
  InboxOutlined,
  PlusOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Checkbox,
  Descriptions,
  Divider,
  Empty,
  Input,
  Radio,
  Select,
  Space,
  Steps,
  Switch,
  Table,
  Tag,
  Typography,
  Upload,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";

import { ApiError } from "../../shared/api/client";
import {
  cancelImportBatch,
  confirmImportWarnings,
  createImportBatch,
  createImportTemplate,
  getImportBatch,
  getImportIssues,
  getImportReportUrl,
  listImportBatches,
  listImportTemplates,
  previewSourceFile,
  retryImportBatch,
  uploadSourceFile,
} from "./api";
import { ImportBatchStatusPanel } from "./ImportBatchStatusPanel";
import type {
  ColumnMapping,
  FileDataType,
  ImportBatch,
  ImportDefinition,
  ImportMode,
  ImportTemplate,
  QualityRule,
  SourceFile,
  SourcePreview,
} from "./types";

const dataTypeOptions = [
  { value: "string", label: "文本" },
  { value: "integer", label: "整数" },
  { value: "decimal", label: "小数" },
  { value: "boolean", label: "布尔" },
  { value: "date", label: "日期" },
  { value: "datetime", label: "日期时间" },
];

const stepItems = [
  { title: "文件" },
  { title: "预览" },
  { title: "映射" },
  { title: "规则" },
  { title: "执行" },
  { title: "结果" },
];

type RuleSelections = Record<"required" | "unique" | "dataType", string[]>;
type BatchAction = "cancel" | "retry" | "confirm";

function normalizedTargetName(sourceName: string, index: number): string {
  const normalized = sourceName
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^[0-9]/, "column_$&")
    .slice(0, 63);
  return normalized || `column_${index + 1}`;
}

function mappingsFromPreview(preview: SourcePreview): ColumnMapping[] {
  return preview.columns.map((column, index) => ({
    source_key: column.key,
    source_name: column.source_name,
    target_name: normalizedTargetName(column.source_name, index),
    data_type: column.inferred_type,
    nullable: column.null_count > 0,
  }));
}

function errorDescription(error: unknown): string {
  if (error instanceof ApiError) {
    return [error.message, error.action].filter(Boolean).join("；");
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "请求失败，请稍后重试";
}

function selectionsFromTemplate(template: ImportTemplate): RuleSelections {
  return {
    required: template.definition.quality_rules
      .filter((rule) => rule.rule_type === "required")
      .flatMap((rule) => (rule.column_name ? [rule.column_name] : [])),
    unique: template.definition.quality_rules
      .filter((rule) => rule.rule_type === "unique")
      .flatMap((rule) => (rule.column_name ? [rule.column_name] : [])),
    dataType: template.definition.quality_rules
      .filter((rule) => rule.rule_type === "data_type")
      .flatMap((rule) => (rule.column_name ? [rule.column_name] : [])),
  };
}

function buildRules(
  mappings: ColumnMapping[],
  selections: RuleSelections,
  businessKeys: string[],
): QualityRule[] {
  const rules: QualityRule[] = [];
  for (const mapping of mappings) {
    if (selections.required.includes(mapping.target_name)) {
      rules.push({
        name: `required_${mapping.target_name}`,
        rule_type: "required",
        severity: "error",
        column_name: mapping.target_name,
        parameters: {},
      });
    }
    if (selections.unique.includes(mapping.target_name)) {
      rules.push({
        name: `unique_${mapping.target_name}`,
        rule_type: "unique",
        severity: "error",
        column_name: mapping.target_name,
        parameters: {},
      });
    }
    if (selections.dataType.includes(mapping.target_name)) {
      rules.push({
        name: `type_${mapping.target_name}`,
        rule_type: "data_type",
        severity: "error",
        column_name: mapping.target_name,
        parameters: { expected_type: mapping.data_type },
      });
    }
  }
  if (businessKeys.length > 0) {
    rules.push({
      name: "business_key_unique",
      rule_type: "business_key",
      severity: "error",
      column_name: null,
      parameters: { columns: businessKeys },
    });
  }
  return rules;
}

export function DataIngestionPage() {
  const queryClient = useQueryClient();
  const [currentStep, setCurrentStep] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File>();
  const [sourceFile, setSourceFile] = useState<SourceFile>();
  const [preview, setPreview] = useState<SourcePreview>();
  const [encoding, setEncoding] = useState("utf-8-sig");
  const [sheetName, setSheetName] = useState<string | null>(null);
  const [flowType, setFlowType] = useState<"wizard" | "template">("wizard");
  const [templateId, setTemplateId] = useState<string>();
  const [mappings, setMappings] = useState<ColumnMapping[]>([]);
  const [businessKeys, setBusinessKeys] = useState<string[]>([]);
  const [ruleSelections, setRuleSelections] = useState<RuleSelections>({
    required: [],
    unique: [],
    dataType: [],
  });
  const [saveTemplate, setSaveTemplate] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [targetType, setTargetType] = useState<"new" | "existing">("new");
  const [targetName, setTargetName] = useState("");
  const [targetId, setTargetId] = useState<string>();
  const [importMode, setImportMode] = useState<ImportMode>("append");
  const [createdBatch, setCreatedBatch] = useState<ImportBatch>();
  const [issuePage, setIssuePage] = useState(1);

  const templatesQuery = useQuery({
    queryKey: ["import-templates"],
    queryFn: listImportTemplates,
  });
  const batchesQuery = useQuery({
    queryKey: ["import-batches"],
    queryFn: listImportBatches,
  });
  const selectedTemplate = templatesQuery.data?.find(
    (template) => template.id === templateId,
  );
  const existingTargets = useMemo(() => {
    const targets = new Map<string, ImportBatch["target"]>();
    for (const batch of batchesQuery.data ?? []) {
      targets.set(batch.target.id, batch.target);
    }
    return [...targets.values()];
  }, [batchesQuery.data]);

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const uploaded = await uploadSourceFile(file);
      const filePreview = await previewSourceFile(uploaded.id, {
        encoding,
        sheet_name: selectedTemplate?.definition.sheet_name ?? null,
      });
      return { uploaded, filePreview };
    },
    onSuccess: ({ uploaded, filePreview }) => {
      setSourceFile(uploaded);
      setPreview(filePreview);
      setSheetName(filePreview.selected_sheet);
      if (selectedTemplate) {
        setMappings(selectedTemplate.definition.columns);
        setBusinessKeys(selectedTemplate.definition.business_key);
        setRuleSelections(selectionsFromTemplate(selectedTemplate));
      } else {
        setMappings(mappingsFromPreview(filePreview));
        setBusinessKeys([]);
        setRuleSelections({ required: [], unique: [], dataType: [] });
      }
      setTargetName(uploaded.original_name.replace(/\.[^.]+$/, ""));
      setCurrentStep(1);
    },
  });

  const previewMutation = useMutation({
    mutationFn: (selectedSheet: string | null) => {
      if (!sourceFile) {
        throw new Error("请先上传文件");
      }
      return previewSourceFile(sourceFile.id, {
        encoding,
        sheet_name: selectedSheet,
      });
    },
    onSuccess: (nextPreview) => {
      setPreview(nextPreview);
      setSheetName(nextPreview.selected_sheet);
      if (!selectedTemplate) {
        setMappings(mappingsFromPreview(nextPreview));
        setBusinessKeys([]);
        setRuleSelections({ required: [], unique: [], dataType: [] });
      }
    },
  });

  const createBatchMutation = useMutation({
    mutationFn: async () => {
      if (!sourceFile || !preview) {
        throw new Error("缺少源文件或预览信息");
      }
      const definition: ImportDefinition = selectedTemplate
        ? selectedTemplate.definition
        : {
            file_kind: preview.file_kind,
            sheet_name: preview.selected_sheet,
            header_row: 1,
            columns: mappings,
            business_key: businessKeys,
            quality_rules: buildRules(mappings, ruleSelections, businessKeys),
          };
      let storedTemplateId = selectedTemplate?.id;
      if (!storedTemplateId && saveTemplate) {
        const stored = await createImportTemplate(
          templateName.trim(),
          definition,
        );
        storedTemplateId = stored.id;
        await queryClient.invalidateQueries({ queryKey: ["import-templates"] });
      }
      return createImportBatch({
        source_file_id: sourceFile.id,
        ...(storedTemplateId
          ? { template_id: storedTemplateId }
          : { definition }),
        ...(targetType === "existing"
          ? { target_id: targetId }
          : { target_name: targetName.trim() }),
        mode: importMode,
        encoding,
        warnings_confirmed: false,
      });
    },
    onSuccess: (batch) => {
      setCreatedBatch(batch);
      setCurrentStep(5);
      void queryClient.invalidateQueries({ queryKey: ["import-batches"] });
    },
  });

  const batchQuery = useQuery({
    queryKey: ["import-batch", createdBatch?.id],
    queryFn: () => getImportBatch(createdBatch!.id),
    enabled: Boolean(createdBatch?.id),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "processing" ? 1500 : false;
    },
  });
  const batch = batchQuery.data ?? createdBatch;
  const issueLimit = 20;
  const issuesQuery = useQuery({
    queryKey: ["import-batch", batch?.id, "issues", issuePage],
    queryFn: () =>
      getImportIssues(batch!.id, (issuePage - 1) * issueLimit, issueLimit),
    enabled: Boolean(batch && batch.error_rows + batch.warning_rows > 0),
  });
  const actionMutation = useMutation({
    mutationFn: ({
      action,
      batchId,
    }: {
      action: BatchAction;
      batchId: string;
    }) => {
      if (action === "cancel") return cancelImportBatch(batchId);
      if (action === "retry") return retryImportBatch(batchId);
      return confirmImportWarnings(batchId);
    },
    onSuccess: (updated) => {
      setCreatedBatch(updated);
      queryClient.setQueryData(["import-batch", updated.id], updated);
    },
  });

  const mappingColumns: ColumnsType<ColumnMapping> = [
    { title: "源字段", dataIndex: "source_name", width: 180, ellipsis: true },
    {
      title: "目标字段",
      dataIndex: "target_name",
      width: 220,
      render: (value, record, index) => (
        <Input
          aria-label={`${record.source_name}目标字段`}
          value={value}
          disabled={Boolean(selectedTemplate)}
          onChange={(event) => {
            const oldName = record.target_name;
            const nextName = event.target.value;
            setBusinessKeys((keys) =>
              keys.map((key) => (key === oldName ? nextName : key)),
            );
            setRuleSelections((selections) => ({
              required: selections.required.map((name) =>
                name === oldName ? nextName : name,
              ),
              unique: selections.unique.map((name) =>
                name === oldName ? nextName : name,
              ),
              dataType: selections.dataType.map((name) =>
                name === oldName ? nextName : name,
              ),
            }));
            setMappings((current) =>
              current.map((mapping, mappingIndex) =>
                mappingIndex === index
                  ? { ...mapping, target_name: nextName }
                  : mapping,
              ),
            );
          }}
        />
      ),
    },
    {
      title: "数据类型",
      dataIndex: "data_type",
      width: 150,
      render: (value, _record, index) => (
        <Select
          aria-label="数据类型"
          value={value}
          options={dataTypeOptions}
          disabled={Boolean(selectedTemplate)}
          onChange={(next: FileDataType) =>
            setMappings((current) =>
              current.map((mapping, mappingIndex) =>
                mappingIndex === index
                  ? { ...mapping, data_type: next }
                  : mapping,
              ),
            )
          }
        />
      ),
    },
    {
      title: "允许空值",
      dataIndex: "nullable",
      width: 110,
      align: "center",
      render: (value, _record, index) => (
        <Switch
          aria-label="允许空值"
          checked={value}
          disabled={Boolean(selectedTemplate)}
          onChange={(checked) =>
            setMappings((current) =>
              current.map((mapping, mappingIndex) =>
                mappingIndex === index
                  ? { ...mapping, nullable: checked }
                  : mapping,
              ),
            )
          }
        />
      ),
    },
  ];

  const previewColumns: ColumnsType<
    Record<string, string | number | boolean | null>
  > = (preview?.columns ?? []).map((column) => ({
    title: (
      <Space size={4} orientation="vertical">
        <span>{column.source_name}</span>
        <Typography.Text type="secondary" className="column-meta">
          {column.inferred_type} · 空值 {column.null_count}
        </Typography.Text>
      </Space>
    ),
    dataIndex: column.key,
    width: 180,
    ellipsis: true,
    render: (value) => String(value ?? ""),
  }));

  const rulesColumns: ColumnsType<ColumnMapping> = [
    { title: "目标字段", dataIndex: "target_name", ellipsis: true },
    ...(["required", "unique", "dataType"] as const).map((rule) => ({
      title: { required: "必填", unique: "唯一", dataType: "类型校验" }[rule],
      width: 110,
      align: "center" as const,
      render: (_value: unknown, record: ColumnMapping) => (
        <Checkbox
          aria-label={`${record.target_name}${rule}`}
          checked={ruleSelections[rule].includes(record.target_name)}
          disabled={Boolean(selectedTemplate)}
          onChange={(event) =>
            setRuleSelections((current) => ({
              ...current,
              [rule]: event.target.checked
                ? [...current[rule], record.target_name]
                : current[rule].filter((name) => name !== record.target_name),
            }))
          }
        />
      ),
    })),
  ];

  const canContinueMapping =
    mappings.length > 0 &&
    mappings.every((mapping) =>
      /^[a-z][a-z0-9_]{0,62}$/.test(mapping.target_name),
    ) &&
    new Set(mappings.map((mapping) => mapping.target_name)).size ===
      mappings.length;
  const canCreateBatch =
    (targetType === "new" ? Boolean(targetName.trim()) : Boolean(targetId)) &&
    (importMode !== "upsert" || businessKeys.length > 0) &&
    (!saveTemplate || Boolean(templateName.trim()));

  function renderStep() {
    if (currentStep === 0) {
      return (
        <div className="wizard-section upload-section">
          <div className="section-heading">
            <div>
              <Typography.Title level={3}>选择导入来源</Typography.Title>
              <Typography.Text type="secondary">
                支持 CSV 与 XLSX，单文件最大 100 MB。
              </Typography.Text>
            </div>
            <Radio.Group
              value={flowType}
              optionType="button"
              buttonStyle="solid"
              onChange={(event) => {
                setFlowType(event.target.value as "wizard" | "template");
                if (event.target.value === "wizard") setTemplateId(undefined);
              }}
              options={[
                { label: "通用向导", value: "wizard" },
                { label: "固定模板", value: "template" },
              ]}
            />
          </div>
          {flowType === "template" && (
            <Select
              className="template-select"
              aria-label="固定模板"
              placeholder="选择已保存模板"
              loading={templatesQuery.isLoading}
              value={templateId}
              onChange={setTemplateId}
              notFoundContent={
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无模板"
                />
              }
              options={(templatesQuery.data ?? []).map((template) => ({
                value: template.id,
                label: `${template.name} · v${template.version}`,
              }))}
            />
          )}
          <Upload.Dragger
            accept=".csv,.xlsx"
            maxCount={1}
            beforeUpload={(file) => {
              setSelectedFile(file);
              return false;
            }}
            onRemove={() => {
              setSelectedFile(undefined);
            }}
            fileList={selectedFile ? ([selectedFile] as never[]) : []}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">拖放文件到此处，或点击选择文件</p>
            <p className="ant-upload-hint">
              文件内容会按 SHA256 去重并保留原始版本
            </p>
          </Upload.Dragger>
          {uploadMutation.isError && (
            <Alert
              type="error"
              showIcon
              title="上传或预览失败"
              description={errorDescription(uploadMutation.error)}
            />
          )}
          <div className="wizard-actions">
            <Button
              type="primary"
              icon={<CloudUploadOutlined />}
              size="large"
              disabled={
                !selectedFile || (flowType === "template" && !templateId)
              }
              loading={uploadMutation.isPending}
              onClick={() =>
                selectedFile && uploadMutation.mutate(selectedFile)
              }
            >
              上传并预览
            </Button>
          </div>
        </div>
      );
    }

    if (currentStep === 1 && preview && sourceFile) {
      return (
        <div className="wizard-section">
          <div className="section-heading">
            <div>
              <Typography.Title level={3}>检查文件内容</Typography.Title>
              <Typography.Text type="secondary">
                {sourceFile.original_name}
              </Typography.Text>
            </div>
            {sourceFile.duplicate && <Tag color="blue">已复用重复文件</Tag>}
          </div>
          <Space wrap>
            {preview.file_kind === "csv" && (
              <Select
                aria-label="CSV 编码"
                value={encoding}
                options={[
                  { value: "utf-8-sig", label: "UTF-8 / BOM" },
                  { value: "utf-8", label: "UTF-8" },
                  { value: "gb18030", label: "GB18030" },
                ]}
                onChange={(value) => {
                  setEncoding(value);
                  previewMutation.mutate(null);
                }}
              />
            )}
            {preview.file_kind === "xlsx" && (
              <Select
                aria-label="工作表"
                value={sheetName}
                options={preview.sheet_names.map((name) => ({
                  value: name,
                  label: name,
                }))}
                onChange={(value) => {
                  setSheetName(value);
                  previewMutation.mutate(value);
                }}
              />
            )}
            <Tag>{preview.columns.length} 个字段</Tag>
            <Tag>{preview.rows.length} 行样例</Tag>
          </Space>
          <Table
            className="preview-table"
            rowKey="__rowIndex"
            loading={previewMutation.isPending}
            columns={previewColumns}
            dataSource={preview.rows.map((row, index) => ({
              ...row,
              __rowIndex: index,
            }))}
            scroll={{ x: Math.max(720, previewColumns.length * 180) }}
            pagination={{ pageSize: 10, hideOnSinglePage: true }}
          />
          {preview.truncated && (
            <Alert
              type="info"
              showIcon
              title="仅展示前 100 行，完整文件将在后台分块处理"
            />
          )}
          <div className="wizard-actions split-actions">
            <Button onClick={() => setCurrentStep(0)}>上一步</Button>
            <Button type="primary" onClick={() => setCurrentStep(2)}>
              确认预览
            </Button>
          </div>
        </div>
      );
    }

    if (currentStep === 2) {
      return (
        <div className="wizard-section">
          <div className="section-heading">
            <div>
              <Typography.Title level={3}>字段映射</Typography.Title>
              <Typography.Text type="secondary">
                目标字段使用小写英文 snake_case，名称必须唯一。
              </Typography.Text>
            </div>
            {selectedTemplate && <Tag color="blue">固定模板只读</Tag>}
          </div>
          <Table
            rowKey="source_key"
            size="small"
            columns={mappingColumns}
            dataSource={mappings}
            scroll={{ x: 720 }}
            pagination={false}
          />
          {!canContinueMapping && (
            <Alert
              type="warning"
              showIcon
              title="请修正无效或重复的目标字段名称"
            />
          )}
          <div className="business-key-field">
            <Typography.Text strong>业务主键</Typography.Text>
            <Select
              mode="multiple"
              aria-label="业务主键"
              placeholder="按业务主键更新时必须选择"
              disabled={Boolean(selectedTemplate)}
              value={businessKeys}
              onChange={setBusinessKeys}
              options={mappings.map((mapping) => ({
                value: mapping.target_name,
                label: mapping.target_name,
              }))}
            />
          </div>
          <div className="wizard-actions split-actions">
            <Button onClick={() => setCurrentStep(1)}>上一步</Button>
            <Button
              type="primary"
              disabled={!canContinueMapping}
              onClick={() => setCurrentStep(3)}
            >
              配置质量规则
            </Button>
          </div>
        </div>
      );
    }

    if (currentStep === 3) {
      return (
        <div className="wizard-section">
          <div className="section-heading">
            <div>
              <Typography.Title level={3}>质量规则</Typography.Title>
              <Typography.Text type="secondary">
                错误会阻止提交；业务主键会自动检查批次内重复。
              </Typography.Text>
            </div>
          </div>
          <Table
            rowKey="source_key"
            size="small"
            columns={rulesColumns}
            dataSource={mappings}
            scroll={{ x: 560 }}
            pagination={false}
          />
          <div className="wizard-actions split-actions">
            <Button onClick={() => setCurrentStep(2)}>上一步</Button>
            <Button type="primary" onClick={() => setCurrentStep(4)}>
              选择执行方式
            </Button>
          </div>
        </div>
      );
    }

    if (currentStep === 4) {
      return (
        <div className="wizard-section execution-section">
          <div className="section-heading">
            <div>
              <Typography.Title level={3}>目标与导入模式</Typography.Title>
              <Typography.Text type="secondary">
                提交后由后台 worker 分块执行，可取消并从检查点重试。
              </Typography.Text>
            </div>
          </div>
          <div className="execution-grid">
            <div className="execution-field">
              <Typography.Text strong>数据目标</Typography.Text>
              <Radio.Group
                value={targetType}
                onChange={(event) => setTargetType(event.target.value)}
              >
                <Radio value="new">
                  <PlusOutlined /> 新建目标
                </Radio>
                <Radio value="existing" disabled={existingTargets.length === 0}>
                  <DatabaseOutlined /> 已有目标
                </Radio>
              </Radio.Group>
              {targetType === "new" ? (
                <Input
                  aria-label="目标名称"
                  value={targetName}
                  maxLength={128}
                  placeholder="目标名称"
                  onChange={(event) => setTargetName(event.target.value)}
                />
              ) : (
                <Select
                  aria-label="已有目标"
                  value={targetId}
                  placeholder="选择已有目标"
                  onChange={setTargetId}
                  options={existingTargets.map((target) => ({
                    value: target.id,
                    label: `${target.name} · ${target.physical_table_name}`,
                  }))}
                />
              )}
            </div>
            <div className="execution-field">
              <Typography.Text strong>导入模式</Typography.Text>
              <Radio.Group
                value={importMode}
                onChange={(event) => setImportMode(event.target.value)}
              >
                <Radio value="append">追加</Radio>
                <Radio value="upsert" disabled={businessKeys.length === 0}>
                  按业务主键更新
                </Radio>
                <Radio value="replace">全量替换</Radio>
              </Radio.Group>
              {businessKeys.length === 0 && (
                <Typography.Text type="secondary">
                  配置业务主键后可使用更新模式。
                </Typography.Text>
              )}
            </div>
          </div>
          {!selectedTemplate && (
            <div className="template-save-row">
              <Checkbox
                checked={saveTemplate}
                onChange={(event) => setSaveTemplate(event.target.checked)}
              >
                保存为固定模板
              </Checkbox>
              {saveTemplate && (
                <Input
                  aria-label="模板名称"
                  value={templateName}
                  maxLength={128}
                  placeholder="模板名称"
                  onChange={(event) => setTemplateName(event.target.value)}
                />
              )}
            </div>
          )}
          <Divider />
          <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 3 }}>
            <Descriptions.Item label="文件">
              {sourceFile?.original_name}
            </Descriptions.Item>
            <Descriptions.Item label="字段">
              {mappings.length}
            </Descriptions.Item>
            <Descriptions.Item label="规则">
              {selectedTemplate?.definition.quality_rules.length ??
                buildRules(mappings, ruleSelections, businessKeys).length}
            </Descriptions.Item>
            <Descriptions.Item label="模式">{importMode}</Descriptions.Item>
            <Descriptions.Item label="业务主键">
              {businessKeys.join(", ") || "未设置"}
            </Descriptions.Item>
            <Descriptions.Item label="来源">
              {selectedTemplate
                ? `${selectedTemplate.name} v${selectedTemplate.version}`
                : "通用向导"}
            </Descriptions.Item>
          </Descriptions>
          {createBatchMutation.isError && (
            <Alert
              type="error"
              showIcon
              title="创建批次失败"
              description={errorDescription(createBatchMutation.error)}
            />
          )}
          <div className="wizard-actions split-actions">
            <Button onClick={() => setCurrentStep(3)}>上一步</Button>
            <Button
              type="primary"
              icon={<FileExcelOutlined />}
              disabled={!canCreateBatch}
              loading={createBatchMutation.isPending}
              onClick={() => createBatchMutation.mutate()}
            >
              创建导入批次
            </Button>
          </div>
        </div>
      );
    }

    return (
      <div className="wizard-section">
        <div className="section-heading">
          <div>
            <Typography.Title level={3}>导入结果</Typography.Title>
            <Typography.Text type="secondary">批次 {batch?.id}</Typography.Text>
          </div>
          <Button onClick={() => window.location.reload()}>发起新导入</Button>
        </div>
        <ImportBatchStatusPanel
          batch={batch}
          loading={batchQuery.isLoading}
          issues={issuesQuery.data}
          issuesLoading={issuesQuery.isLoading}
          issuePage={issuePage}
          actionLoading={actionMutation.isPending}
          onIssuePageChange={setIssuePage}
          onAction={(action) =>
            batch && actionMutation.mutate({ action, batchId: batch.id })
          }
          reportUrl={batch ? getImportReportUrl(batch.id) : undefined}
        />
      </div>
    );
  }

  return (
    <div className="ingestion-workspace">
      <div className="ingestion-overview">
        <div>
          <Typography.Title level={2}>数据导入</Typography.Title>
          <Typography.Text type="secondary">
            上传、治理并追踪 CSV/XLSX 数据批次
          </Typography.Text>
        </div>
        <Space>
          <Tag>{templatesQuery.data?.length ?? 0} 个模板</Tag>
          <Tag>{existingTargets.length} 个目标</Tag>
        </Space>
      </div>
      <Steps
        current={currentStep}
        items={stepItems}
        responsive
        className="ingestion-steps"
      />
      {renderStep()}
    </div>
  );
}
