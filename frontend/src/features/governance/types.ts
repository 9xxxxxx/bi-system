export type MetricStatus = "draft" | "active" | "deprecated";
export type PolicyStatus = "draft" | "active" | "disabled";

export interface MetricSummary {
  id: string;
  series_id: string;
  dataset_id: string;
  dataset_name: string;
  code: string;
  name: string;
  version: number;
  description: string;
  result_type: "integer" | "decimal";
  unit: string | null;
  status: MetricStatus;
  owner_name: string;
  updated_at: string;
}

export interface MetricPage {
  items: MetricSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface CreateMetricRequest {
  dataset_id: string;
  code: string;
  name: string;
  description: string;
  formula: {
    op: "aggregate";
    function: string;
    field_id: string;
  };
  unit: string | null;
  dimension_field_ids: string[];
  status: "draft" | "active";
}

export interface RowPolicy {
  id: string;
  dataset_id: string;
  name: string;
  version: number;
  effect: "allow" | "deny";
  status: PolicyStatus;
  user_ids: string[];
  role_ids: string[];
  updated_at: string;
}

export interface RowPolicyPage {
  items: RowPolicy[];
  total: number;
  offset: number;
  limit: number;
}

export interface CreateRowPolicyRequest {
  dataset_id: string;
  name: string;
  effect: "allow" | "deny";
  expression: {
    kind: "comparison";
    field_id: string;
    operator: string;
    value: string | number | boolean;
  };
}

export interface IdentityUser {
  id: string;
  username: string;
  display_name: string;
}

export interface IdentityRole {
  id: string;
  code: string;
  name: string;
  description: string | null;
}
