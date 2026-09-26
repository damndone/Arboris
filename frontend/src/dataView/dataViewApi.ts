import { apiUrl, readResponse } from "../api";

export type DatasetNode = {
  node_id: string;
  label: string;
  stage: string | null;
  parent_stage_id: string | null;
};

export type MissingCode = number | string | { low: number; high: number };

export type DatasetPage = {
  run_id: string;
  node_id: string;
  artifact_id: string;
  columns: string[];
  total_rows: number;
  offset: number;
  row_numbers: number[];
  rows: Record<string, unknown>[];
};

export type DatasetVariable = {
  position: number;
  name: string;
  type: "numeric" | "string" | "date" | "boolean";
  dtype: string;
  missing: number;
  declared_missing_matches: number;
  unique: number;
  variable_label: string | null;
  value_labels: Record<string, string>;
  measurement_level: string | null;
  user_missing_values: MissingCode[];
  min?: number | null;
  max?: number | null;
  mean?: number | null;
  values?: { value: unknown; count: number }[];
};

export type DatasetVariables = {
  run_id: string;
  node_id: string;
  artifact_id: string;
  total_rows: number;
  variables: DatasetVariable[];
};

export type MetadataField =
  | "variable_labels"
  | "value_labels"
  | "measurement_level"
  | "user_missing_values";

export type MetadataPatch = Partial<Record<MetadataField, Record<string, unknown>>>;

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  return search.toString();
}

function runPath(runId: string, suffix: string): string {
  return `/runs/${encodeURIComponent(runId)}${suffix}`;
}

export async function listDatasets(projectRoot: string, runId: string): Promise<DatasetNode[]> {
  const response = await fetch(
    apiUrl(`${runPath(runId, "/datasets")}?${query({ project_root: projectRoot })}`),
  );
  return (await readResponse<{ datasets: DatasetNode[] }>(response)).datasets;
}

export async function fetchDatasetPage(
  projectRoot: string,
  runId: string,
  nodeId: string,
  options: { offset: number; limit: number; sortBy?: string; descending?: boolean },
): Promise<DatasetPage> {
  const response = await fetch(
    apiUrl(
      `${runPath(runId, "/datasets/rows")}?${query({
        project_root: projectRoot,
        node_id: nodeId,
        offset: options.offset,
        limit: options.limit,
        sort_by: options.sortBy,
        descending: options.sortBy ? options.descending ?? false : undefined,
      })}`,
    ),
  );
  return readResponse<DatasetPage>(response);
}

export async function fetchDatasetVariables(
  projectRoot: string,
  runId: string,
  nodeId: string,
): Promise<DatasetVariables> {
  const response = await fetch(
    apiUrl(
      `${runPath(runId, "/datasets/variables")}?${query({ project_root: projectRoot, node_id: nodeId })}`,
    ),
  );
  return readResponse<DatasetVariables>(response);
}

export async function saveMetadata(
  projectRoot: string,
  runId: string,
  labels: MetadataPatch,
): Promise<{ source_run_id: string; run_id: string; status: string }> {
  const response = await fetch(
    apiUrl(`${runPath(runId, "/metadata")}?${query({ project_root: projectRoot })}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ labels }),
    },
  );
  return readResponse(response);
}
