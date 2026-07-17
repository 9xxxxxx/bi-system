import { requestJson } from "../../shared/api/client";
import type {
  CreateDatasetRequest,
  CreateSemanticModelRequest,
  DataSource,
  DatasetDetail,
  DatasetListResponse,
  DatasetQueryRequest,
  DatasetQueryResult,
  SemanticModel,
} from "./types";

export function listDatasets(
  offset = 0,
  limit = 50,
): Promise<DatasetListResponse> {
  const params = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  return requestJson<DatasetListResponse>(`/datasets?${params.toString()}`);
}

export function getDataset(datasetId: string): Promise<DatasetDetail> {
  return requestJson<DatasetDetail>(`/datasets/${datasetId}`);
}

export function listDataSources(): Promise<DataSource[]> {
  return requestJson<DataSource[]>("/data-sources");
}

export function createSemanticModel(
  request: CreateSemanticModelRequest,
): Promise<SemanticModel> {
  return requestJson<SemanticModel>("/semantic-models", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function createDataset(
  request: CreateDatasetRequest,
): Promise<DatasetDetail> {
  return requestJson<DatasetDetail>("/datasets", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function queryDataset(
  request: DatasetQueryRequest,
): Promise<DatasetQueryResult> {
  return requestJson<DatasetQueryResult>("/dataset-queries", {
    method: "POST",
    body: JSON.stringify(request),
  });
}
