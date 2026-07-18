export type DataState = "ready" | "loading" | "empty" | "error";
export type ChartKind = "bar" | "line" | "donut";

export interface FilterContext {
  fieldId: string;
  operator: "eq";
  value: string;
}

export interface ChartInteraction {
  componentId: string;
  seriesId: string;
  dataIndex: number;
  dataLabel: string;
  dataValue: number;
  filter: FilterContext;
}

export interface InteractionDatum {
  componentId: string,
  seriesId: string,
  dimensionFieldId: string,
  dataIndex: number,
  dataLabel: string,
  dataValue: number,
  filterValue: string,
}

export function makeInteraction({
  componentId,
  seriesId,
  dimensionFieldId,
  dataIndex,
  dataLabel,
  dataValue,
  filterValue,
}: InteractionDatum): ChartInteraction {
  return {
    componentId,
    seriesId,
    dataIndex,
    dataLabel,
    dataValue,
    filter: { fieldId: dimensionFieldId, operator: "eq", value: filterValue },
  };
}

export function toggleReadonlyFilterPanel(current: boolean): boolean {
  return !current;
}
