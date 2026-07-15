export type FileKind = "csv" | "xlsx";
export type FileDataType =
  "string" | "integer" | "decimal" | "boolean" | "date" | "datetime";
export type ImportMode = "append" | "upsert" | "replace";
export type BatchStatus =
  | "pending"
  | "processing"
  | "succeeded"
  | "partially_succeeded"
  | "failed"
  | "cancelled";

export interface SourceFile {
  id: string;
  original_name: string;
  file_kind: FileKind;
  status: string;
  size_bytes: number;
  sha256: string;
  media_type: string;
  created_at: string;
  duplicate: boolean;
}

export interface PreviewColumn {
  key: string;
  source_name: string;
  inferred_type: FileDataType;
  null_count: number;
}

export interface SourcePreview {
  source_file_id: string;
  file_kind: FileKind;
  sheet_names: string[];
  selected_sheet: string | null;
  columns: PreviewColumn[];
  rows: Record<string, string | number | boolean | null>[];
  truncated: boolean;
}

export interface ColumnMapping {
  source_key: string;
  source_name: string;
  target_name: string;
  data_type: FileDataType;
  nullable: boolean;
}

export interface QualityRule {
  name: string;
  rule_type: "required" | "unique" | "data_type" | "business_key";
  severity: "error" | "warning";
  column_name: string | null;
  parameters: Record<string, unknown>;
}

export interface ImportDefinition {
  file_kind: FileKind;
  sheet_name: string | null;
  header_row: number;
  columns: ColumnMapping[];
  business_key: string[];
  quality_rules: QualityRule[];
}

export interface ImportTemplate {
  id: string;
  name: string;
  version: number;
  status: string;
  definition: ImportDefinition;
  created_at: string;
}

export interface ImportTarget {
  id: string;
  name: string;
  physical_table_name: string;
}

export interface ImportBatch {
  id: string;
  source_file_id: string;
  template_id: string | null;
  target: ImportTarget;
  mode: ImportMode;
  status: BatchStatus;
  total_rows: number | null;
  processed_rows: number;
  valid_rows: number;
  error_rows: number;
  warning_rows: number;
  checkpoint_row: number;
  attempt_count: number;
  cancellation_requested: boolean;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface ImportIssue {
  id: string;
  row_number: number;
  column_name: string | null;
  severity: "error" | "warning";
  code: string;
  message: string;
  raw_value: string | null;
}

export interface ImportIssuePage {
  total: number;
  offset: number;
  limit: number;
  items: ImportIssue[];
}
