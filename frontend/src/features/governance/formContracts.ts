import type { DatasetField } from "../data-modeling/types";
import type { CreateMetricRequest, CreateRowPolicyRequest } from "./types";

export const numericAggregateOptions = [
  { value: "sum", label: "求和" },
  { value: "avg", label: "平均值" },
  { value: "min", label: "最小值" },
  { value: "max", label: "最大值" },
  { value: "count", label: "计数" },
  { value: "count_distinct", label: "去重计数" },
];
export const countAggregateOptions = numericAggregateOptions.slice(-2);

export interface MetricFormValues {
  dataset_id: string;
  code: string;
  name: string;
  description: string;
  field_id: string;
  aggregate: string;
  dimension_field_ids?: string[];
  unit?: string;
  status: "draft" | "active";
}

export interface PolicyFormValues {
  dataset_id: string;
  name: string;
  effect: "allow" | "deny";
  field_id: string;
  operator: string;
  value: string;
  user_ids?: string[];
  role_ids?: string[];
}

export function toMetricRequest(values: MetricFormValues): CreateMetricRequest {
  return {
    dataset_id: values.dataset_id,
    code: values.code.trim(),
    name: values.name.trim(),
    description: values.description.trim(),
    formula: {
      op: "aggregate",
      function: values.aggregate,
      field_id: values.field_id,
    },
    unit: values.unit?.trim() || null,
    dimension_field_ids: values.dimension_field_ids ?? [],
    status: values.status,
  };
}

export function toPolicyRequest(
  values: PolicyFormValues,
  fields: DatasetField[],
): CreateRowPolicyRequest {
  const field = fields.find((item) => item.id === values.field_id);
  let value: string | number | boolean = values.value.trim();
  if (field?.data_type === "integer") {
    const parsed = Number(values.value);
    if (!Number.isFinite(parsed) || !Number.isInteger(parsed))
      throw new Error("策略条件值必须是有效整数");
    value = parsed;
  }
  if (field?.data_type === "decimal") {
    const parsed = Number(values.value);
    if (!Number.isFinite(parsed)) throw new Error("策略条件值必须是有效数值");
    value = parsed;
  }
  if (field?.data_type === "boolean") {
    const normalized = values.value.trim().toLowerCase();
    if (!["true", "false", "1", "0", "是", "否"].includes(normalized))
      throw new Error("策略条件值必须是有效布尔值");
    value = ["true", "1", "是"].includes(normalized);
  }
  return {
    dataset_id: values.dataset_id,
    name: values.name.trim(),
    effect: values.effect,
    expression: {
      kind: "comparison",
      field_id: values.field_id,
      operator: values.operator,
      value,
    },
  };
}
