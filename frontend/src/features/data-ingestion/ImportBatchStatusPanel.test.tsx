import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import type { ImportBatch } from "./types";
import { ImportBatchStatusPanel } from "./ImportBatchStatusPanel";

function batch(overrides: Partial<ImportBatch> = {}): ImportBatch {
  return {
    id: "batch-1",
    source_file_id: "source-1",
    template_id: null,
    target: {
      id: "target-1",
      name: "销售明细",
      physical_table_name: "data_target_1",
    },
    mode: "append",
    status: "pending",
    total_rows: 100,
    processed_rows: 0,
    valid_rows: 0,
    error_rows: 0,
    warning_rows: 0,
    checkpoint_row: 0,
    attempt_count: 0,
    cancellation_requested: false,
    error_code: null,
    error_message: null,
    created_at: "2026-07-15T00:00:00Z",
    started_at: null,
    finished_at: null,
    updated_at: "2026-07-15T00:00:00Z",
    ...overrides,
  };
}

it("renders loading and empty states", () => {
  const { rerender } = render(<ImportBatchStatusPanel loading />);
  expect(document.querySelector(".ant-progress")).toBeInTheDocument();

  rerender(<ImportBatchStatusPanel />);
  expect(screen.getByText("尚未创建导入批次")).toBeInTheDocument();
});

it("renders a successful import summary", () => {
  render(
    <ImportBatchStatusPanel
      batch={batch({
        status: "succeeded",
        processed_rows: 100,
        valid_rows: 100,
      })}
    />,
  );

  expect(screen.getByText("数据已提交到目标表")).toBeInTheDocument();
  expect(screen.getByText("导入成功")).toBeInTheDocument();
});

it("allows warning confirmation", () => {
  const onAction = vi.fn();
  render(
    <ImportBatchStatusPanel
      batch={batch({
        status: "failed",
        warning_rows: 3,
        error_code: "quality_warnings_pending",
      })}
      onAction={onAction}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /确认警告并继续/ }));
  expect(onAction).toHaveBeenCalledWith("confirm");
});

it("offers checkpoint retry for a failed batch", () => {
  const onAction = vi.fn();
  render(
    <ImportBatchStatusPanel
      batch={batch({
        status: "failed",
        error_code: "worker_error",
        error_message: "读取文件失败",
      })}
      onAction={onAction}
    />,
  );

  expect(screen.getByText("读取文件失败")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /从检查点重试/ }));
  expect(onAction).toHaveBeenCalledWith("retry");
});

it("renders the cancelled state without recovery actions", () => {
  render(<ImportBatchStatusPanel batch={batch({ status: "cancelled" })} />);

  expect(screen.getByText("导入已取消")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /重试/ }),
  ).not.toBeInTheDocument();
});
