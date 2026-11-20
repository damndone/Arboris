import { apiUrl } from "./api";
import { readResponse } from "./api";
import type { ResponseOf, Schema } from "./apiTypes";
// ── v1.8 slice C: durable comparison nodes ──
// A comparison is stored server-side and projected into the forest as a node
// joining its two endpoints, so a conclusion survives a reload.

export type CompareNodeEndpoint = Schema<"CompareEndpoint">;

export type CompareNodeRecord = Schema<"CompareNodeView">;

export async function createCompareNode(
  projectRoot: string,
  left: { runId: string; nodeId: string },
  right: { runId: string; nodeId: string },
): Promise<CompareNodeRecord> {
  const response = await fetch(
    apiUrl(`/compare-nodes?project_root=${encodeURIComponent(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        left: { run_id: left.runId, node_id: left.nodeId },
        right: { run_id: right.runId, node_id: right.nodeId },
      }),
    },
  );
  return readResponse<CompareNodeRecord>(response);
}

export async function deleteCompareNode(
  projectRoot: string,
  compareId: string,
): Promise<ResponseOf<"/compare-nodes/{compare_id}", "delete">> {
  const response = await fetch(
    apiUrl(
      `/compare-nodes/${encodeURIComponent(compareId)}?project_root=${encodeURIComponent(projectRoot)}`,
    ),
    { method: "DELETE" },
  );
  return readResponse<ResponseOf<"/compare-nodes/{compare_id}", "delete">>(response);
}

// v1.8.9 step 5 — SPSS/Stata dataset export with a loss report.

export type DatasetExportFormat = Schema<"DatasetExportReport">["format"];

export type DatasetExportNote = Schema<"DatasetExportNote">;

export type DatasetExportResult = Schema<"DatasetExportResult">;

export type DatasetExportFilter = { column: string; op: string; value?: unknown };

/** What to export and how, like Stata's export/save options. */
export type DatasetExportOptions = {
  format: DatasetExportFormat;
  columns?: string[] | null;
  filters?: DatasetExportFilter[];
  dta_version?: 13 | 14 | 15;
  value_labels?: "labels" | "strings" | "none";
  missing_codes?: "as_missing" | "keep_codes";
  filename?: string | null;
};

export type DatasetExportPreview = Schema<"DatasetExportPreview">;

function exportBody(nodeId: string, options: DatasetExportFormat | DatasetExportOptions): string {
  const chosen = typeof options === "string" ? { format: options } : options;
  const body: Record<string, unknown> = { node_id: nodeId, ...chosen };
  for (const key of Object.keys(body)) {
    if (body[key] === null || body[key] === undefined || body[key] === "") delete body[key];
  }
  return JSON.stringify(body);
}

export async function exportDataset(
  projectRoot: string,
  runId: string,
  nodeId: string,
  options: DatasetExportFormat | DatasetExportOptions,
): Promise<DatasetExportResult> {
  const response = await fetch(
    apiUrl(
      `/runs/${encodeURIComponent(runId)}/datasets/export?project_root=${encodeURIComponent(projectRoot)}`,
    ),
    { method: "POST", headers: { "Content-Type": "application/json" }, body: exportBody(nodeId, options) },
  );
  return readResponse<DatasetExportResult>(response);
}

export type AnalysisScriptExportResult = Schema<"ScriptExportResult">;

export type ScriptExportTargets = Schema<"ScriptExportTargets">;

export async function listScriptExportTargets(projectRoot: string, runId: string, modelTarget: string): Promise<ScriptExportTargets> {
  const response = await fetch(apiUrl(`/runs/${encodeURIComponent(runId)}/script-export/targets?project_root=${encodeURIComponent(projectRoot)}&model_target=${encodeURIComponent(modelTarget)}`));
  return readResponse<ScriptExportTargets>(response);
}

export async function exportAnalysisScript(projectRoot: string, runId: string, target: string,
  language: 'stata' | 'r' | 'python', requireNative: boolean): Promise<AnalysisScriptExportResult> {
  const response = await fetch(apiUrl(`/runs/${encodeURIComponent(runId)}/script-export?project_root=${encodeURIComponent(projectRoot)}`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, language, require_native: requireNative }),
  });
  return readResponse<AnalysisScriptExportResult>(response);
}

/** Exactly what the file will contain, without writing it. */
export async function previewDatasetExport(
  projectRoot: string,
  runId: string,
  nodeId: string,
  options: DatasetExportOptions,
): Promise<DatasetExportPreview> {
  const response = await fetch(
    apiUrl(
      `/runs/${encodeURIComponent(runId)}/datasets/export/preview?project_root=${encodeURIComponent(projectRoot)}`,
    ),
    { method: "POST", headers: { "Content-Type": "application/json" }, body: exportBody(nodeId, options) },
  );
  return readResponse<DatasetExportPreview>(response);
}

