import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  executePipelineDraft,
  getPipelineDraft,
  patchPipelineDraftParams,
  validatePipelineDraft,
  type DraftValidationResult,
  type PipelineDraftV1,
} from "../api";
import { DraftGraphCanvas } from "./DraftGraphCanvas";
import { ModelNodeInspector } from "./ModelNodeInspector";

export function DraftGraphRoute() {
  const { draftId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const projectRoot = searchParams.get("project_root") ?? "";
  const [draft, setDraft] = useState<PipelineDraftV1 | null>(null);
  const [draftHash, setDraftHash] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [validation, setValidation] = useState<DraftValidationResult | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getPipelineDraft(projectRoot, draftId).then((res) => {
      if (cancelled) return;
      setDraft(res.draft);
      setDraftHash(res.draft_hash);
      setSelectedNodeId(res.draft.graph.nodes[0]?.node_id ?? null);
    });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, draftId]);

  const selectedNode = useMemo(
    () => draft?.graph.nodes.find((node) => node.node_id === selectedNodeId) ?? null,
    [draft, selectedNodeId],
  );
  const validatedHash = validation?.validated_draft_hash;
  const canExecute = Boolean(
    draft && !isSaving && validation?.status === "valid" && validatedHash === draftHash,
  );

  if (!draft) return <section className="panel">Loading draft...</section>;

  return (
    <section className="panel" aria-label="Draft Graph">
      <div className="panel-heading">
        <h2>Draft Graph</h2>
        <span>{draft.draft_id}</span>
      </div>
      <div className="draft-toolbar">
        <span>{validation && validatedHash !== draftHash ? "Validation stale" : "Saved"}</span>
        <button
          type="button"
          disabled={isSaving}
          onClick={async () => {
            setValidation(await validatePipelineDraft(projectRoot, draftId, "rerun_child"));
          }}
        >
          Validate
        </button>
        <button
          type="button"
          disabled={!canExecute}
          onClick={async () => {
            const result = await executePipelineDraft(projectRoot, draftId, {
              validated_draft_hash: validatedHash ?? "",
              execution_mode: "rerun_child",
            });
            const params = new URLSearchParams({ project_root: projectRoot, tab: "lineage" });
            if (result.focus.target_model_node_id) {
              params.set("focus", result.focus.target_model_node_id);
            }
            if (result.focus.status === "pending_index" && result.focus.poll) {
              params.set("pending_source_run_id", result.focus.poll.rerun_from_run_id);
              params.set("pending_source_model_node_id", result.focus.poll.rerun_from_model_node_id);
              params.set("pending_source_op_node_id", result.focus.poll.rerun_from_op_node_id);
            }
            navigate(`/runs/${result.run_id}?${params.toString()}`);
          }}
        >
          Execute Draft
        </button>
      </div>
      <DraftGraphCanvas
        draft={draft}
        selectedNodeId={selectedNodeId}
        onSelectNode={setSelectedNodeId}
      />
      {selectedNode?.node_type === "input.dataset" && (
        <section aria-label="Input node inspector">
          <h2>InputNode</h2>
          <p>{selectedNode.run_input_id}</p>
          <p>{selectedNode.input_fingerprint}</p>
        </section>
      )}
      {selectedNode?.node_type === "model" && (
        <ModelNodeInspector
          node={selectedNode}
          draftHash={draftHash}
          onSave={async (body) => {
            setIsSaving(true);
            try {
              const res = await patchPipelineDraftParams(projectRoot, draftId, body);
              setDraft(res.draft);
              setDraftHash(res.draft_hash);
              setValidation(null);
            } finally {
              setIsSaving(false);
            }
          }}
        />
      )}
      {validation && (
        <section aria-label="Validation panel">
          {validation.checks.map((check) => (
            <p key={`${check.code}:${check.node_id ?? ""}`}>
              {check.code}: {check.message}
            </p>
          ))}
        </section>
      )}
    </section>
  );
}
