// frontend/src/workbench/useDraftHandlers.ts
//
// v1.6.9 B1-3 — cohesion cluster extracted from WorkbenchRouteContainer's
// ForestWorkbench (spec §4.4). Owns the draft fork / patch / validate / discard /
// ensure-loaded handlers, the genesis-wizard pure dispatches, and the
// mount-time draft-hydration effect. These all share one concern: mutate the
// DraftRegistry via `dispatchDraft` (+ toggle `draftBusy`) in response to draft
// lifecycle actions.
//
// State ownership: `registry` / `dispatchDraft` and `draftBusy` / `setDraftBusy`
// STAY in the container and are passed IN — the handlers only need to dispatch
// and toggle busy, and `handleExecuteDraft` (which reads `registry` and calls
// both) MUST stay in the container because it owns container-level pending-run
// state (activeRunId / pendingRerunFocus / pendingRerunRun). Passing state in +
// getting handlers out keeps that execute path working naturally.
//
// Move is VERBATIM: busy wrapping, console.error messages, and best-effort
// catches are identical to the former inline container handlers.

import { useEffect, useState } from "react";
import {
  listPipelineDrafts,
  getPipelineDraft,
  validatePipelineDraft,
  patchPipelineDraftParams,
  deletePipelineDraft,
  type PipelineDraftResponse,
  type PipelineDraftPatchRequest,
  type DraftValidationResult,
} from "../api";
import type { DraftAction, DraftRegistry } from "../lineage/drafts/draftRegistry";

export interface UseDraftHandlersParams {
  projectRoot: string;
  registry: DraftRegistry;
  dispatchDraft: (action: DraftAction) => void;
  setDraftBusy: (busy: boolean) => void;
}

export interface DraftActionHandlers {
  errors: Readonly<Record<string, string>>;
  onForkDraft: (created: PipelineDraftResponse) => void;
  onPatch: (draftId: string, body: PipelineDraftPatchRequest) => Promise<void>;
  onValidate: (draftId: string) => Promise<void>;
  onDiscard: (draftId: string) => Promise<void>;
  onEnsureLoaded: (draftId: string) => Promise<void>;
  onGenesisDraftUpdated: (response: PipelineDraftResponse) => void;
  onGenesisDraftValidated: (
    draftId: string,
    validation: DraftValidationResult,
  ) => void;
  onGenesisDraftExecuting: (draftId: string) => void;
  onGenesisDraftFailed: (draftId: string) => void;
}

export function useDraftHandlers({
  projectRoot,
  registry,
  dispatchDraft,
  setDraftBusy,
}: UseDraftHandlersParams): DraftActionHandlers {
  const [errors, setErrors] = useState<Record<string, string>>({});
  const clearError = (draftId: string) => {
    setErrors((current) => {
      if (!(draftId in current)) return current;
      const next = { ...current };
      delete next[draftId];
      return next;
    });
  };
  const recordError = (draftId: string, error: unknown) => {
    setErrors((current) => ({
      ...current,
      [draftId]: error instanceof Error ? error.message : String(error),
    }));
  };
  // Hydrate persisted (unexecuted) drafts onto the forest on mount so drafts
  // survive a page reload. Best-effort: never block the forest if it fails.
  useEffect(() => {
    let cancelled = false;
    listPipelineDrafts(projectRoot)
      .then(async (summaries) => {
        if (cancelled) return;
        const unexecuted = summaries.filter((s) => s.status !== "executed");
        if (unexecuted.length) {
          dispatchDraft({ type: "hydrate", summaries: unexecuted });
        }
        const unanchored = unexecuted.filter(
          (s) => !s.source_node_hash && !s.source_op_node_id,
        );
        if (unanchored.length === 0) return;
        const loaded = await Promise.allSettled(
          unanchored.map((s) => getPipelineDraft(projectRoot, s.draft_id)),
        );
        if (cancelled) return;
        for (const res of loaded) {
          if (res.status !== "fulfilled") continue;
          dispatchDraft({
            type: "put",
            draftId: res.value.draft.draft_id,
            draft: res.value.draft,
            draftHash: res.value.draft_hash,
          });
        }
      })
      .catch(() => {
        /* drafts are best-effort; never block the forest */
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot]);

  const onForkDraft = (created: PipelineDraftResponse) => {
    dispatchDraft({
      type: "put",
      draftId: created.draft.draft_id,
      draft: created.draft,
      draftHash: created.draft_hash,
    });
  };

  const onPatch = async (
    draftId: string,
    body: PipelineDraftPatchRequest,
  ) => {
    setDraftBusy(true);
    clearError(draftId);
    try {
      const res = await patchPipelineDraftParams(projectRoot, draftId, body);
      dispatchDraft({ type: "patch", draftId, draft: res.draft, draftHash: res.draft_hash });
    } catch (e) {
      recordError(draftId, e);
      console.error("draft patch failed", e);
    } finally {
      setDraftBusy(false);
    }
  };

  const onValidate = async (draftId: string) => {
    setDraftBusy(true);
    clearError(draftId);
    dispatchDraft({ type: "validating", draftId });
    try {
      const v = await validatePipelineDraft(projectRoot, draftId, "rerun_child");
      dispatchDraft({
        type: "validated",
        draftId,
        validation: v,
        draftHash: v.validated_draft_hash ?? "",
      });
    } catch (e) {
      dispatchDraft({ type: "revertToDraft", draftId });
      recordError(draftId, e);
      console.error("draft validate failed", e);
    } finally {
      setDraftBusy(false);
    }
  };

  const onDiscard = async (draftId: string) => {
    setDraftBusy(true);
    clearError(draftId);
    try {
      await deletePipelineDraft(projectRoot, draftId);
      dispatchDraft({ type: "remove", draftId });
    } catch (e) {
      recordError(draftId, e);
      console.error("draft discard failed", e);
    } finally {
      setDraftBusy(false);
    }
  };

  const onEnsureLoaded = async (draftId: string) => {
    const entry = registry.get(draftId);
    if (!entry || entry.draft !== null) return;
    try {
      const res = await getPipelineDraft(projectRoot, draftId);
      dispatchDraft({ type: "put", draftId, draft: res.draft, draftHash: res.draft_hash });
    } catch {
      recordError(draftId, "Unable to load this draft. Retry after checking the project state.");
    }
  };

  const onGenesisDraftUpdated = (response: PipelineDraftResponse) => {
    dispatchDraft({
      type: "put",
      draftId: response.draft.draft_id,
      draft: response.draft,
      draftHash: response.draft_hash,
    });
  };

  const onGenesisDraftValidated = (
    draftId: string,
    validation: DraftValidationResult,
  ) => {
    const entry = registry.get(draftId);
    dispatchDraft({
      type: "validated",
      draftId,
      validation,
      draftHash: validation.validated_draft_hash ?? entry?.draftHash ?? "",
    });
  };

  const onGenesisDraftExecuting = (draftId: string) => {
    dispatchDraft({ type: "executing", draftId });
  };

  const onGenesisDraftFailed = (draftId: string) => {
    dispatchDraft({ type: "failed", draftId });
  };

  return {
    errors,
    onForkDraft,
    onPatch,
    onValidate,
    onDiscard,
    onEnsureLoaded,
    onGenesisDraftUpdated,
    onGenesisDraftValidated,
    onGenesisDraftExecuting,
    onGenesisDraftFailed,
  };
}
