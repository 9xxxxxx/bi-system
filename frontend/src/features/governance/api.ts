import { requestJson } from "../../shared/api/client";
import type {
  CreateMetricRequest,
  CreateRowPolicyRequest,
  IdentityRole,
  IdentityUser,
  MetricPage,
  MetricSummary,
  RowPolicy,
  RowPolicyPage,
} from "./types";

export function listMetrics(): Promise<MetricPage> {
  return requestJson<MetricPage>("/metrics?offset=0&limit=100");
}

export function createMetric(
  request: CreateMetricRequest,
): Promise<MetricSummary> {
  return requestJson<MetricSummary>("/metrics", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function listRowPolicies(): Promise<RowPolicyPage> {
  return requestJson<RowPolicyPage>("/row-policies?offset=0&limit=100");
}

export function createRowPolicy(
  request: CreateRowPolicyRequest,
): Promise<RowPolicy> {
  return requestJson<RowPolicy>("/row-policies", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export function replaceRowPolicyBindings(
  policyId: string,
  userIds: string[],
  roleIds: string[],
): Promise<RowPolicy> {
  return requestJson<RowPolicy>(`/row-policies/${policyId}/bindings`, {
    method: "PUT",
    body: JSON.stringify({ user_ids: userIds, role_ids: roleIds }),
  });
}

export function activateRowPolicy(policyId: string): Promise<RowPolicy> {
  return requestJson<RowPolicy>(`/row-policies/${policyId}/activate`, {
    method: "POST",
  });
}

export async function publishRowPolicy(
  request: CreateRowPolicyRequest,
  userIds: string[],
  roleIds: string[],
): Promise<RowPolicy> {
  const created = await createRowPolicy(request);
  await replaceRowPolicyBindings(created.id, userIds, roleIds);
  return activateRowPolicy(created.id);
}

export function listIdentityUsers(): Promise<IdentityUser[]> {
  return requestJson<IdentityUser[]>("/identity/users");
}

export function listIdentityRoles(): Promise<IdentityRole[]> {
  return requestJson<IdentityRole[]>("/identity/roles");
}
