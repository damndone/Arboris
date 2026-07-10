import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useDraftHandlers } from "./useDraftHandlers";
import type { DraftAction, DraftEntry, DraftRegistry } from "../lineage/drafts/draftRegistry";
import type {
  DraftValidationResult,
  PipelineDraftResponse,
  PipelineDraftSummary,
  PipelineDraftV1,
} from "../api";

vi.mock("../api", () => ({
  patchPipelineDraftParams: vi.fn(),
  validatePipelineDraft: vi.fn(),
  deletePipelineDraft: vi.fn(),
  getPipelineDraft: vi.fn(),
  listPipelineDrafts: vi.fn(),
}));
import {
  patchPipelineDraftParams,
  validatePipelineDraft,
  deletePipelineDraft,
  getPipelineDraft,
  listPipelineDrafts,
} from "../api";

const asMock = (fn: unknown) => fn as ReturnType<typeof vi.fn>;

const draft = (id: string): PipelineDraftV1 =>
  ({ draft_id: id }) as unknown as PipelineDraftV1;

const response = (id: string, hash: string): PipelineDraftResponse => ({
  draft: draft(id),
  draft_hash: hash,
});

const entry = (over: Partial<DraftEntry>): DraftEntry => ({
  draftId: "d1",
  draft: draft("d1"),
  draftHash: "h0",
  validation: null,
  lifecycleState: "draft",
  sourceNodeHash: null,
  sourceOpNodeId: null,
  modelType: null,
  ...over,
});

const registryOf = (...entries: DraftEntry[]): DraftRegistry =>
  new Map(entries.map((e) => [e.draftId, e]));

const summary = (over: Partial<PipelineDraftSummary>): PipelineDraftSummary => ({
  draft_id: "s1",
  status: "draft",
  draft_hash: "sh",
  ...over,
});

function setup(registry: DraftRegistry = new Map()) {
  const dispatchDraft = vi.fn<(a: DraftAction) => void>();
  const setDraftBusy = vi.fn<(b: boolean) => void>();
  const view = renderHook(() =>
    useDraftHandlers({
      projectRoot: "/p",
      registry,
      dispatchDraft,
      setDraftBusy,
    }),
  );
  return { ...view, dispatchDraft, setDraftBusy };
}

beforeEach(() => {
  // Default: mount hydration effect finds no drafts (no noise on other tests).
  asMock(listPipelineDrafts).mockResolvedValue([]);
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => vi.clearAllMocks());

describe("useDraftHandlers", () => {
  describe("onForkDraft", () => {
    it("dispatches put with the created draft + hash", () => {
      const { result, dispatchDraft } = setup();
      result.current.onForkDraft(response("d9", "h9"));
      expect(dispatchDraft).toHaveBeenCalledWith({
        type: "put",
        draftId: "d9",
        draft: draft("d9"),
        draftHash: "h9",
      });
    });
  });

  describe("onPatch", () => {
    it("dispatches patch on success and toggles busy around it", async () => {
      asMock(patchPipelineDraftParams).mockResolvedValue(response("d1", "h1"));
      const { result, dispatchDraft, setDraftBusy } = setup();
      await result.current.onPatch("d1", {
        model_node_id: "m",
        base_draft_hash: "h0",
        params: {},
      });
      expect(patchPipelineDraftParams).toHaveBeenCalledWith("/p", "d1", {
        model_node_id: "m",
        base_draft_hash: "h0",
        params: {},
      });
      expect(dispatchDraft).toHaveBeenCalledWith({
        type: "patch",
        draftId: "d1",
        draft: draft("d1"),
        draftHash: "h1",
      });
      expect(setDraftBusy.mock.calls).toEqual([[true], [false]]);
    });

    it("does not dispatch patch on failure but still clears busy + logs", async () => {
      asMock(patchPipelineDraftParams).mockRejectedValue(new Error("boom"));
      const { result, dispatchDraft, setDraftBusy } = setup();
      await result.current.onPatch("d1", {
        model_node_id: "m",
        base_draft_hash: "h0",
        params: {},
      });
      expect(dispatchDraft).not.toHaveBeenCalledWith(
        expect.objectContaining({ type: "patch" }),
      );
      expect(setDraftBusy.mock.calls).toEqual([[true], [false]]);
      expect(console.error).toHaveBeenCalled();
    });
  });

  describe("onValidate", () => {
    it("dispatches validating then validated with validated_draft_hash", async () => {
      const validation = {
        status: "valid",
        validated_draft_hash: "vh",
      } as unknown as DraftValidationResult;
      asMock(validatePipelineDraft).mockResolvedValue(validation);
      const { result, dispatchDraft, setDraftBusy } = setup();
      await result.current.onValidate("d1");
      expect(validatePipelineDraft).toHaveBeenCalledWith("/p", "d1", "rerun_child");
      expect(dispatchDraft).toHaveBeenNthCalledWith(1, {
        type: "validating",
        draftId: "d1",
      });
      expect(dispatchDraft).toHaveBeenNthCalledWith(2, {
        type: "validated",
        draftId: "d1",
        validation,
        draftHash: "vh",
      });
      expect(setDraftBusy.mock.calls).toEqual([[true], [false]]);
    });

    it("falls back to '' hash when validated_draft_hash is absent", async () => {
      const validation = { status: "invalid" } as unknown as DraftValidationResult;
      asMock(validatePipelineDraft).mockResolvedValue(validation);
      const { result, dispatchDraft } = setup();
      await result.current.onValidate("d1");
      expect(dispatchDraft).toHaveBeenCalledWith({
        type: "validated",
        draftId: "d1",
        validation,
        draftHash: "",
      });
    });

    it("dispatches revertToDraft on API error", async () => {
      asMock(validatePipelineDraft).mockRejectedValue(new Error("nope"));
      const { result, dispatchDraft, setDraftBusy } = setup();
      await result.current.onValidate("d1");
      expect(dispatchDraft).toHaveBeenNthCalledWith(1, {
        type: "validating",
        draftId: "d1",
      });
      expect(dispatchDraft).toHaveBeenCalledWith({
        type: "revertToDraft",
        draftId: "d1",
      });
      expect(dispatchDraft).not.toHaveBeenCalledWith(
        expect.objectContaining({ type: "validated" }),
      );
      expect(setDraftBusy.mock.calls).toEqual([[true], [false]]);
    });
  });

  describe("onDiscard", () => {
    it("deletes then dispatches remove", async () => {
      asMock(deletePipelineDraft).mockResolvedValue(undefined);
      const { result, dispatchDraft, setDraftBusy } = setup();
      await result.current.onDiscard("d1");
      expect(deletePipelineDraft).toHaveBeenCalledWith("/p", "d1");
      expect(dispatchDraft).toHaveBeenCalledWith({ type: "remove", draftId: "d1" });
      expect(setDraftBusy.mock.calls).toEqual([[true], [false]]);
    });

    it("does not dispatch remove on delete error", async () => {
      asMock(deletePipelineDraft).mockRejectedValue(new Error("fail"));
      const { result, dispatchDraft } = setup();
      await result.current.onDiscard("d1");
      expect(dispatchDraft).not.toHaveBeenCalledWith(
        expect.objectContaining({ type: "remove" }),
      );
      expect(console.error).toHaveBeenCalled();
    });
  });

  describe("onEnsureLoaded", () => {
    it("no-ops when the draft is already loaded", async () => {
      const reg = registryOf(entry({ draftId: "d1", draft: draft("d1") }));
      const { result, dispatchDraft } = setup(reg);
      await result.current.onEnsureLoaded("d1");
      expect(getPipelineDraft).not.toHaveBeenCalled();
      expect(dispatchDraft).not.toHaveBeenCalled();
    });

    it("fetches + dispatches put when the entry has draft:null", async () => {
      asMock(getPipelineDraft).mockResolvedValue(response("d1", "h2"));
      const reg = registryOf(entry({ draftId: "d1", draft: null }));
      const { result, dispatchDraft } = setup(reg);
      await result.current.onEnsureLoaded("d1");
      expect(getPipelineDraft).toHaveBeenCalledWith("/p", "d1");
      expect(dispatchDraft).toHaveBeenCalledWith({
        type: "put",
        draftId: "d1",
        draft: draft("d1"),
        draftHash: "h2",
      });
    });
  });

  describe("hydration effect", () => {
    it("hydrates ONLY unexecuted summaries and backfills unanchored drafts", async () => {
      asMock(listPipelineDrafts).mockResolvedValue([
        summary({ draft_id: "exec", status: "executed" }),
        summary({ draft_id: "anchored", source_node_hash: "nh" }),
        summary({ draft_id: "loose" }), // unanchored → gets backfill GET
      ]);
      asMock(getPipelineDraft).mockResolvedValue(response("loose", "lh"));
      const { dispatchDraft } = setup();

      await waitFor(() =>
        expect(dispatchDraft).toHaveBeenCalledWith(
          expect.objectContaining({ type: "hydrate" }),
        ),
      );

      const hydrateCall = dispatchDraft.mock.calls.find(
        ([a]) => a.type === "hydrate",
      )![0] as Extract<DraftAction, { type: "hydrate" }>;
      expect(hydrateCall.summaries.map((s) => s.draft_id)).toEqual([
        "anchored",
        "loose",
      ]);

      await waitFor(() =>
        expect(getPipelineDraft).toHaveBeenCalledWith("/p", "loose"),
      );
      await waitFor(() =>
        expect(dispatchDraft).toHaveBeenCalledWith({
          type: "put",
          draftId: "loose",
          draft: draft("loose"),
          draftHash: "lh",
        }),
      );
      // anchored draft is NOT backfilled.
      expect(getPipelineDraft).not.toHaveBeenCalledWith("/p", "anchored");
    });

    it("does not dispatch hydrate when there are no unexecuted drafts", async () => {
      asMock(listPipelineDrafts).mockResolvedValue([
        summary({ draft_id: "exec", status: "executed" }),
      ]);
      const { dispatchDraft } = setup();
      await waitFor(() => expect(listPipelineDrafts).toHaveBeenCalled());
      expect(dispatchDraft).not.toHaveBeenCalledWith(
        expect.objectContaining({ type: "hydrate" }),
      );
    });
  });
});
