import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ApiError,
  executePipelineDraft,
  getPipelineDraft,
  patchPipelineDraftParams,
  validatePipelineDraft,
  type DraftValidationResult,
  type PipelineDraftV1,
} from "../api";
import { DraftGraphCanvas } from "./DraftGraphCanvas";
import { ModelNodeInspector } from "./ModelNodeInspector";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return "Request failed";
}

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
  const [isLoading, setIsLoading] = useState(true);
  const [isValidating, setIsValidating] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [validationStale, setValidationStale] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    getPipelineDraft(projectRoot, draftId)
      .then((res) => {
        if (cancelled) return;
        setDraft(res.draft);
        setDraftHash(res.draft_hash);
        setSelectedNodeId(res.draft.graph.nodes[0]?.node_id ?? null);
      })
      .catch((loadError: unknown) => {
        if (cancelled) return;
        setError(errorMessage(loadError));
      })
      .finally(() => {
        if (cancelled) return;
        setIsLoading(false);
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
  const isValidationStale = Boolean(validationStale || (validation && validatedHash !== draftHash));
  const canExecute = Boolean(
    draft
      && !isSaving
      && !isExecuting
      && !hasUnsavedChanges
      && validation?.status === "valid"
      && validatedHash === draftHash,
  );

  if (!draft) {
    return (
      <section className="panel">
        {isLoading ? "Loading draft..." : null}
        {error && <p role="alert">{error}</p>}
      </section>
    );
  }

  return (
    <section className="panel" aria-label="Draft Graph">
      <div className="panel-heading">
        <h2>Draft Graph</h2>
        <span>{draft.draft_id}</span>
      </div>
      <div className="draft-toolbar">
        <span>{hasUnsavedChanges ? "Unsaved" : isValidationStale ? "Validation stale" : "Saved"}</span>
        <button
          type="button"
          disabled={isSaving || isValidating || hasUnsavedChanges}
          onClick={async () => {
            setIsValidating(true);
            setError(null);
            try {
              setValidation(await validatePipelineDraft(projectRoot, draftId, "rerun_child"));
              setValidationStale(false);
            } catch (validateError) {
              setValidation(null);
              setError(errorMessage(validateError));
            } finally {
              setIsValidating(false);
            }
          }}
        >
          Validate
        </button>
        <button
          type="button"
          disabled={!canExecute}
          onClick={async () => {
            setIsExecuting(true);
            setError(null);
            try {
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
            } catch (executeError) {
              setError(errorMessage(executeError));
            } finally {
              setIsExecuting(false);
            }
          }}
        >
          Execute Draft
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
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
          onDirtyChange={setHasUnsavedChanges}
          onSave={async (body) => {
            setIsSaving(true);
            setError(null);
            try {
              const res = await patchPipelineDraftParams(projectRoot, draftId, body);
              setDraft(res.draft);
              setDraftHash(res.draft_hash);
              setValidation(null);
              setValidationStale(true);
              setHasUnsavedChanges(false);
            } catch (error) {
              const status = error instanceof ApiError
                ? error.status
                : (error as { status?: unknown })?.status;
              if (status === 409) {
                const latest = await getPipelineDraft(projectRoot, draftId);
                setDraft(latest.draft);
                setDraftHash(latest.draft_hash);
                setValidation(null);
                setValidationStale(true);
                setHasUnsavedChanges(false);
                return;
              }
              setError(errorMessage(error));
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
