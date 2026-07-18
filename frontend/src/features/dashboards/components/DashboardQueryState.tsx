import { Button, Result, Skeleton } from "antd";

import { ApiError } from "../../../shared/api/client";
import { dashboardErrorDescription } from "../presentation";

export function DashboardLoadingState({ label }: { label: string }) {
  return (
    <section
      className="dashboard-state dashboard-state-loading"
      aria-label={label}
    >
      <Skeleton active paragraph={{ rows: 8 }} />
    </section>
  );
}

export function DashboardErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  const forbidden =
    error instanceof ApiError &&
    (error.status === 403 || error.code === "dashboard_forbidden");
  return (
    <Result
      className="dashboard-state"
      status={forbidden ? "403" : "error"}
      title={forbidden ? "没有仪表盘访问权限" : "仪表盘加载失败"}
      subTitle={dashboardErrorDescription(error)}
      extra={
        forbidden ? null : (
          <Button type="primary" onClick={onRetry}>
            重新加载
          </Button>
        )
      }
    />
  );
}
