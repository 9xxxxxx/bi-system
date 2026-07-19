import { Button, Input, Radio, Select, Space, Typography } from "antd";

import type {
  ComparisonOperator,
  RelativeDatePreset,
  ScopedFilter,
} from "../charts/types";
import type { DashboardFieldOption } from "./useDatasetFields";

type FilterMode = "value" | "relative" | "absolute";

function modeOf(value: ScopedFilter | null): FilterMode {
  if (value?.kind === "relative_date") return "relative";
  if (value?.kind === "absolute_date_range") return "absolute";
  return "value";
}

function filterFieldId(value: ScopedFilter | null): string {
  if (!value) return "";
  if (value.kind === "logical") return value.predicates[0]?.field_id ?? "";
  return value.field_id;
}

function withFieldId(value: ScopedFilter, fieldId: string): ScopedFilter {
  if (value.kind !== "logical") return { ...value, field_id: fieldId };
  const [first, ...rest] = value.predicates;
  return first
    ? { ...value, predicates: [{ ...first, field_id: fieldId }, ...rest] }
    : value;
}

export function FilterEditor({
  value,
  onChange,
  label,
  fieldOptions,
  fieldsLoading = false,
}: {
  value: ScopedFilter | null;
  onChange: (value: ScopedFilter | null) => void;
  label: string;
  fieldOptions: DashboardFieldOption[];
  fieldsLoading?: boolean;
}) {
  const mode = modeOf(value);
  const fieldId = filterFieldId(value);
  const dateMode = mode === "relative" || mode === "absolute";
  const availableFields = dateMode
    ? fieldOptions.filter(
        (field) => field.dataType === "date" || field.dataType === "datetime",
      )
    : fieldOptions;
  const selectedField = fieldOptions.find((field) => field.value === fieldId);
  return (
    <div className="dashboard-filter-editor">
      <Typography.Text strong>{label}</Typography.Text>
      <Radio.Group
        size="small"
        value={mode}
        optionType="button"
        options={[
          { value: "value", label: "字段值" },
          { value: "relative", label: "相对日期" },
          { value: "absolute", label: "绝对日期" },
        ]}
        onChange={(event) => {
          const next = event.target.value as FilterMode;
          const nextFieldId =
            next === "value" ||
            selectedField?.dataType === "date" ||
            selectedField?.dataType === "datetime"
              ? fieldId
              : "";
          if (next === "relative") {
            onChange({
              kind: "relative_date",
              field_id: nextFieldId,
              field_type:
                selectedField?.dataType === "datetime" ? "datetime" : "date",
              period: "last_30_days",
            });
          } else if (next === "absolute") {
            onChange({
              kind: "absolute_date_range",
              field_id: nextFieldId,
              field_type:
                selectedField?.dataType === "datetime" ? "datetime" : "date",
              start: "2026-01-01",
              end: "2026-02-01",
            });
          } else {
            onChange({
              kind: "comparison",
              field_id: fieldId,
              operator: "eq",
              value: "",
            });
          }
        }}
      />
      <Select
        showSearch
        aria-label={`${label}字段`}
        placeholder={dateMode ? "选择日期字段" : "选择字段"}
        loading={fieldsLoading}
        value={fieldId || undefined}
        optionFilterProp="label"
        options={availableFields}
        onChange={(nextFieldId: string) => {
          const nextField = fieldOptions.find(
            (field) => field.value === nextFieldId,
          );
          if (!value) {
            onChange({
              kind: "comparison",
              field_id: nextFieldId,
              operator: "eq",
              value: "",
            });
          } else if (
            value.kind === "relative_date" ||
            value.kind === "absolute_date_range"
          ) {
            onChange({
              ...value,
              field_id: nextFieldId,
              field_type:
                nextField?.dataType === "datetime" ? "datetime" : "date",
            });
          } else {
            onChange(withFieldId(value, nextFieldId));
          }
        }}
      />
      {mode === "relative" ? (
        <Space.Compact block>
          <Select
            aria-label={`${label}相对日期`}
            value={
              value?.kind === "relative_date" ? value.period : "last_30_days"
            }
            options={(
              [
                "today",
                "yesterday",
                "last_7_days",
                "last_30_days",
                "this_week",
                "last_week",
                "this_month",
                "last_month",
                "month_to_date",
                "year_to_date",
              ] as RelativeDatePreset[]
            ).map((period) => ({ value: period, label: period }))}
            onChange={(period: RelativeDatePreset) =>
              value?.kind === "relative_date" && onChange({ ...value, period })
            }
          />
        </Space.Compact>
      ) : mode === "absolute" ? (
        <>
          <Space.Compact block>
            <Input
              type="date"
              aria-label={`${label}开始日期`}
              value={value?.kind === "absolute_date_range" ? value.start : ""}
              onChange={(event) =>
                value?.kind === "absolute_date_range" &&
                onChange({ ...value, start: event.target.value })
              }
            />
            <Input
              type="date"
              aria-label={`${label}结束日期`}
              value={value?.kind === "absolute_date_range" ? value.end : ""}
              onChange={(event) =>
                value?.kind === "absolute_date_range" &&
                onChange({ ...value, end: event.target.value })
              }
            />
          </Space.Compact>
        </>
      ) : (
        <Space.Compact block>
          <Select
            aria-label={`${label}运算符`}
            value={value?.kind === "comparison" ? value.operator : "eq"}
            options={(
              [
                ["eq", "等于"],
                ["ne", "不等于"],
                ["gt", "大于"],
                ["gte", "大于等于"],
                ["lt", "小于"],
                ["lte", "小于等于"],
              ] as Array<[ComparisonOperator, string]>
            ).map(([operator, operatorLabel]) => ({
              value: operator,
              label: operatorLabel,
            }))}
            onChange={(operator: ComparisonOperator) =>
              onChange({
                kind: "comparison",
                field_id: fieldId,
                operator,
                value: value?.kind === "comparison" ? value.value : "",
              })
            }
          />
          <Input
            aria-label={`${label}值`}
            value={value?.kind === "comparison" ? String(value.value) : ""}
            onChange={(event) =>
              onChange({
                kind: "comparison",
                field_id: fieldId,
                operator: value?.kind === "comparison" ? value.operator : "eq",
                value: event.target.value,
              })
            }
          />
        </Space.Compact>
      )}
      <Button size="small" disabled={!value} onClick={() => onChange(null)}>
        清除{label}
      </Button>
    </div>
  );
}
