import { useQuery } from "@tanstack/react-query";

import { getDataset } from "../../data-modeling/api";

export interface DashboardFieldOption {
  value: string;
  label: string;
  role: "dimension" | "measure";
  dataType: string;
}

export function useDatasetFields(datasetId: string) {
  const query = useQuery({
    queryKey: ["dashboards", "catalog", "dataset", datasetId],
    queryFn: () => getDataset(datasetId),
    enabled: Boolean(datasetId),
    staleTime: 30_000,
  });
  return {
    ...query,
    fields:
      query.data?.fields
        .filter((field) => !field.hidden)
        .map((field) => ({
          value: field.id,
          label: field.label,
          role: field.role,
          dataType: field.data_type,
        })) ?? [],
  };
}
