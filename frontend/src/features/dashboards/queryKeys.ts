import type { DashboardListOptions } from "./api";
import type { DashboardTemplateStatus } from "./types";

export const dashboardQueryKeys = {
  all: ["dashboards"] as const,
  lists: () => [...dashboardQueryKeys.all, "list"] as const,
  list: (options: DashboardListOptions = {}) =>
    [...dashboardQueryKeys.lists(), options] as const,
  detail: (dashboardId: string) =>
    [...dashboardQueryKeys.all, "detail", dashboardId] as const,
  templateLists: () => [...dashboardQueryKeys.all, "templates"] as const,
  templates: (status: DashboardTemplateStatus = "published") =>
    [...dashboardQueryKeys.templateLists(), status] as const,
};
