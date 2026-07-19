import { useQuery, useQueryClient } from "@tanstack/react-query";

import { queryDashboardChart } from "./queryApi";
import type { DashboardChartQueryRequest } from "./types";

export function useDashboardChartQuery(
  request: DashboardChartQueryRequest,
  enabled: boolean,
) {
  const queryClient = useQueryClient();
  const queryKey = ["dashboards", "chart-query", request] as const;
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => queryDashboardChart(request, signal),
    enabled,
    retry: false,
    staleTime: 30_000,
  });
  return {
    ...query,
    cancel: () => queryClient.cancelQueries({ queryKey }),
  };
}
