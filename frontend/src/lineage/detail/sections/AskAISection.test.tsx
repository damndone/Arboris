import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ForestContext } from "../../../workbench/ForestContext";
import { makeOwnerResolutionSeedFixture } from "../../api/nodeOperationContext";
import { NodeOperationContextProvider } from "../NodeOperationContextProvider";
import type { AskAIResponse } from "./askAiClient";
import { askAiForNode } from "./askAiClient";
import { AskAISection } from "./AskAISection";

vi.mock("./askAiClient", () => ({
  askAiForNode: vi.fn(),
}));

function renderAskAISection(activeRunId: string) {
  const seed = makeOwnerResolutionSeedFixture();
  const selected = seed.forest.nodes.find(
    (node) => node.nodeKey === seed.sharedNodeKey,
  );
  if (!selected) throw new Error("missing selected node fixture");
  const selectedNode = selected;

  function tree(nextActiveRunId: string) {
    return (
      <ForestContext.Provider
        value={{
          forest: seed.forest,
          activeRunId: nextActiveRunId,
          setActiveRunId: vi.fn(),
        }}
      >
        <NodeOperationContextProvider node={selectedNode}>
          <AskAISection node={selectedNode} />
        </NodeOperationContextProvider>
      </ForestContext.Provider>
    );
  }

  const result = render(tree(activeRunId));
  return {
    ...result,
    rerenderWithActiveRunId(nextActiveRunId: string) {
      result.rerender(tree(nextActiveRunId));
    },
  };
}

function deferredAskAIResponse() {
  let resolve!: (value: AskAIResponse) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<AskAIResponse>((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

describe("AskAISection", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_WORKBENCH_ASK_AI", "1");
    vi.mocked(askAiForNode).mockReset();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("is hidden by default when the Ask AI feature flag is off", () => {
    vi.unstubAllEnvs();
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId);

    expect(screen.queryByTestId("ask-ai-section")).not.toBeInTheDocument();
    expect(vi.mocked(askAiForNode)).not.toHaveBeenCalled();
  });

  it("renders an enabled ask button and context preview JSON when context resolves", () => {
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId);

    expect(
      screen.getByRole("button", { name: "Ask AI about this node" }),
    ).toBeEnabled();
    const preview = screen.getByTestId("ask-ai-context-preview");
    const packet = JSON.parse(preview.textContent ?? "{}");
    expect(packet.packet_version).toBe("ask-ai-context/v1");
    expect(packet.packet_scope.scope_type).toBe("selected_node");
    expect(packet.context_visibility_notice.full_datasets_included).toBe(false);
  });

  it("ignores stale responses after context switches to resolver failure", async () => {
    const deferred = deferredAskAIResponse();
    vi.mocked(askAiForNode).mockReturnValueOnce(deferred.promise);
    const seed = makeOwnerResolutionSeedFixture();
    const { rerenderWithActiveRunId } = renderAskAISection(seed.activeHeadRunId);

    fireEvent.click(screen.getByRole("button", { name: "Ask AI about this node" }));
    expect(vi.mocked(askAiForNode)).toHaveBeenCalledTimes(1);

    rerenderWithActiveRunId("run_not_owner");
    expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent(
      "ambiguous_owner_run",
    );

    await act(async () => {
      deferred.resolve({ text: "stale answer from node A" });
      await deferred.promise;
    });

    expect(screen.queryByTestId("ask-ai-answer")).not.toBeInTheDocument();
    expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent(
      "ambiguous_owner_run",
    );
  });

  it("does not let an older response overwrite a newer answer after returning to the same context", async () => {
    const stale = deferredAskAIResponse();
    const fresh = deferredAskAIResponse();
    vi.mocked(askAiForNode)
      .mockReturnValueOnce(stale.promise)
      .mockReturnValueOnce(fresh.promise);
    const seed = makeOwnerResolutionSeedFixture();
    const { rerenderWithActiveRunId } = renderAskAISection(seed.activeHeadRunId);

    fireEvent.click(screen.getByRole("button", { name: "Ask AI about this node" }));
    expect(vi.mocked(askAiForNode)).toHaveBeenCalledTimes(1);

    rerenderWithActiveRunId("run_not_owner");
    expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent(
      "ambiguous_owner_run",
    );

    rerenderWithActiveRunId(seed.activeHeadRunId);
    fireEvent.click(screen.getByRole("button", { name: "Ask AI about this node" }));
    expect(vi.mocked(askAiForNode)).toHaveBeenCalledTimes(2);

    await act(async () => {
      fresh.resolve({ text: "fresh answer from node A" });
      await fresh.promise;
    });
    expect(screen.getByTestId("ask-ai-answer")).toHaveTextContent(
      "fresh answer from node A",
    );

    await act(async () => {
      stale.resolve({ text: "stale answer from node A" });
      await stale.promise;
    });

    expect(screen.getByTestId("ask-ai-answer")).toHaveTextContent(
      "fresh answer from node A",
    );
  });

  it("renders model JSON-looking response as text, not as an action", async () => {
    vi.mocked(askAiForNode).mockResolvedValueOnce({
      text: '{"operation":"rerun","owner_run_id":"run_a"}',
    });
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId);

    fireEvent.click(screen.getByRole("button", { name: "Ask AI about this node" }));

    const answer = await screen.findByTestId("ask-ai-answer");
    expect(answer).toHaveTextContent('{"operation":"rerun","owner_run_id":"run_a"}');
    expect(screen.queryByTestId("ask-ai-executable-action")).not.toBeInTheDocument();
  });

  it("shows resolver failure and omits packet preview when context cannot resolve", () => {
    renderAskAISection("run_not_owner");

    expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent(
      "ambiguous_owner_run",
    );
    expect(screen.queryByTestId("ask-ai-context-preview")).not.toBeInTheDocument();
  });

  it("does not call Ask AI when resolver fails", () => {
    renderAskAISection("run_not_owner");

    expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent(
      "ambiguous_owner_run",
    );
    expect(vi.mocked(askAiForNode)).not.toHaveBeenCalled();
  });

  it("shows service errors as text and keeps the context preview visible", async () => {
    vi.mocked(askAiForNode).mockRejectedValueOnce(new Error("Ask AI failed (501)"));
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId);

    fireEvent.click(screen.getByRole("button", { name: "Ask AI about this node" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Ask AI failed (501)");
    });
    expect(screen.getByTestId("ask-ai-context-preview")).toBeInTheDocument();
  });
});
