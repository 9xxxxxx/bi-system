import { API_BASE_URL, requestJson } from "../../shared/api/client";
import type {
  ImportBatch,
  ImportDefinition,
  ImportIssuePage,
  ImportMode,
  ImportTemplate,
  SourceFile,
  SourcePreview,
} from "./types";

export function uploadSourceFile(file: File): Promise<SourceFile> {
  const body = new FormData();
  body.append("file", file);
  return requestJson<SourceFile>("/source-files", { method: "POST", body });
}

export function previewSourceFile(
  sourceFileId: string,
  options: { encoding: string; sheet_name: string | null },
): Promise<SourcePreview> {
  return requestJson<SourcePreview>(`/source-files/${sourceFileId}/preview`, {
    method: "POST",
    body: JSON.stringify(options),
  });
}

export function listImportTemplates(): Promise<ImportTemplate[]> {
  return requestJson<ImportTemplate[]>("/import-templates");
}

export function createImportTemplate(
  name: string,
  definition: ImportDefinition,
): Promise<ImportTemplate> {
  return requestJson<ImportTemplate>("/import-templates", {
    method: "POST",
    body: JSON.stringify({ name, definition }),
  });
}

export function listImportBatches(): Promise<ImportBatch[]> {
  return requestJson<ImportBatch[]>("/import-batches?limit=50");
}

export interface CreateBatchInput {
  source_file_id: string;
  template_id?: string;
  definition?: ImportDefinition;
  target_id?: string;
  target_name?: string;
  mode: ImportMode;
  encoding: string;
  warnings_confirmed: boolean;
}

export function createImportBatch(
  input: CreateBatchInput,
): Promise<ImportBatch> {
  return requestJson<ImportBatch>("/import-batches", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getImportBatch(batchId: string): Promise<ImportBatch> {
  return requestJson<ImportBatch>(`/import-batches/${batchId}`);
}

export function getImportIssues(
  batchId: string,
  offset: number,
  limit: number,
): Promise<ImportIssuePage> {
  return requestJson<ImportIssuePage>(
    `/import-batches/${batchId}/issues?offset=${offset}&limit=${limit}`,
  );
}

function postBatchAction(
  batchId: string,
  action: string,
): Promise<ImportBatch> {
  return requestJson<ImportBatch>(`/import-batches/${batchId}/${action}`, {
    method: "POST",
  });
}

export function cancelImportBatch(batchId: string): Promise<ImportBatch> {
  return postBatchAction(batchId, "cancel");
}

export function retryImportBatch(batchId: string): Promise<ImportBatch> {
  return postBatchAction(batchId, "retry");
}

export function confirmImportWarnings(batchId: string): Promise<ImportBatch> {
  return postBatchAction(batchId, "confirm-warnings");
}

export function getImportReportUrl(batchId: string): string {
  return `${API_BASE_URL}/import-batches/${batchId}/report`;
}
