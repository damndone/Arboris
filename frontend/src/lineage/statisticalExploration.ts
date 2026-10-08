import { apiUrl, readResponse } from "../api";
import type { RequestOf, ResponseOf, Schema } from "../apiTypes";

type ExplorationRequest = Schema<"StatisticalExplorationRequest">;

export type StatisticalExplorationOperation = ExplorationRequest["operation"];
export type StatisticalFilterOperator = Schema<"StatisticalFilterRequest">["operator"];
export type StatisticalFilter = Schema<"StatisticalFilterRequest">;
export type StatisticalExplorationRequest = ExplorationRequest;
export type StatisticalExplorationResult = Schema<"ExplorationResult">;
export type StatisticalExplorationPreview = Schema<"ExplorationPreviewState">;
export type StatisticalExplorationPreviewResponse = ResponseOf<"/statistical-explorations/preview", "post">;
export type StatisticalExplorationConfirmResponse = ResponseOf<"/statistical-explorations/confirm", "post">;
export type StatisticalOlsContextRequest = RequestOf<"/statistical-explorations/ols-context", "post">;
export type StatisticalOlsCovariance = NonNullable<StatisticalOlsContextRequest["covariance"]>;
export type StatisticalOlsContextResponse = ResponseOf<"/statistical-explorations/ols-context", "post">;

function projectQuery(projectRoot: string): string {
  const params = new URLSearchParams({ project_root: projectRoot });
  return `?${params.toString()}`;
}

export async function previewStatisticalExploration(
  projectRoot: string,
  request: StatisticalExplorationRequest,
): Promise<StatisticalExplorationPreviewResponse> {
  const response = await fetch(apiUrl(`/statistical-explorations/preview${projectQuery(projectRoot)}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return readResponse<StatisticalExplorationPreviewResponse>(response);
}

export async function confirmStatisticalExploration(
  projectRoot: string,
  request: RequestOf<"/statistical-explorations/confirm", "post">,
): Promise<StatisticalExplorationConfirmResponse> {
  const response = await fetch(apiUrl(`/statistical-explorations/confirm${projectQuery(projectRoot)}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return readResponse<StatisticalExplorationConfirmResponse>(response);
}

export async function createStatisticalOlsContext(
  projectRoot: string,
  request: StatisticalOlsContextRequest,
): Promise<StatisticalOlsContextResponse> {
  const response = await fetch(apiUrl(`/statistical-explorations/ols-context${projectQuery(projectRoot)}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return readResponse<StatisticalOlsContextResponse>(response);
}
