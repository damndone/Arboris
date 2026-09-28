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
  /** Project-wide: who may see this column's values (see Sharing). */
  sensitivity?: SensitivityLevel;
  sensitivity_source?: "project" | "suggested";
  sensitivity_suggested?: SensitivityLevel;
};

export const SENSITIVITY_LEVELS = ["public", "internal", "sensitive", "restricted"] as const;
export type SensitivityLevel = (typeof SENSITIVITY_LEVELS)[number];

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

export type EgressView = {
  project_root: string;
  policy: {
    version: number;
    providers: Record<string, { allow: string[] }>;
    columns: Record<string, SensitivityLevel>;
  };
  policy_source: string;
  content_classes: string[];
  sensitivity_levels: SensitivityLevel[];
  defaults: { remote: string[]; local: string[] };
  active_provider: {
    provider_id: string;
    provider_name: string;
    locality: "local" | "remote";
    allowed_classes: string[];
  } | null;
};

export type EgressAuditRecord = {
  at: string;
  provider_id: string;
  provider_host: string;
  provider_locality: "local" | "remote";
  model: string;
  message_count: number;
  withheld_count: number;
  redacted_columns: string[];
  payload_bytes: number;
  decisions: {
    index: number;
    role: string;
    tool_id?: string;
    content_class: string;
    decision: string;
    redacted_columns?: string[];
    withheld_protocols?: string[];
  }[];
};

export async function fetchEgress(projectRoot: string): Promise<EgressView> {
  const response = await fetch(apiUrl(`/projects/egress?${query({ project_root: projectRoot })}`));
  return readResponse<EgressView>(response);
}

/** A null level removes the project's choice; the column falls back to the suggestion. */
export async function patchColumnSensitivity(
  projectRoot: string,
  columns: Record<string, SensitivityLevel | null>,
): Promise<EgressView> {
  const response = await fetch(apiUrl(`/projects/egress/columns?${query({ project_root: projectRoot })}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ columns }),
  });
  return readResponse<EgressView>(response);
}

export async function replaceEgressPolicy(
  projectRoot: string,
  policy: EgressView["policy"],
): Promise<EgressView> {
  const response = await fetch(apiUrl(`/projects/egress/policy?${query({ project_root: projectRoot })}`), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(policy),
  });
  return readResponse<EgressView>(response);
}

export async function fetchEgressAudit(projectRoot: string, limit = 20): Promise<EgressAuditRecord[]> {
  const response = await fetch(
    apiUrl(`/projects/egress/audit?${query({ project_root: projectRoot, limit })}`),
  );
  return (await readResponse<{ records: EgressAuditRecord[] }>(response)).records;
}
