import type { DashboardListOptions } from "./api";

export const dashboardQueryKeys = {
  all: ["dashboards"] as const,
  lists: () => [...dashboardQueryKeys.all, "list"] as const,
  list: (options: DashboardListOptions = {}) =>
    [...dashboardQueryKeys.lists(), options] as const,
  detail: (dashboardId: string) =>
    [...dashboardQueryKeys.all, "detail", dashboardId] as const,
  templates: () => [...dashboardQueryKeys.all, "templates"] as const,
};
