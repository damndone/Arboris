// v1.6.7 — DraftRegistry: single source of truth for active in-graph drafts.
// Keyed by draftId (= the persistent server key), so session-created drafts
// and reload-hydrated drafts are homogeneous. See spec §4.1.

import type {
  DraftValidationResult,
  PipelineDraftSummary,
  PipelineDraftV1,
} from "../../api";
import type { LifecycleState } from "../api/graphViewTypes";

export interface DraftEntry {
  draftId: string;
  draft: PipelineDraftV1 | null; // null until first GET (hydrate defers load)
  draftHash: string;
  validation: DraftValidationResult | null;
  lifecycleState: LifecycleState;
  // Anchor is resolved against the live forest by node_hash (see mergeDraftsIntoModel).
  sourceNodeHash: string | null;
  sourceOpNodeId: string | null;
  modelType: string | null;
}

export type DraftRegistry = ReadonlyMap<string, DraftEntry>;

export function emptyRegistry(): DraftRegistry {
  return new Map();
}

export type DraftAction =
  | { type: "put"; draftId: string; draft: PipelineDraftV1; draftHash: string }
  | { type: "patch"; draftId: string; draft: PipelineDraftV1; draftHash: string }
  | { type: "validating"; draftId: string }
  | { type: "validated"; draftId: string; validation: DraftValidationResult; draftHash: string }
  | { type: "executing"; draftId: string }
  | { type: "failed"; draftId: string }
  | { type: "revertToDraft"; draftId: string }
  | { type: "remove"; draftId: string }
  | { type: "hydrate"; summaries: PipelineDraftSummary[] };

function createdFromHash(draft: PipelineDraftV1): string | null {
  return draft.created_from?.source_node_hash ?? null;
}
function createdFromOp(draft: PipelineDraftV1): string | null {
  return draft.created_from?.source_op_node_id ?? null;
}
function modelTypeOf(draft: PipelineDraftV1): string | null {
  const model = draft.graph.nodes.find((n) => n.node_type === "model");
  return (model && "model_type" in model ? (model.model_type as string) : null) ?? null;
}

export function draftReducer(state: DraftRegistry, action: DraftAction): DraftRegistry {
  const next = new Map(state);
  switch (action.type) {
    case "put":
    case "patch": {
      const prev = next.get(action.draftId);
      next.set(action.draftId, {
        draftId: action.draftId,
        draft: action.draft,
        draftHash: action.draftHash,
        validation: null,
        lifecycleState: "draft",
        sourceNodeHash: createdFromHash(action.draft) ?? prev?.sourceNodeHash ?? null,
        sourceOpNodeId: createdFromOp(action.draft) ?? prev?.sourceOpNodeId ?? null,
        modelType: modelTypeOf(action.draft) ?? prev?.modelType ?? null,
      });
      return next;
    }
    case "validating": {
      const prev = next.get(action.draftId);
      if (prev) next.set(action.draftId, { ...prev, lifecycleState: "validating" });
      return next;
    }
    case "validated": {
      const prev = next.get(action.draftId);
      if (prev) {
        next.set(action.draftId, {
          ...prev,
          validation: action.validation,
          draftHash: action.draftHash,
          lifecycleState: action.validation.status === "valid" ? "valid" : "invalid",
        });
      }
      return next;
    }
    case "executing": {
      const prev = next.get(action.draftId);
      if (prev) next.set(action.draftId, { ...prev, lifecycleState: "pending" });
      return next;
    }
    case "failed": {
      const prev = next.get(action.draftId);
      if (prev) next.set(action.draftId, { ...prev, lifecycleState: "failed" });
      return next;
    }
    case "revertToDraft": {
      const prev = next.get(action.draftId);
      if (prev) next.set(action.draftId, { ...prev, lifecycleState: "draft", validation: null });
      return next;
    }
    case "remove": {
      next.delete(action.draftId);
      return next;
    }
    case "hydrate": {
      for (const s of action.summaries) {
        if (next.has(s.draft_id)) continue; // never clobber a live session draft
        next.set(s.draft_id, {
          draftId: s.draft_id,
          draft: null,
          draftHash: s.draft_hash,
          validation: null,
          lifecycleState: "draft",
          sourceNodeHash: s.source_node_hash ?? null,
          sourceOpNodeId: s.source_op_node_id ?? null,
          modelType: s.model_type ?? null,
        });
      }
      return next;
    }
    default:
      return next;
  }
}
