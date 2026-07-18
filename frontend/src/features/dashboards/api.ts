import { requestJson } from "../../shared/api/client";
import { componentTypeLabels } from "./presentation";
import type {
  CreateDashboardRequest,
  DashboardComponentType,
  DashboardDetail,
  DashboardLayoutProfile,
  DashboardListResponse,
  DashboardSummary,
  DashboardStatus,
  DashboardTemplateListResponse,
  SaveDashboardVersionRequest,
} from "./types";

interface DashboardPageWire {
  page_id: string;
  title: string;
  ordinal: number;
  page_filter?: Record<string, unknown> | null;
  components?: DashboardComponentWire[];
}

interface DashboardComponentWire {
  component_id: string;
  page_id: string;
  component_type: DashboardComponentType;
  config_version: number;
  config: Record<string, unknown>;
  ordinal: number;
}

interface DashboardDetailWire extends DashboardSummary {
  revision: number;
  current_version_id: string;
  global_filter?: Record<string, unknown> | null;
  pages: DashboardPageWire[];
  components?: DashboardComponentWire[];
  layouts: DashboardLayoutProfile[];
  permissions?: DashboardDetail["permissions"];
}

interface SaveDashboardVersionWire {
  base_version: number;
  expected_revision: number;
  global_filter: Record<string, unknown> | null;
  pages: Array<Omit<DashboardPageWire, "components">>;
  components: Array<Omit<DashboardComponentWire, "ordinal">>;
  layouts: DashboardLayoutProfile[];
}

export interface DashboardListOptions {
  offset?: number;
  limit?: number;
  status?: DashboardStatus;
}

export function listDashboards({
  offset = 0,
  limit = 50,
  status,
}: DashboardListOptions = {}): Promise<DashboardListResponse> {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  if (status) params.set("status", status);
  return requestJson<DashboardListResponse>(`/dashboards?${params.toString()}`);
}

export function getDashboard(dashboardId: string): Promise<DashboardDetail> {
  return requestJson<DashboardDetailWire>(`/dashboards/${dashboardId}`).then(
    mapDashboardDetail,
  );
}

export function createDashboard(
  request: CreateDashboardRequest,
): Promise<DashboardDetail> {
  return requestJson<DashboardDetailWire>("/dashboards", {
    method: "POST",
    body: JSON.stringify(request),
  }).then(mapDashboardDetail);
}

export function saveDashboardVersion(
  dashboardId: string,
  request: SaveDashboardVersionRequest,
): Promise<DashboardDetail> {
  return requestJson<DashboardDetailWire>(
    `/dashboards/${dashboardId}/versions`,
    {
      method: "POST",
      body: JSON.stringify(toSaveWire(request)),
    },
  ).then(mapDashboardDetail);
}

export function listDashboardTemplates(
  offset = 0,
  limit = 50,
): Promise<DashboardTemplateListResponse> {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
    status: "published",
  });
  return requestJson<DashboardTemplateListResponse>(
    `/dashboard-templates?${params.toString()}`,
  );
}

function mapDashboardDetail(wire: DashboardDetailWire): DashboardDetail {
  return {
    id: wire.id,
    name: wire.name,
    description: wire.description,
    status: wire.status,
    owner_name: wire.owner_name,
    updated_at: wire.updated_at,
    current_version: wire.current_version,
    page_count: wire.page_count,
    capabilities: wire.capabilities,
    revision: wire.revision,
    current_version_id: wire.current_version_id,
    global_filter: wire.global_filter ?? null,
    pages: [...wire.pages]
      .sort((left, right) => left.ordinal - right.ordinal)
      .map((page) => ({
        id: page.page_id,
        title: page.title,
        ordinal: page.ordinal,
        page_filter: page.page_filter ?? null,
        components: [
          ...(page.components ?? []).concat(
            (wire.components ?? []).filter(
              (component) => component.page_id === page.page_id,
            ),
          ),
        ]
          .sort((left, right) => left.ordinal - right.ordinal)
          .map((component) => {
            const title =
              typeof component.config.title === "string" &&
              component.config.title.trim()
                ? component.config.title
                : componentTypeLabels[component.component_type];
            const description =
              typeof component.config.description === "string"
                ? component.config.description
                : null;
            return {
              id: component.component_id,
              component_type: component.component_type,
              title,
              description,
              ordinal: component.ordinal,
              config: {
                ...component.config,
                schema_version:
                  typeof component.config.schema_version === "number"
                    ? component.config.schema_version
                    : component.config_version,
              },
            };
          }),
      })),
    layouts: wire.layouts.map((layout) => ({
      ...layout,
      items: layout.items.map((item) => ({ ...item })),
    })),
    permissions: wire.permissions ?? [],
  };
}

function toSaveWire(
  request: SaveDashboardVersionRequest,
): SaveDashboardVersionWire {
  return {
    base_version: request.base_version,
    expected_revision: request.expected_revision,
    global_filter: request.global_filter ?? null,
    pages: request.pages.map((page) => ({
      page_id: page.id,
      title: page.title,
      ordinal: page.ordinal,
      page_filter: page.page_filter ?? null,
    })),
    components: request.pages.flatMap((page) =>
      page.components.map((component) => ({
        component_id: component.id,
        page_id: page.id,
        component_type: component.component_type,
        config_version: 1,
        config: {
          ...component.config,
          title: component.title,
          description: component.description,
        },
      })),
    ),
    layouts: request.layouts.map((layout) => ({
      ...layout,
      items: layout.items.map((item) => ({ ...item })),
    })),
  };
}
