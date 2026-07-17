import { CalculatorOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import { ApiError } from "../../shared/api/client";
import { createCalculatedField } from "./api";
import { parseCalculatedLiteral } from "./calculatedFieldContracts";
import type {
  CalculatedExpression,
  CreateCalculatedFieldRequest,
  DatasetDetail,
  DatasetField,
  DatasetFieldRole,
} from "./types";

type CalculationMode = "arithmetic" | "case";
type ArithmeticOperator = "add" | "subtract" | "multiply" | "safe_divide";
type ResultType = CreateCalculatedFieldRequest["data_type"];
type ComparisonOperator = "eq" | "ne" | "gt" | "gte" | "lt" | "lte";

interface CalculatedFieldEditorProps {
  dataset: DatasetDetail;
  mobileReadonly: boolean;
  onCreated: (dataset: DatasetDetail) => void;
}

function errorDescription(error: unknown): string {
  if (error instanceof ApiError) {
    return [error.message, error.action].filter(Boolean).join("；");
  }
  return error instanceof Error
    ? error.message
    : "计算字段创建失败，请稍后重试";
}

export function CalculatedFieldEditor({
  dataset,
  mobileReadonly,
  onCreated,
}: CalculatedFieldEditorProps) {
  const initialVisibleFields = dataset.fields.filter((field) => !field.hidden);
  const initialNumericFields = initialVisibleFields.filter(
    (field) => field.data_type === "integer" || field.data_type === "decimal",
  );
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [role, setRole] = useState<DatasetFieldRole>("measure");
  const [dataType, setDataType] = useState<ResultType>("decimal");
  const [mode, setMode] = useState<CalculationMode>("arithmetic");
  const [arithmeticOperator, setArithmeticOperator] =
    useState<ArithmeticOperator>("safe_divide");
  const [leftFieldId, setLeftFieldId] = useState<string | undefined>(
    initialNumericFields[0]?.id,
  );
  const [rightFieldId, setRightFieldId] = useState<string | undefined>(
    initialNumericFields[1]?.id ?? initialNumericFields[0]?.id,
  );
  const [caseFieldId, setCaseFieldId] = useState<string | undefined>(
    initialVisibleFields[0]?.id,
  );
  const [comparisonOperator, setComparisonOperator] =
    useState<ComparisonOperator>("eq");
  const [comparisonValue, setComparisonValue] = useState("");
  const [thenValue, setThenValue] = useState("");
  const [elseValue, setElseValue] = useState("");

  const visibleFields = useMemo(
    () => dataset.fields.filter((field) => !field.hidden),
    [dataset.fields],
  );
  const numericFields = visibleFields.filter(
    (field) => field.data_type === "integer" || field.data_type === "decimal",
  );
  const fieldOptions = visibleFields.map(fieldOption);
  const numericOptions = numericFields.map(fieldOption);
  const mutation = useMutation({
    mutationFn: () =>
      createCalculatedField(dataset.id, {
        name: name.trim(),
        label: label.trim(),
        role,
        data_type: dataType,
        hidden: false,
        expression: buildExpression(),
      }),
    onSuccess: (created) => {
      setOpen(false);
      onCreated(created);
    },
  });

  function buildExpression(): CalculatedExpression {
    if (mode === "arithmetic") {
      if (!leftFieldId || !rightFieldId) throw new Error("请选择两个计算字段");
      const left = { op: "field" as const, field_id: leftFieldId };
      const right = { op: "field" as const, field_id: rightFieldId };
      return arithmeticOperator === "safe_divide"
        ? {
            op: "safe_divide",
            numerator: left,
            denominator: right,
            fallback: null,
          }
        : { op: arithmeticOperator, left, right };
    }
    if (!caseFieldId) throw new Error("请选择判断字段");
    const comparisonField = visibleFields.find(
      (field) => field.id === caseFieldId,
    );
    if (!comparisonField) throw new Error("判断字段不存在");
    return {
      op: "case",
      when: {
        kind: "comparison",
        field_id: caseFieldId,
        operator: comparisonOperator,
        value: parseCalculatedLiteral(
          comparisonValue,
          comparisonField.data_type,
        ),
      },
      then: {
        op: "literal",
        value: parseCalculatedLiteral(thenValue, dataType),
      },
      else: {
        op: "literal",
        value: parseCalculatedLiteral(elseValue, dataType),
      },
    };
  }

  const expressionReady =
    mode === "arithmetic"
      ? Boolean(leftFieldId && rightFieldId)
      : Boolean(
          caseFieldId &&
          comparisonValue.trim() &&
          thenValue.trim() &&
          elseValue.trim(),
        );
  const canSubmit = Boolean(name.trim() && label.trim() && expressionReady);

  return (
    <>
      <Button
        icon={<CalculatorOutlined />}
        disabled={mobileReadonly}
        onClick={() => setOpen(true)}
      >
        计算字段
      </Button>
      <Modal
        open={open}
        title="创建计算字段"
        width={640}
        destroyOnHidden
        onCancel={() => setOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setOpen(false)}>
            取消
          </Button>,
          <Button
            key="create"
            type="primary"
            loading={mutation.isPending}
            disabled={!canSubmit}
            onClick={() => mutation.mutate()}
          >
            创建新版本
          </Button>,
        ]}
      >
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          {mutation.isError && (
            <Alert
              type="error"
              showIcon
              title="计算字段创建失败"
              description={errorDescription(mutation.error)}
            />
          )}
          <Space wrap style={{ width: "100%" }}>
            <label>
              <Typography.Text strong>字段名称</Typography.Text>
              <Input
                aria-label="计算字段名称"
                placeholder="例如：profit_rate"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              <Typography.Text strong>显示标签</Typography.Text>
              <Input
                aria-label="计算字段标签"
                placeholder="例如：利润率"
                value={label}
                onChange={(event) => setLabel(event.target.value)}
              />
            </label>
            <Select
              aria-label="计算字段角色"
              value={role}
              disabled={mode === "arithmetic"}
              style={{ width: 110 }}
              options={[
                { value: "dimension", label: "维度" },
                { value: "measure", label: "度量" },
              ]}
              onChange={setRole}
            />
            <Select
              aria-label="计算字段类型"
              value={dataType}
              style={{ width: 120 }}
              options={[
                { value: "integer", label: "整数" },
                { value: "decimal", label: "小数" },
                ...(mode === "case"
                  ? [
                      { value: "string", label: "字符串" },
                      { value: "boolean", label: "布尔" },
                      { value: "date", label: "日期" },
                      { value: "datetime", label: "日期时间" },
                    ]
                  : []),
              ]}
              onChange={setDataType}
            />
          </Space>
          <Segmented<CalculationMode>
            block
            value={mode}
            options={[
              { value: "arithmetic", label: "双字段运算" },
              { value: "case", label: "条件 CASE" },
            ]}
            onChange={(nextMode) => {
              setMode(nextMode);
              if (nextMode === "arithmetic") {
                setRole("measure");
                if (dataType !== "integer" && dataType !== "decimal") {
                  setDataType("decimal");
                }
              }
            }}
          />
          {mode === "arithmetic" ? (
            <Space wrap>
              <Select
                aria-label="左侧字段"
                placeholder="选择字段"
                value={leftFieldId}
                style={{ width: 170 }}
                options={numericOptions}
                onChange={setLeftFieldId}
              />
              <Select
                aria-label="计算运算符"
                value={arithmeticOperator}
                style={{ width: 130 }}
                options={[
                  { value: "add", label: "加" },
                  { value: "subtract", label: "减" },
                  { value: "multiply", label: "乘" },
                  { value: "safe_divide", label: "安全除法" },
                ]}
                onChange={setArithmeticOperator}
              />
              <Select
                aria-label="右侧字段"
                placeholder="选择字段"
                value={rightFieldId}
                style={{ width: 170 }}
                options={numericOptions}
                onChange={setRightFieldId}
              />
            </Space>
          ) : (
            <Space orientation="vertical" style={{ width: "100%" }}>
              <Space wrap>
                <Select
                  aria-label="CASE判断字段"
                  placeholder="判断字段"
                  value={caseFieldId}
                  style={{ width: 180 }}
                  options={fieldOptions}
                  onChange={setCaseFieldId}
                />
                <Select
                  aria-label="CASE比较符"
                  value={comparisonOperator}
                  style={{ width: 110 }}
                  options={[
                    { value: "eq", label: "等于" },
                    { value: "ne", label: "不等于" },
                    { value: "gt", label: "大于" },
                    { value: "gte", label: "大于等于" },
                    { value: "lt", label: "小于" },
                    { value: "lte", label: "小于等于" },
                  ]}
                  onChange={setComparisonOperator}
                />
                <Input
                  aria-label="CASE比较值"
                  placeholder="比较值"
                  value={comparisonValue}
                  style={{ width: 150 }}
                  onChange={(event) => setComparisonValue(event.target.value)}
                />
              </Space>
              <Space wrap>
                <Input
                  aria-label="CASE命中值"
                  placeholder="条件成立时"
                  value={thenValue}
                  onChange={(event) => setThenValue(event.target.value)}
                />
                <Input
                  aria-label="CASE默认值"
                  placeholder="其他情况"
                  value={elseValue}
                  onChange={(event) => setElseValue(event.target.value)}
                />
              </Space>
            </Space>
          )}
        </Space>
      </Modal>
    </>
  );
}

function fieldOption(field: DatasetField) {
  return {
    value: field.id,
    label: `${field.label} · ${field.data_type}${field.field_kind === "calculated" ? " · 计算" : ""}`,
  };
}
