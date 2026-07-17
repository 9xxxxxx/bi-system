export type DatasetStatus = "draft" | "active" | "archived";
export type DatasetFieldRole = "dimension" | "measure";

export interface DatasetSummary {
  id: string;
  name: string;
  description: string | null;
  status: DatasetStatus;
  source_count: number;
  field_count: number;
  metric_count: number;
  owner_name: string;
  updated_at: string;
}

export interface DatasetListResponse {
  items: DatasetSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface DataSourceField {
  id: string;
  display_name: string;
  data_type: string;
  nullable: boolean;
}

export interface DataSource {
  id: string;
  name: string;
  status: string;
  active_row_count: number;
  latest_active_batch_id: string | null;
  fields: DataSourceField[];
}

export interface SemanticModelSource {
  id: string;
  target_id: string;
  alias: string;
  role: "fact" | "dimension";
  ordinal: number;
}

export interface SemanticModel {
  id: string;
  series_id: string;
  name: string;
  version: number;
  description: string | null;
  status: string;
  sources: SemanticModelSource[];
  joins: SemanticModelJoin[];
}

export interface SemanticModelJoin {
  id: string;
  left_source_id: string;
  right_source_id: string;
  join_type: "inner" | "left";
  cardinality: "one_to_one" | "many_to_one";
  ordinal: number;
  keys: Array<{
    left_column_id: string;
    right_column_id: string;
    ordinal: number;
  }>;
}

export interface CreateSemanticModelRequest {
  name: string;
  description: string | null;
  sources: Array<{
    target_id: string;
    alias: string;
    role: "fact" | "dimension";
  }>;
  joins: Array<{
    left_source: string;
    right_source: string;
    join_type: "inner" | "left";
    cardinality: "one_to_one" | "many_to_one";
    keys: Array<{
      left_column_id: string;
      right_column_id: string;
    }>;
  }>;
}

export interface DatasetFieldInput {
  model_source_id: string;
  source_column_id: string;
  name: string;
  label: string;
  role: DatasetFieldRole;
  hidden: boolean;
}

export interface CreateDatasetRequest {
  semantic_model_id: string;
  name: string;
  description: string | null;
  fields: DatasetFieldInput[];
}

export interface DatasetField {
  id: string;
  model_source_id: string | null;
  source_column_id: string | null;
  name: string;
  label: string;
  field_kind: "source" | "calculated";
  role: DatasetFieldRole;
  data_type: string;
  hidden: boolean;
  ordinal: number;
}

export interface DatasetDetail extends DatasetSummary {
  semantic_model_id: string;
  series_id: string;
  version: number;
  fields: DatasetField[];
}

export interface DatasetQueryRequest {
  dataset_id: string;
  selections: Array<{
    field_id: string;
    output_name: string;
  }>;
  limit: number;
}

export interface DatasetQueryResult {
  columns: string[];
  rows: Array<Record<string, unknown>>;
  truncated: boolean;
  elapsed_ms: number;
  dataset_version: number;
  source_batch_ids: string[];
}
