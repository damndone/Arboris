import { apiUrl, readResponse } from "../api";
import type { ResponseOf, Schema } from "../apiTypes";

export type DatasetNode = Schema<"DatasetNode">;
export type MissingCode = Schema<"DatasetVariable">["user_missing_values"][number];
export type DatasetPage = ResponseOf<"/runs/{run_id}/datasets/rows", "get">;
export type DatasetVariable = Schema<"DatasetVariable">;
export type SensitivityLevel = Schema<"EgressPolicyDocument">["columns"][string];
export const SENSITIVITY_LEVELS = ["public", "internal", "sensitive", "restricted"] as const satisfies readonly SensitivityLevel[];
export type ContentClass = Schema<"ActiveProviderEgress">["allowed_classes"][number];
export type DatasetVariables = ResponseOf<"/runs/{run_id}/datasets/variables", "get">;

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
  return (await readResponse<ResponseOf<"/runs/{run_id}/datasets", "get">>(response)).datasets;
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
): Promise<ResponseOf<"/runs/{run_id}/metadata", "post">> {
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

export type EgressView = ResponseOf<"/projects/egress", "get">;
export type EgressAuditRecord = Schema<"EgressAuditRecord">;

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
  return (await readResponse<ResponseOf<"/projects/egress/audit", "get">>(response)).records;
}
