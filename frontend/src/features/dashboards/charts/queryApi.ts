import { API_BASE_URL, ApiError } from "../../../shared/api/client";
import type {
  DashboardChartQueryRequest,
  DashboardChartQueryResponse,
} from "./types";

export async function queryDashboardChart(
  request: DashboardChartQueryRequest,
  signal?: AbortSignal,
): Promise<DashboardChartQueryResponse> {
  const response = await fetch(`${API_BASE_URL}/dashboard-chart-queries`, {
    method: "POST",
    credentials: "include",
    signal,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    let detail:
      { code?: string; message?: string; action?: string } | undefined;
    try {
      const payload = (await response.json()) as {
        detail?: typeof detail | string;
      };
      detail =
        typeof payload.detail === "string"
          ? { message: payload.detail }
          : payload.detail;
    } catch {
      detail = undefined;
    }
    throw new ApiError(detail?.message ?? "图表查询失败", {
      status: response.status,
      code: detail?.code,
      action: detail?.action,
    });
  }
  return (await response.json()) as DashboardChartQueryResponse;
}
