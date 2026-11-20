import { useEffect, useState } from "react";
import { artifactUrl, readArtifact } from "../../../manual/manualApi";
import type { AnalysisReplay } from "../../../manual/OperationsPanel";
import { ResultValue } from "../../../manual/operations/ResultValue";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";
import { useWorkspaceCommands } from "../../../workspace/workspaceCommands";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";

const PREFIX = "native-result:";
const object = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;

function savedAnalysis(value: unknown, owner: string): AnalysisReplay | null {
  const envelope = object(value);
  const source = object(envelope?.source);
  const request = object(envelope?.request);
  if (source?.run_id !== owner || typeof source.node_ref !== "string" || typeof source.artifact_id !== "string"
      || typeof request?.operation_id !== "string" || request.operation_id !== source.operation_id) return null;
  const { operation_id: operationId, ...spec } = request;
  return { operationId, spec, target: { kind: "dataset_node", run_id: owner,
    node_id: source.node_ref, artifact_id: source.artifact_id } };
}
export function isNativeResearchResult(node: GraphViewNode): boolean {
  const id = "opNodeId" in node ? node.opNodeId : node.id;
  return typeof id === "string" && id.startsWith(PREFIX);
}

function SavedResearchResult({ root, runId, artifactId, ledger }: {
  root: string; runId: string; artifactId: string;
  ledger: { artifactId: string; rowCount: number } | { error: true } | null;
}) {
  const [view, setView] = useState<{ value: unknown } | { error: string } | null>(null);
  const commands = useWorkspaceCommands();
  useEffect(() => {
    let active = true;
    void readArtifact(root, runId, artifactId).then(response => response.json()).then(value => {
      if (active) setView({ value });
    }).catch((error: unknown) => {
      if (active) setView({ error: error instanceof Error ? error.message : String(error) });
    });
    return () => { active = false; };
  }, [root, runId, artifactId]);
  const replay = view && "value" in view ? savedAnalysis(view.value, runId) : null;
  return <section aria-label="Saved native research result">
    {view === null && <p role="status">Loading saved result…</p>}
    {view && "error" in view && <p role="alert">{view.error}</p>}
    {view && "value" in view && <>
      <div className="op-outcome__actions">
        {commands && replay && <button type="button" className="op-link" onClick={() => commands.analyze("", replay)}>Rerun this analysis</button>}
        <a className="op-link" href={artifactUrl(root, runId, artifactId)} target="_blank" rel="noreferrer">Download result JSON</a>
        {ledger && !("error" in ledger) && <a className="op-link" href={artifactUrl(root, runId, ledger.artifactId)} target="_blank" rel="noreferrer">
          Download full ledger CSV · {ledger.rowCount} periods
        </a>}
      </div>
      {ledger && "error" in ledger && <p role="alert">Saved ledger reference is invalid.</p>}
      <ResultValue value={view.value} />
    </>}
  </section>;
}

export function NativeResearchResultSection({ node }: { node: GraphViewNode }) {
  const root = useProjectRootOptional();
  const resolved = useResolvedNodeOperationContext();
  if (!root || !resolved?.ok) return <p>Saved result owner could not be resolved.</p>;
  const { owner_run_id: runId, op_node_id: nodeId } = resolved.context.operation_target;
  const artifactId = nodeId.slice(PREFIX.length);
  const annotations = object(node.raw)?.annotations;
  const entry = Array.isArray(annotations) ? annotations.map(object).find(item => item?.type === "quant_replay_ledger") : null;
  const ledger = entry ? (typeof entry.artifact_id === "string" && entry.artifact_id.startsWith("quant_replay_ledger_")
    && typeof entry.sha256 === "string" && /^[0-9a-f]{64}$/.test(entry.sha256)
    && typeof entry.row_count === "number" && Number.isInteger(entry.row_count) && entry.row_count >= 0
    ? { artifactId: entry.artifact_id, rowCount: entry.row_count } : { error: true as const }) : null;
  return <SavedResearchResult key={JSON.stringify([root, runId, artifactId])} root={root} runId={runId} artifactId={artifactId} ledger={ledger} />;
}
