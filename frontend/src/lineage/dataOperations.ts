import { apiUrl, readResponse } from "../api";
import type { RequestOf, ResponseOf, Schema } from "../apiTypes";

export type DataColumnCastRequest = Schema<"DataColumnCastRequest">;
export type DataColumnCastTarget = DataColumnCastRequest["target_dtype"];
export type DataColumnCastContext = ResponseOf<"/data-operations/column-cast/context", "get">;
export type DataColumnCastPreviewResponse = ResponseOf<"/data-operations/column-cast/preview", "post">;
export type DataColumnCastPreview = DataColumnCastPreviewResponse["preview"];
export type DataColumnsCastRequest = Schema<"DataColumnsCastRequest">;
export type DataColumnsCastItem = DataColumnsCastRequest["casts"][number];
export type DataCastOutputFormat = NonNullable<DataColumnsCastRequest["output_format"]>;
export type DataColumnsCastPreviewResponse = ResponseOf<"/data-operations/columns-cast/preview", "post">;
export type DataColumnsCastPreview = DataColumnsCastPreviewResponse["preview"];
export type DataColumnCastItemResult = DataColumnsCastPreview["items"][number];
export type DataColumnCastConfirmResponse = Schema<"OperationConfirmed">;

export type FeatureRecipeRequest = Schema<"FeatureRecipeRequest">;
export type FeatureRecipeOperation = FeatureRecipeRequest["operation_id"];
export type FeatureRecipePreviewResponse = ResponseOf<"/data-operations/feature-recipe/preview", "post">;
export type FeatureRecipePreview = FeatureRecipePreviewResponse["preview"];
export type FeatureRecipeConfirmResponse = ResponseOf<"/data-operations/feature-recipe/confirm", "post">;

// The transform builder's own vocabulary: the operations and parameters this
// UI offers. The server admits operations from its registry and validates the
// parameters per operation, so the request declares them openly.
export type DataTransformOperation =
  | "merge"
  | "append"
  | "reshape"
  | "subset"
  | "dedupe"
  | "rename"
  | "aggregate"
  | "fill_missing"
  | "tsset"
  | "lag"
  | "recode";

export type DataTransformHow = "left" | "right" | "inner" | "outer";
export type DataTransformSchemaPolicy = "exact" | "union";
export type DataTransformDirection = "wide_to_long" | "long_to_wide";

export interface DataTransformGrowthPolicy {
  max_rows?: number;
  max_growth_factor?: number;
}

export interface DataTransformRowIndexRange {
  start: number;
  stop: number;
}

/** Canonical parameters sent to the fail-closed data-operation route. */
export interface DataTransformParameters {
  keys?: string[];
  how?: DataTransformHow;
  growth_policy?: DataTransformGrowthPolicy;
  schema_policy?: DataTransformSchemaPolicy;
  row_growth_policy?: DataTransformGrowthPolicy;
  direction?: DataTransformDirection;
  id_columns?: string[];
  value_columns?: string[];
  var_name?: string;
  value_name?: string;
  index?: string[];
  columns?: string | string[];
  values?: string;
  equals?: Record<string, unknown>;
  row_indices?: number[];
  row_index_range?: DataTransformRowIndexRange;
  [key: string]: unknown;
}

export type DataTransformRequest = Omit<Schema<"DataTransformRequest">, "operation" | "parameters"> & {
  operation: DataTransformOperation;
  parameters: DataTransformParameters;
};
export type DataTransformPreviewResponse = ResponseOf<"/data-operations/transform/preview", "post">;
export type DataTransformPreview = DataTransformPreviewResponse["preview"];
export type DataTransformConfirmResponse = ResponseOf<"/data-operations/transform/confirm", "post">;

export type DataModelRunRequest = Schema<"DataModelRunRequest">;
export type DataModelRunResponse = ResponseOf<"/data-operations/model-run", "post">;

export type DataColumnCastOperationRecord = ResponseOf<"/data-operations/column-cast/by-child-node", "get">["operation"];

/** The diff a data operation records (its diff_ref): one shape per operation. */
export interface DataOperationDiff {
  kind: string;
  // data.column.cast
  column?: string;
  before_dtype?: string;
  after_dtype?: string;
  // data.columns.cast
  casts?: Array<{ column: string; before_dtype: string; after_dtype: string }>;
  // code.execute
  columns_added?: string[];
  columns_removed?: string[];
  dtype_changes?: Array<{ column: string; before_dtype: string; after_dtype: string }>;
  row_count_before?: number;
  row_count_after?: number;
  source_fingerprint: string;
  result_fingerprint: string;
}

export type CodeExecuteRequest = Schema<"CodeExecuteRequest">;
export type CodeDtypeChange = Schema<"CodeDtypeChange">;
export type CodeExecutePreviewResponse = ResponseOf<"/data-operations/code-execute/preview", "post">;
export type CodeExecutePreview = CodeExecutePreviewResponse["preview"];
export type CodeExecuteRiskAuthorizationResponse = ResponseOf<"/data-operations/code-execute/risk-authorize", "post">;
export type CodeExecuteRiskAuthorization = CodeExecuteRiskAuthorizationResponse["risk_authorization"];

function projectQuery(projectRoot: string): string {
  return `?project_root=${encodeURIComponent(projectRoot)}`;
}

export async function previewCodeExecute(
  projectRoot: string,
  request: CodeExecuteRequest,
): Promise<CodeExecutePreviewResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/code-execute/preview${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<CodeExecutePreviewResponse>(response);
}

export async function authorizeCodeExecuteRisk(
  projectRoot: string,
  request: RequestOf<"/data-operations/code-execute/risk-authorize", "post">,
): Promise<CodeExecuteRiskAuthorizationResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/code-execute/risk-authorize${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<CodeExecuteRiskAuthorizationResponse>(response);
}

export async function confirmCodeExecute(
  projectRoot: string,
  request: RequestOf<"/data-operations/code-execute/confirm", "post">,
): Promise<DataColumnCastConfirmResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/code-execute/confirm${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnCastConfirmResponse>(response);
}

export async function fetchDataColumnCastContext(
  projectRoot: string,
  sourceRunId: string,
  sourceNodeId: string,
): Promise<DataColumnCastContext> {
  const params = new URLSearchParams({
    project_root: projectRoot,
    source_run_id: sourceRunId,
    source_node_id: sourceNodeId,
  });
  const response = await fetch(
    apiUrl(`/data-operations/column-cast/context?${params.toString()}`),
  );
  return readResponse<DataColumnCastContext>(response);
}

export async function fetchDataColumnCastRecordByChildNode(
  projectRoot: string,
  childNodeId: string,
): Promise<ResponseOf<"/data-operations/column-cast/by-child-node", "get">> {
  const params = new URLSearchParams({
    project_root: projectRoot,
    child_node_id: childNodeId,
  });
  const response = await fetch(
    apiUrl(`/data-operations/column-cast/by-child-node?${params.toString()}`),
  );
  return readResponse<ResponseOf<"/data-operations/column-cast/by-child-node", "get">>(response);
}

export async function previewDataColumnCast(
  projectRoot: string,
  request: DataColumnCastRequest,
): Promise<DataColumnCastPreviewResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/column-cast/preview${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnCastPreviewResponse>(response);
}

export async function previewDataColumnsCast(
  projectRoot: string,
  request: DataColumnsCastRequest,
): Promise<DataColumnsCastPreviewResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/columns-cast/preview${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnsCastPreviewResponse>(response);
}

export async function confirmDataColumnsCast(
  projectRoot: string,
  request: DataColumnsCastRequest & {
    preview_fingerprint: string;
    session_id?: string;
  },
): Promise<DataColumnCastConfirmResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/columns-cast/confirm${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnCastConfirmResponse>(response);
}

export async function confirmDataColumnCast(
  projectRoot: string,
  request: DataColumnCastRequest & {
    preview_fingerprint: string;
    session_id?: string;
  },
): Promise<DataColumnCastConfirmResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/column-cast/confirm${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataColumnCastConfirmResponse>(response);
}

export async function previewFeatureRecipe(
  projectRoot: string,
  request: FeatureRecipeRequest,
): Promise<FeatureRecipePreviewResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/feature-recipe/preview${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<FeatureRecipePreviewResponse>(response);
}

export async function confirmFeatureRecipe(
  projectRoot: string,
  request: FeatureRecipeRequest & { preview_fingerprint: string },
): Promise<FeatureRecipeConfirmResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/feature-recipe/confirm${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<FeatureRecipeConfirmResponse>(response);
}

export async function previewDataTransform(
  projectRoot: string,
  request: DataTransformRequest,
): Promise<DataTransformPreviewResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/transform/preview${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataTransformPreviewResponse>(response);
}

export async function confirmDataTransform(
  projectRoot: string,
  request: DataTransformRequest & { preview_fingerprint: string },
): Promise<DataTransformConfirmResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/transform/confirm${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataTransformConfirmResponse>(response);
}

export async function startModelFromDataNode(
  projectRoot: string,
  request: DataModelRunRequest,
): Promise<DataModelRunResponse> {
  const response = await fetch(
    apiUrl(`/data-operations/model-run${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  return readResponse<DataModelRunResponse>(response);
}
