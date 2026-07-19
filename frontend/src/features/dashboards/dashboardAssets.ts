import { API_BASE_URL, requestJson } from "../../shared/api/client";

export interface DashboardAsset {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface DashboardAssetListResponse {
  items: DashboardAsset[];
  total: number;
  offset: number;
  limit: number;
}

export function listDashboardAssets(): Promise<DashboardAssetListResponse> {
  return requestJson<DashboardAssetListResponse>(
    "/dashboard-assets?offset=0&limit=100",
  );
}

export function uploadDashboardAsset(file: File): Promise<DashboardAsset> {
  const body = new FormData();
  body.append("file", file);
  return requestJson<DashboardAsset>("/dashboard-assets", {
    method: "POST",
    body,
  });
}

export function dashboardAssetContentUrl(assetId: string): string {
  return `${API_BASE_URL}/dashboard-assets/${assetId}/content`;
}
