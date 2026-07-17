import {
  CheckCircleOutlined,
  FunctionOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  message,
  Select,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useState } from "react";

import { getDataset, listDatasets } from "../data-modeling/api";
import type { DatasetField } from "../data-modeling/types";
import { ApiError } from "../../shared/api/client";
import {
  createMetric,
  listIdentityRoles,
  listIdentityUsers,
  listMetrics,
  listRowPolicies,
  publishRowPolicy,
} from "./api";
import {
  countAggregateOptions,
  numericAggregateOptions,
  toMetricRequest,
  toPolicyRequest,
} from "./formContracts";
import type { MetricFormValues, PolicyFormValues } from "./formContracts";
import type { MetricSummary, RowPolicy } from "./types";

const metricKey = ["governance", "metrics"] as const;
const policyKey = ["governance", "row-policies"] as const;

export function GovernancePage() {
  return (
    <section className="governance-page" aria-labelledby="governance-title">
      <header className="governance-header">
        <div>
          <Typography.Title id="governance-title" level={2}>
            数据治理
          </Typography.Title>
          <Typography.Text type="secondary">
            维护公共指标口径，并按用户或角色发布数据访问规则
          </Typography.Text>
        </div>
        <div className="governance-state-chain" aria-label="规则发布流程">
          <span>定义</span>
          <i />
          <span>绑定</span>
          <i />
          <strong>生效</strong>
        </div>
      </header>
      <Tabs
        className="governance-tabs"
        defaultActiveKey="metrics"
        items={[
          {
            key: "metrics",
            label: "公共指标",
            icon: <FunctionOutlined />,
            children: <MetricsPanel />,
          },
          {
            key: "policies",
            label: "行级权限",
            icon: <SafetyCertificateOutlined />,
            children: <PoliciesPanel />,
          },
        ]}
      />
    </section>
  );
}

function MetricsPanel() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [datasetId, setDatasetId] = useState<string>();
  const [form] = Form.useForm<MetricFormValues>();
  const metrics = useQuery({ queryKey: metricKey, queryFn: listMetrics });
  const datasets = useQuery({
    queryKey: ["datasets", "governance"],
    queryFn: () => listDatasets(0, 100),
  });
  const dataset = useQuery({
    queryKey: ["datasets", datasetId],
    queryFn: () => getDataset(datasetId!),
    enabled: Boolean(datasetId),
  });
  const mutation = useMutation({
    mutationFn: (values: MetricFormValues) =>
      createMetric(toMetricRequest(values)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: metricKey });
      message.success("公共指标已创建");
      setDrawerOpen(false);
      form.resetFields();
      setDatasetId(undefined);
    },
  });
  const fields = (dataset.data?.fields ?? []).filter(isQueryableSourceField);
  const selectedFieldId = Form.useWatch("field_id", form);
  const selectedField = fields.find((field) => field.id === selectedFieldId);
  const aggregateOptions =
    selectedField && !isNumeric(selectedField)
      ? countAggregateOptions
      : numericAggregateOptions;

  const columns: ColumnsType<MetricSummary> = [
    {
      title: "指标",
      dataIndex: "name",
      render: (value, row) => (
        <div className="governance-name">
          <strong>{value}</strong>
          <span>
            {row.code} · v{row.version}
          </span>
        </div>
      ),
    },
    { title: "数据集", dataIndex: "dataset_name", width: 180 },
    { title: "负责人", dataIndex: "owner_name", width: 140 },
    {
      title: "单位",
      dataIndex: "unit",
      width: 90,
      render: (value) => value || "-",
    },
    { title: "状态", dataIndex: "status", width: 100, render: statusTag },
  ];

  return (
    <div className="governance-panel">
      <PanelToolbar
        title="指标目录"
        count={metrics.data?.total ?? 0}
        onCreate={() => setDrawerOpen(true)}
        createLabel="新建指标"
      />
      <QueryAlert error={metrics.error} retry={() => metrics.refetch()} />
      <Table
        rowKey="id"
        loading={metrics.isLoading}
        columns={columns}
        dataSource={metrics.data?.items ?? []}
        pagination={false}
        scroll={{ x: 720 }}
        locale={{ emptyText: <Empty description="还没有公共指标" /> }}
      />
      <Drawer
        title="新建公共指标"
        size="large"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            aggregate: "sum",
            status: "active",
            dimension_field_ids: [],
          }}
          onFinish={(values) => mutation.mutate(values)}
        >
          <Form.Item
            name="dataset_id"
            label="数据集"
            rules={[{ required: true }]}
          >
            <Select
              loading={datasets.isLoading}
              placeholder="选择已发布数据集"
              options={(datasets.data?.items ?? [])
                .filter((item) => item.status === "active")
                .map((item) => ({ value: item.id, label: item.name }))}
              onChange={(value) => {
                setDatasetId(value);
                form.setFieldsValue({
                  field_id: undefined,
                  dimension_field_ids: [],
                });
              }}
            />
          </Form.Item>
          <div className="governance-form-grid">
            <Form.Item
              name="name"
              label="指标名称"
              rules={[{ required: true, whitespace: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item
              name="code"
              label="指标编码"
              rules={[
                { required: true },
                {
                  pattern: /^[a-z][a-z0-9_]{0,62}$/,
                  message: "使用小写字母、数字和下划线",
                },
              ]}
            >
              <Input placeholder="sales_amount" />
            </Form.Item>
          </div>
          <Form.Item
            name="description"
            label="口径说明"
            rules={[{ required: true, whitespace: true }]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <div className="governance-form-grid">
            <Form.Item
              name="field_id"
              label="计算字段"
              rules={[{ required: true }]}
            >
              <Select
                loading={dataset.isLoading}
                options={fields.map(fieldOption)}
              />
            </Form.Item>
            <Form.Item
              name="aggregate"
              label="聚合方式"
              rules={[{ required: true }]}
            >
              <Select options={aggregateOptions} />
            </Form.Item>
          </div>
          <Form.Item name="dimension_field_ids" label="可用分析维度">
            <Select
              mode="multiple"
              options={fields
                .filter((field) => field.role === "dimension")
                .map(fieldOption)}
            />
          </Form.Item>
          <div className="governance-form-grid">
            <Form.Item name="unit" label="单位">
              <Input placeholder="元、户、%" />
            </Form.Item>
            <Form.Item name="status" label="创建状态">
              <Select
                options={[
                  { value: "active", label: "直接发布" },
                  { value: "draft", label: "保存草稿" },
                ]}
              />
            </Form.Item>
          </div>
          <MutationAlert mutation={mutation} />
          <Button
            block
            type="primary"
            htmlType="submit"
            icon={<PlusOutlined />}
            loading={mutation.isPending}
          >
            创建指标
          </Button>
        </Form>
      </Drawer>
    </div>
  );
}

function PoliciesPanel() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [datasetId, setDatasetId] = useState<string>();
  const [form] = Form.useForm<PolicyFormValues>();
  const policies = useQuery({ queryKey: policyKey, queryFn: listRowPolicies });
  const datasets = useQuery({
    queryKey: ["datasets", "governance"],
    queryFn: () => listDatasets(0, 100),
  });
  const users = useQuery({
    queryKey: ["identity", "users"],
    queryFn: listIdentityUsers,
  });
  const roles = useQuery({
    queryKey: ["identity", "roles"],
    queryFn: listIdentityRoles,
  });
  const dataset = useQuery({
    queryKey: ["datasets", datasetId],
    queryFn: () => getDataset(datasetId!),
    enabled: Boolean(datasetId),
  });
  const policyFields = (dataset.data?.fields ?? []).filter(
    isQueryableSourceField,
  );
  const mutation = useMutation({
    mutationFn: async (values: PolicyFormValues) => {
      if (!(values.user_ids?.length || values.role_ids?.length))
        throw new Error("至少选择一个用户或角色");
      return publishRowPolicy(
        toPolicyRequest(values, policyFields),
        values.user_ids ?? [],
        values.role_ids ?? [],
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: policyKey });
      message.success("行级权限已发布");
      setDrawerOpen(false);
      form.resetFields();
      setDatasetId(undefined);
    },
  });
  const columns: ColumnsType<RowPolicy> = [
    {
      title: "规则",
      dataIndex: "name",
      render: (value, row) => (
        <div className="governance-name">
          <strong>{value}</strong>
          <span>
            v{row.version} ·{" "}
            {row.effect === "allow" ? "允许匹配行" : "排除匹配行"}
          </span>
        </div>
      ),
    },
    {
      title: "绑定用户",
      dataIndex: "user_ids",
      width: 110,
      render: (value: string[]) => value.length,
    },
    {
      title: "绑定角色",
      dataIndex: "role_ids",
      width: 110,
      render: (value: string[]) => value.length,
    },
    { title: "状态", dataIndex: "status", width: 110, render: statusTag },
  ];
  return (
    <div className="governance-panel">
      <PanelToolbar
        title="访问规则"
        count={policies.data?.total ?? 0}
        onCreate={() => setDrawerOpen(true)}
        createLabel="新建规则"
      />
      <QueryAlert error={policies.error} retry={() => policies.refetch()} />
      <Table
        rowKey="id"
        loading={policies.isLoading}
        columns={columns}
        dataSource={policies.data?.items ?? []}
        pagination={false}
        scroll={{ x: 620 }}
        locale={{ emptyText: <Empty description="还没有行级权限规则" /> }}
      />
      <Drawer
        title="发布行级权限"
        size="large"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        destroyOnHidden
      >
        <div className="policy-flow">
          <span className="is-current">1 定义规则</span>
          <span>2 绑定对象</span>
          <span>3 自动生效</span>
        </div>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            effect: "allow",
            operator: "eq",
            user_ids: [],
            role_ids: [],
          }}
          onFinish={(values) => mutation.mutate(values)}
        >
          <Form.Item
            name="dataset_id"
            label="数据集"
            rules={[{ required: true }]}
          >
            <Select
              loading={datasets.isLoading}
              options={(datasets.data?.items ?? [])
                .filter((item) => item.status === "active")
                .map((item) => ({ value: item.id, label: item.name }))}
              onChange={(value) => {
                setDatasetId(value);
                form.setFieldValue("field_id", undefined);
              }}
            />
          </Form.Item>
          <div className="governance-form-grid">
            <Form.Item
              name="name"
              label="规则名称"
              rules={[{ required: true, whitespace: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item name="effect" label="匹配行处理">
              <Select
                options={[
                  { value: "allow", label: "允许访问" },
                  { value: "deny", label: "禁止访问" },
                ]}
              />
            </Form.Item>
          </div>
          <div className="policy-expression-grid">
            <Form.Item
              name="field_id"
              label="字段"
              rules={[{ required: true }]}
            >
              <Select
                loading={dataset.isLoading}
                options={policyFields.map(fieldOption)}
              />
            </Form.Item>
            <Form.Item name="operator" label="条件">
              <Select
                options={[
                  { value: "eq", label: "等于" },
                  { value: "ne", label: "不等于" },
                  { value: "gt", label: "大于" },
                  { value: "gte", label: "大于等于" },
                  { value: "lt", label: "小于" },
                  { value: "lte", label: "小于等于" },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="value"
              label="值"
              rules={[{ required: true, whitespace: true }]}
            >
              <Input />
            </Form.Item>
          </div>
          <Form.Item name="user_ids" label="绑定用户">
            <Select
              mode="multiple"
              loading={users.isLoading}
              options={(users.data ?? []).map((user) => ({
                value: user.id,
                label: `${user.display_name} (@${user.username})`,
              }))}
            />
          </Form.Item>
          <Form.Item name="role_ids" label="绑定角色">
            <Select
              mode="multiple"
              loading={roles.isLoading}
              options={(roles.data ?? []).map((role) => ({
                value: role.id,
                label: role.name,
              }))}
            />
          </Form.Item>
          <MutationAlert mutation={mutation} />
          <Button
            block
            type="primary"
            htmlType="submit"
            icon={<CheckCircleOutlined />}
            loading={mutation.isPending}
          >
            创建、绑定并发布
          </Button>
        </Form>
      </Drawer>
    </div>
  );
}

function PanelToolbar({
  title,
  count,
  onCreate,
  createLabel,
}: {
  title: string;
  count: number;
  onCreate: () => void;
  createLabel: string;
}) {
  return (
    <div className="governance-toolbar">
      <div>
        <Typography.Title level={4}>{title}</Typography.Title>
        <Typography.Text type="secondary">共 {count} 项</Typography.Text>
      </div>
      <Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>
        {createLabel}
      </Button>
    </div>
  );
}

function QueryAlert({ error, retry }: { error: unknown; retry: () => void }) {
  if (!error) return null;
  return (
    <Alert
      showIcon
      type="error"
      title="治理数据加载失败"
      description={errorText(error)}
      action={
        <Button size="small" onClick={retry}>
          重新加载
        </Button>
      }
    />
  );
}

function MutationAlert({
  mutation,
}: {
  mutation: { isError: boolean; error: unknown };
}) {
  return mutation.isError ? (
    <Alert
      className="governance-form-alert"
      showIcon
      type="error"
      title="操作未完成"
      description={errorText(mutation.error)}
    />
  ) : null;
}

function fieldOption(field: DatasetField) {
  return { value: field.id, label: `${field.label} (${field.data_type})` };
}
function isNumeric(field: DatasetField) {
  return field.data_type === "integer" || field.data_type === "decimal";
}
function isQueryableSourceField(field: DatasetField) {
  return field.field_kind === "calculated" || field.source_column_id !== null;
}
function statusTag(value: string) {
  const presentation: Record<string, { color: string; label: string }> = {
    active: { color: "success", label: "已生效" },
    draft: { color: "default", label: "草稿" },
    deprecated: { color: "warning", label: "已弃用" },
    disabled: { color: "warning", label: "已停用" },
  };
  const item = presentation[value] ?? { color: "default", label: value };
  return <Tag color={item.color}>{item.label}</Tag>;
}
function errorText(error: unknown) {
  if (error instanceof ApiError)
    return [error.message, error.action].filter(Boolean).join("；");
  if (error instanceof Error) return error.message;
  return "请稍后重试";
}
