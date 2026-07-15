export type DatasetStatus = "draft" | "active" | "archived";

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
  latest_batch_id: string | null;
  fields: DataSourceField[];
}
