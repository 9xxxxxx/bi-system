import {
  CheckCircleFilled,
  CloseCircleFilled,
  DownloadOutlined,
  ExclamationCircleFilled,
  LoadingOutlined,
  ReloadOutlined,
  StopOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Progress,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";

import type { ImportBatch, ImportIssuePage } from "./types";

type BatchAction = "cancel" | "retry" | "confirm";

interface ImportBatchStatusPanelProps {
  batch?: ImportBatch;
  loading?: boolean;
  issues?: ImportIssuePage;
  issuesLoading?: boolean;
  issuePage?: number;
  actionLoading?: boolean;
  onAction?: (action: BatchAction) => void;
  onIssuePageChange?: (page: number) => void;
  reportUrl?: string;
}

const statusLabel: Record<ImportBatch["status"], string> = {
  pending: "待处理",
  processing: "处理中",
  succeeded: "导入成功",
  partially_succeeded: "部分成功",
  failed: "导入失败",
  cancelled: "已取消",
};

const statusColor: Record<ImportBatch["status"], string> = {
  pending: "default",
  processing: "processing",
  succeeded: "success",
  partially_succeeded: "warning",
  failed: "error",
  cancelled: "default",
};

const issueColumns: ColumnsType<NonNullable<ImportIssuePage>["items"][number]> =
  [
    { title: "行", dataIndex: "row_number", width: 72 },
    {
      title: "字段",
      dataIndex: "column_name",
      width: 140,
      render: (value) => value ?? "-",
    },
    {
      title: "级别",
      dataIndex: "severity",
      width: 90,
      render: (value) => (
        <Tag color={value === "error" ? "error" : "warning"}>
          {value === "error" ? "错误" : "警告"}
        </Tag>
      ),
    },
    { title: "问题", dataIndex: "message", ellipsis: true },
    {
      title: "原值",
      dataIndex: "raw_value",
      ellipsis: true,
      render: (value) => value ?? "-",
    },
  ];

function batchAlert(batch: ImportBatch) {
  const warningPending =
    batch.status === "failed" &&
    batch.error_code === "quality_warnings_pending";
  if (warningPending) {
    return {
      type: "warning" as const,
      icon: <ExclamationCircleFilled />,
      title: "发现需要确认的数据警告",
      description: `共 ${batch.warning_rows} 行警告。确认后系统会重新校验并继续导入。`,
    };
  }
  if (batch.status === "succeeded") {
    return {
      type: "success" as const,
      icon: <CheckCircleFilled />,
      title: "数据已提交到目标表",
      description: `有效数据 ${batch.valid_rows} 行，目标为“${batch.target.name}”。`,
    };
  }
  if (batch.status === "failed") {
    return {
      type: "error" as const,
      icon: <CloseCircleFilled />,
      title: "导入未完成",
      description: batch.error_message ?? "处理失败，请查看问题样本后重试。",
    };
  }
  if (batch.status === "cancelled") {
    return {
      type: "info" as const,
      icon: <StopOutlined />,
      title: "导入已取消",
      description: "未激活的暂存数据不会出现在目标表中。",
    };
  }
  return {
    type: "info" as const,
    icon: <LoadingOutlined />,
    title:
      batch.status === "pending" ? "等待 worker 领取任务" : "正在分块处理数据",
    description: "可离开本页，批次状态和检查点会持续保留。",
  };
}

export function ImportBatchStatusPanel({
  batch,
  loading = false,
  issues,
  issuesLoading = false,
  issuePage = 1,
  actionLoading = false,
  onAction,
  onIssuePageChange,
  reportUrl,
}: ImportBatchStatusPanelProps) {
  if (loading && !batch) {
    return <Progress percent={35} status="active" showInfo={false} />;
  }
  if (!batch) {
    return <Empty description="尚未创建导入批次" />;
  }

  const alert = batchAlert(batch);
  const total = batch.total_rows ?? 0;
  const progress =
    total > 0
      ? Math.min(100, Math.round((batch.processed_rows / total) * 100))
      : 0;
  const warningPending =
    batch.status === "failed" &&
    batch.error_code === "quality_warnings_pending";
  const canCancel = batch.status === "pending" || batch.status === "processing";
  const canRetry = batch.status === "failed" && !warningPending;

  return (
    <div className="batch-result">
      <Alert showIcon {...alert} />
      <div className="batch-progress">
        <div className="batch-progress-heading">
          <Typography.Text strong>批次进度</Typography.Text>
          <Tag color={statusColor[batch.status]}>
            {statusLabel[batch.status]}
          </Tag>
        </div>
        <Progress
          percent={batch.status === "succeeded" ? 100 : progress}
          status={batch.status === "failed" ? "exception" : undefined}
        />
      </div>
      <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }}>
        <Descriptions.Item label="已处理">
          {batch.processed_rows}
        </Descriptions.Item>
        <Descriptions.Item label="有效行">{batch.valid_rows}</Descriptions.Item>
        <Descriptions.Item label="错误行">{batch.error_rows}</Descriptions.Item>
        <Descriptions.Item label="警告行">
          {batch.warning_rows}
        </Descriptions.Item>
        <Descriptions.Item label="检查点">
          {batch.checkpoint_row}
        </Descriptions.Item>
        <Descriptions.Item label="尝试次数">
          {batch.attempt_count}
        </Descriptions.Item>
        <Descriptions.Item label="模式">{batch.mode}</Descriptions.Item>
        <Descriptions.Item label="物理表">
          {batch.target.physical_table_name}
        </Descriptions.Item>
      </Descriptions>
      <Space wrap>
        {warningPending && (
          <Button
            type="primary"
            icon={<CheckCircleFilled />}
            loading={actionLoading}
            onClick={() => onAction?.("confirm")}
          >
            确认警告并继续
          </Button>
        )}
        {canCancel && (
          <Button
            danger
            icon={<StopOutlined />}
            loading={actionLoading}
            onClick={() => onAction?.("cancel")}
          >
            取消导入
          </Button>
        )}
        {canRetry && (
          <Button
            icon={<ReloadOutlined />}
            loading={actionLoading}
            onClick={() => onAction?.("retry")}
          >
            从检查点重试
          </Button>
        )}
        {reportUrl && batch.error_rows + batch.warning_rows > 0 && (
          <Button href={reportUrl} icon={<DownloadOutlined />}>
            下载完整报告
          </Button>
        )}
      </Space>
      {batch.error_rows + batch.warning_rows > 0 && (
        <div className="issue-section">
          <Typography.Title level={4}>问题样本</Typography.Title>
          <Table
            rowKey="id"
            size="small"
            loading={issuesLoading}
            columns={issueColumns}
            dataSource={issues?.items ?? []}
            scroll={{ x: 720 }}
            pagination={{
              current: issuePage,
              pageSize: issues?.limit ?? 20,
              total: issues?.total ?? 0,
              showSizeChanger: false,
              onChange: onIssuePageChange,
            }}
          />
        </div>
      )}
    </div>
  );
}
