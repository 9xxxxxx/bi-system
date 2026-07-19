import { requestJson } from "../../shared/api/client";
import { componentTypeLabels } from "./presentation";
import type {
  CreateDashboardRequest,
  CreateDashboardTemplateRequest,
  DashboardComponentType,
  DashboardDetail,
  DashboardLayoutProfile,
  DashboardListResponse,
  DashboardSummary,
  DashboardStatus,
  DashboardTemplateDetail,
  DashboardTemplateListResponse,
  DashboardTemplateStatus,
  InstantiateDashboardTemplateRequest,
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
  includeDeleted?: boolean;
}

export function listDashboards({
  offset = 0,
  limit = 50,
  status,
  includeDeleted,
}: DashboardListOptions = {}): Promise<DashboardListResponse> {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  if (status) params.set("status", status);
  if (includeDeleted !== undefined) {
    params.set("include_deleted", String(includeDeleted));
  }
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

export function activateDashboard(
  dashboardId: string,
  expectedRevision: number,
): Promise<DashboardDetail> {
  return requestJson<DashboardDetailWire>(
    `/dashboards/${dashboardId}/activate`,
    {
      method: "POST",
      body: JSON.stringify({ expected_revision: expectedRevision }),
    },
  ).then(mapDashboardDetail);
}

export function deleteDashboard(
  dashboardId: string,
  expectedRevision: number,
): Promise<DashboardDetail> {
  const params = new URLSearchParams({
    expected_revision: String(expectedRevision),
  });
  return requestJson<DashboardDetailWire>(
    `/dashboards/${dashboardId}?${params.toString()}`,
    { method: "DELETE" },
  ).then(mapDashboardDetail);
}

export function restoreDashboard(
  dashboardId: string,
  expectedRevision: number,
): Promise<DashboardDetail> {
  return requestJson<DashboardDetailWire>(
    `/dashboards/${dashboardId}/restore`,
    {
      method: "POST",
      body: JSON.stringify({ expected_revision: expectedRevision }),
    },
  ).then(mapDashboardDetail);
}

export function listDashboardTemplates(
  offset = 0,
  limit = 50,
  status: DashboardTemplateStatus = "published",
): Promise<DashboardTemplateListResponse> {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
    status,
  });
  return requestJson<DashboardTemplateListResponse>(
    `/dashboard-templates?${params.toString()}`,
  );
}

export function createDashboardTemplate(
  request: CreateDashboardTemplateRequest,
): Promise<DashboardTemplateDetail> {
  return requestJson<DashboardTemplateDetail>("/dashboard-templates", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function publishDashboardTemplate(
  templateId: string,
  expectedRevision: number,
): Promise<DashboardTemplateDetail> {
  return requestJson<DashboardTemplateDetail>(
    `/dashboard-templates/${templateId}/publish`,
    {
      method: "POST",
      body: JSON.stringify({ expected_revision: expectedRevision }),
    },
  );
}

export function instantiateDashboardTemplate(
  templateId: string,
  request: InstantiateDashboardTemplateRequest,
): Promise<DashboardDetail> {
  return requestJson<DashboardDetailWire>(
    `/dashboard-templates/${templateId}/instantiate`,
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  ).then(mapDashboardDetail);
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
