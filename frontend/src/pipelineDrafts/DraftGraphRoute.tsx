import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ApiError,
  executePipelineDraft,
  getPipelineDraft,
  patchPipelineDraftParams,
  validatePipelineDraft,
  waitForRunTerminal,
  type DraftValidationResult,
  type PipelineDraftV1,
} from "../api";
import { completeNotebookOptionExecution } from "../notebook/notebookApi";
import { DraftGraphCanvas } from "./DraftGraphCanvas";
import { ModelNodeInspector } from "./ModelNodeInspector";
import { rootToSlug } from "../workbench/projectSlug";

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

  // v1.6.5 (P6): return to the source run's lineage. The draft records its
  // origin run in `created_from`; fall back to the bound input node's
  // `run_input_id` for older drafts that lack it.
  const sourceRunId =
    draft?.created_from?.source_run_id ??
    draft?.graph.nodes.find(
      (n): n is Extract<typeof n, { node_type: "input.dataset" }> =>
        n.node_type === "input.dataset",
    )?.run_input_id ??
    null;
  const executionMode = draft?.default_execution_mode ?? "rerun_child";
  const returnTo = searchParams.get("return_to");
  const notebookId =
    draft?.notebook_provenance?.notebook_id ?? searchParams.get("notebook");
  const draftModelNodeKey = `draft:${draftId}:model_1`;
  const goBackToLineage = () => {
    if (returnTo) {
      navigate(returnTo);
      return;
    }
    if (!sourceRunId && !projectRoot) return;
    if (!sourceRunId) {
      const params = new URLSearchParams({ view: "graph" });
      if (notebookId) params.set("notebook", notebookId);
      params.set("tabs", draftModelNodeKey);
      params.set("active", draftModelNodeKey);
      params.set("focus", draftModelNodeKey);
      navigate(`/p/${rootToSlug(projectRoot)}/graph?${params.toString()}`);
      return;
    }
    const params = new URLSearchParams({ project_root: projectRoot, tab: "lineage" });
    navigate(`/runs/${sourceRunId}?${params.toString()}`);
  };
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

  const modelNode = draft.graph.nodes.find((n) => n.node_type === "model");
  const modelType = modelNode && "model_type" in modelNode ? modelNode.model_type : "";
  const draftState = hasUnsavedChanges
    ? "Unsaved"
    : isValidationStale
      ? "Validation stale"
      : "Saved";

  return (
    <section className="panel draft-layout" aria-label="Draft Graph">
      {/* §6.3 Toolbar: back · title · source run/model · state · Validate · Execute */}
      <header className="draft-toolbar" aria-label="Draft toolbar">
        <button
          type="button"
          className="draft-back-link"
          onClick={goBackToLineage}
          disabled={!sourceRunId && !projectRoot && !returnTo}
        >
          ← Back to Lineage
        </button>
        <div className="draft-toolbar__title">
          <h2>Draft Graph</h2>
          <span className="draft-toolbar__source">
            {sourceRunId ? `source: ${sourceRunId}` : draft.draft_id}
            {modelType ? ` · ${modelType}` : ""}
          </span>
        </div>
        <span className="draft-toolbar__state" data-state={draftState}>
          {draftState}
        </span>
        <div className="draft-toolbar__actions">
          <button
            type="button"
            disabled={isSaving || isValidating || hasUnsavedChanges}
            onClick={async () => {
              setIsValidating(true);
              setError(null);
              try {
                setValidation(await validatePipelineDraft(projectRoot, draftId, executionMode));
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
                  execution_mode: executionMode,
                });
                const provenance = draft.notebook_provenance;
                if (provenance?.notebook_id && provenance.option_id) {
                  // Draft execution is asynchronous. Reconcile the Notebook
                  // only after the real run reaches a terminal state, so the
                  // active head and Artifact Contract never advance on a
                  // merely-dispatched or still-running run.
                  void waitForRunTerminal(projectRoot, result.run_id).then((detail) => {
                    if (!detail) return;
                    const succeeded = detail.status === "completed";
                    return completeNotebookOptionExecution(
                      projectRoot,
                      provenance.notebook_id,
                      provenance.option_id,
                      {
                        execution_status: succeeded ? "succeeded" : "failed",
                        run_id: result.run_id,
                        ...(succeeded
                          ? {}
                          : {
                              error_code:
                                detail.errors?.issues?.[0]?.code ??
                                "WORKFLOW_NOT_COMPLETED",
                            }),
                      },
                    );
                  }).catch(() => {
                    // The run remains authoritative; a later Notebook mount
                    // can retry reconciliation from the persisted draft.
                  });
                }
                const params = new URLSearchParams({ project_root: projectRoot, tab: "lineage" });
                if (result.focus.target_model_node_id) {
                  params.set("focus", result.focus.target_model_node_id);
                }
                const poll = result.focus.poll;
                if (
                  result.focus.status === "pending_index" &&
                  poll?.rerun_from_run_id &&
                  poll.rerun_from_model_node_id &&
                  poll.rerun_from_op_node_id
                ) {
                  params.set("pending_source_run_id", poll.rerun_from_run_id);
                  params.set("pending_source_model_node_id", poll.rerun_from_model_node_id);
                  params.set("pending_source_op_node_id", poll.rerun_from_op_node_id);
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
      </header>

      {error && (
        <p role="alert" className="draft-error">
          {error}
        </p>
      )}

      <div className="draft-body">
        {/* §6.3 Canvas region */}
        <section className="draft-canvas-region" aria-label="Draft canvas">
          <DraftGraphCanvas
            draft={draft}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
          />
        </section>

        {/* §6.3 Inspector + Validation side panel */}
        <aside className="draft-side">
          {selectedNode?.node_type === "input.dataset" && (
            <section className="draft-inspector" aria-label="Input node inspector">
              <h2>InputNode</h2>
              <dl>
                <dt>run_input_id</dt>
                <dd>{selectedNode.run_input_id}</dd>
                <dt>input_fingerprint</dt>
                <dd>{selectedNode.input_fingerprint}</dd>
              </dl>
            </section>
          )}
          {selectedNode?.node_type === "model" && (
            <section className="draft-inspector" aria-label="Model node inspector wrapper">
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
            </section>
          )}
          {validation && (
            <section className="draft-validation" aria-label="Validation panel">
              <h3>Validation</h3>
              {validation.checks.length === 0 ? (
                <p className="draft-validation__ok">No blocking issues.</p>
              ) : (
                <ul>
                  {validation.checks.map((check) => (
                    <li key={`${check.code}:${check.node_id ?? ""}`}>
                      {check.code}: {check.message}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
        </aside>
      </div>
    </section>
  );
}
