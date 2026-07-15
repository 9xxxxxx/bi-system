import { requestJson } from "../../shared/api/client";
import type { DataSource, DatasetListResponse } from "./types";

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

export function listDataSources(): Promise<DataSource[]> {
  return requestJson<DataSource[]>("/data-sources");
}
