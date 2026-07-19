export type DashboardStatus = "draft" | "active" | "archived" | "deleted";
export type DashboardCapability = "view" | "edit" | "share" | "export";
export type DashboardComponentType =
  | "kpi"
  | "trend_indicator"
  | "target_progress"
  | "detail_table"
  | "ranking_table"
  | "bar"
  | "horizontal_bar"
  | "stacked_bar"
  | "line"
  | "area"
  | "pie"
  | "donut"
  | "rich_text"
  | "image";

export interface DashboardSummary {
  id: string;
  name: string;
  description: string | null;
  status: DashboardStatus;
  owner_name: string;
  updated_at: string;
  revision: number;
  current_version: number;
  page_count: number;
  capabilities: DashboardCapability[];
}

export interface DashboardListResponse {
  items: DashboardSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface DashboardComponent {
  id: string;
  component_type: DashboardComponentType;
  title: string;
  description: string | null;
  ordinal: number;
  config: Record<string, unknown> & { schema_version: number };
}

export interface DashboardPage {
  id: string;
  title: string;
  ordinal: number;
  page_filter?: Record<string, unknown> | null;
  components: DashboardComponent[];
}

export type DashboardLayoutProfileName = "desktop" | "mobile";

export interface DashboardLayoutItem {
  component_id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  min_width: number;
  min_height: number;
}

export interface DashboardLayoutProfile {
  schema_version: 1;
  profile: DashboardLayoutProfileName;
  columns: number;
  row_height: number;
  items: DashboardLayoutItem[];
}

export interface DashboardDetail extends DashboardSummary {
  revision: number;
  current_version_id: string;
  global_filter?: Record<string, unknown> | null;
  pages: DashboardPage[];
  layouts: DashboardLayoutProfile[];
  permissions?: DashboardPermission[];
}

export interface DashboardPermission {
  subject_type: "user" | "role" | "workspace";
  subject_id: string;
  capability: DashboardCapability;
}

export interface CreateDashboardRequest {
  name: string;
  description?: string;
  template_version_id?: string;
}

export interface SaveDashboardVersionRequest {
  base_version: number;
  expected_revision: number;
  global_filter?: Record<string, unknown> | null;
  pages: DashboardPage[];
  layouts: DashboardLayoutProfile[];
}

export interface DashboardTemplateSummary {
  id: string;
  name: string;
  description: string | null;
  latest_version_id: string;
  page_count: number;
  owner_name: string;
  updated_at: string;
}

export interface DashboardTemplateListResponse {
  items: DashboardTemplateSummary[];
  total: number;
  offset: number;
  limit: number;
}

export type DashboardTemplateStatus = "draft" | "published" | "archived";
export type DashboardTemplateVisibility = "private" | "workspace";

export interface DashboardTemplateDetail {
  id: string;
  name: string;
  description: string | null;
  status: DashboardTemplateStatus;
  visibility: DashboardTemplateVisibility;
  owner_name: string;
  revision: number;
  version_id: string;
  source_dashboard_version_id: string;
  updated_at: string;
}

export interface CreateDashboardTemplateRequest {
  name: string;
  description?: string | null;
  source_dashboard_version_id: string;
  visibility?: DashboardTemplateVisibility;
}

export interface InstantiateDashboardTemplateRequest {
  name: string;
  description?: string | null;
  template_version_id: string;
}
