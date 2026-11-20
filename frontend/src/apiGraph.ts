import { readResponse } from "./api";
import { type PipelineDraftResponse } from "./api";
import { draftUrl } from "./api";
import { apiUrl } from "./api";
import type { Schema } from "./apiTypes";
import type { HeadSetResponse } from "./lineage/api/graphViewTypes";
import type { ManualRerunPatch } from "./lineage/detail/sections/manualRerunPatch";
// ── v1.6.8 — graph-native genesis (uploads / genesis draft / node patch / project forest) ──

export type UploadResult = Schema<"UploadStored">;

/** Upload a dataset file standalone (POST /uploads, multipart form).
 *  Content-addressable: the server stores by sha256 so genesis draft chains
 *  fully rehydrate after reload. */
export async function uploadDataset(
  projectRoot: string,
  file: File,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("project_root", projectRoot);
  form.append("file", file);
  const response = await fetch(apiUrl("/uploads"), {
    method: "POST",
    body: form,
  });
  return readResponse<UploadResult>(response);
}

export type PipelineDraftGenesisRequest = Schema<"PipelineDraftGenesisRequest">;

/** Create a parentless genesis draft chain (source → table → model). */
export async function createGenesisDraft(
  projectRoot: string,
  body: PipelineDraftGenesisRequest,
): Promise<PipelineDraftResponse> {
  const response = await fetch(draftUrl(projectRoot, "/pipeline-drafts/genesis"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<PipelineDraftResponse>(response);
}

export type DraftNodePatchRequest = Schema<"DraftNodePatchRequest">;

/** Configure one genesis draft node in place (PATCH .../nodes/{nodeId}).
 *  `columns` applies to table nodes only. */
export async function patchDraftNode(
  projectRoot: string,
  draftId: string,
  nodeId: string,
  body: DraftNodePatchRequest,
): Promise<PipelineDraftResponse> {
  const response = await fetch(
    draftUrl(
      projectRoot,
      `/pipeline-drafts/${encodeURIComponent(draftId)}/nodes/${encodeURIComponent(nodeId)}`,
    ),
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return readResponse<PipelineDraftResponse>(response);
}

/** Fetch the project-level forest (GET /graph — union of all family
 *  head-sets; empty forest for zero-run projects). Body shape is parity with
 *  the per-run headset view, so it feeds the same adaptHeadSet. */
export async function fetchProjectForest(
  projectRoot: string,
): Promise<HeadSetResponse> {
  const response = await fetch(
    apiUrl(`/graph?project_root=${encodeURIComponent(projectRoot)}`),
  );
  return readResponse<HeadSetResponse>(response);
}

// ── v1.6.1 — head-set (cross-run forest) graph + node rerun ──

/** Fetch the family head-set (union DAG across the rerun forest). */
export async function getRunGraphHeadSet(
  projectRoot: string,
  runId: string,
): Promise<HeadSetResponse> {
  const url = apiUrl(
    `/runs/${encodeURIComponent(runId)}/graph?project_root=${encodeURIComponent(
      projectRoot,
    )}&view=headset`,
  );
  const response = await fetch(url);
  return readResponse<HeadSetResponse>(response);
}

export interface NodeWriteOperationRequestV1 {
  request_id: string;
  operation: "rerun";
  context_version: "node-operation-context/v1";
  context_fingerprint: string;
  owner_run_id: string;
  op_node_id: string;
  node_hash: string;
  forest_node_key: string;
  owner_resolution: string;
  active_head_run_id: string | null;
  op_overrides: Record<string, unknown>;
  manual_patch?: ManualRerunPatch;
  rerun_reason?: string;
}

export type RerunResponseV1 = Schema<"RerunSubmitted">;

export interface LegacyRerunFromNodeArgs {
  fromNode: string;
  opOverrides: Record<string, unknown>;
  rerunReason?: string;
}

function isNodeWriteOperationRequestV1(
  args: LegacyRerunFromNodeArgs | NodeWriteOperationRequestV1,
): args is NodeWriteOperationRequestV1 {
  return (
    "operation" in args &&
    args.operation === "rerun" &&
    "context_version" in args &&
    args.context_version === "node-operation-context/v1"
  );
}

/** Create a child run by editing one node's operation (POST /runs/{id}/rerun).
 *  Legacy callers may still pass `fromNode`; context-driven callers submit the
 *  validated NodeOperationContext write target. */
export async function rerunFromNode(
  projectRoot: string,
  runId: string,
  args: LegacyRerunFromNodeArgs | NodeWriteOperationRequestV1,
): Promise<RerunResponseV1> {
  const url = apiUrl(
    `/runs/${encodeURIComponent(runId)}/rerun?project_root=${encodeURIComponent(projectRoot)}`,
  );
  const body = isNodeWriteOperationRequestV1(args)
    ? {
        ...args,
        from_node: args.op_node_id,
        rerun_reason: args.rerun_reason ?? "manual_override",
      }
    : {
        from_node: args.fromNode,
        op_overrides: args.opOverrides,
        rerun_reason: args.rerunReason ?? "manual_override",
      };
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<RerunResponseV1>(response);
}

export type RunProgressEvent = {
  event: "step_start" | "step_complete" | "step_blocked"
       | "workflow_completed" | "workflow_blocked"
       | "workflow_failed" | "workflow_interrupted";
  run_id: string;
  sequence: number;
  timestamp: string;
  step: string | null;
  message: string;
  status: string | null;
};

export type RunProgressCallbacks = {
  onStepStart?: (step: string, msg: string) => void;
  onStepComplete?: (step: string, msg: string) => void;
  onStepBlocked?: (step: string, msg: string) => void;
  onTerminal?: (status: string, msg: string) => void;
  onError?: (err: Error) => void;
};

export function connectRunEvents(
  projectRoot: string,
  runId: string,
  callbacks: RunProgressCallbacks,
): () => void {
  const url = apiUrl(
    `/runs/${encodeURIComponent(runId)}/events?project_root=${encodeURIComponent(projectRoot)}`,
  );
  const source = new EventSource(url);

  source.addEventListener("step_start", (e: MessageEvent) => {
    const data = JSON.parse(e.data) as RunProgressEvent;
    callbacks.onStepStart?.(data.step ?? "", data.message);
  });
  source.addEventListener("step_complete", (e: MessageEvent) => {
    const data = JSON.parse(e.data) as RunProgressEvent;
    callbacks.onStepComplete?.(data.step ?? "", data.message);
  });
  source.addEventListener("step_blocked", (e: MessageEvent) => {
    const data = JSON.parse(e.data) as RunProgressEvent;
    callbacks.onStepBlocked?.(data.step ?? "", data.message);
  });

  const handleTerminal = (e: MessageEvent) => {
    const data = JSON.parse(e.data) as RunProgressEvent;
    callbacks.onTerminal?.(data.status ?? "unknown", data.message);
    source.close();
  };
  source.addEventListener("workflow_completed", handleTerminal);
  source.addEventListener("workflow_blocked", handleTerminal);
  source.addEventListener("workflow_failed", handleTerminal);
  source.addEventListener("workflow_interrupted", handleTerminal);

  source.onerror = () => callbacks.onError?.(new Error("SSE connection error"));
  return () => source.close();
}

