export const dataModelingQueryKeys = {
  all: ["data-modeling"] as const,
  datasets: () => [...dataModelingQueryKeys.all, "datasets"] as const,
  datasetList: (offset: number, limit: number) =>
    [...dataModelingQueryKeys.datasets(), { offset, limit }] as const,
  dataSources: () => [...dataModelingQueryKeys.all, "data-sources"] as const,
};
