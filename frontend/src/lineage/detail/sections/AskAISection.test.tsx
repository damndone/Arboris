import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ForestContext } from "../../../workbench/ForestContext";
import { ProjectRootProvider } from "../../../workbench/ProjectRootContext";
import { makeOwnerResolutionSeedFixture } from "../../api/nodeOperationContext";
import { fetchAnalysisLoopPackets, type AnalysisLoopPacketsResponse } from "../../api/analysisLoop";
import { NodeOperationContextProvider } from "../NodeOperationContextProvider";
import type { AskAIResponse } from "./askAiClient";
import { askAiForNode, fetchLlmConfig } from "./askAiClient";
import { AskAISection } from "./AskAISection";

vi.mock("./askAiClient", () => ({
  askAiForNode: vi.fn(),
  fetchLlmConfig: vi.fn().mockResolvedValue({
    configured: true,
    base_url: "https://llm.example.com",
    model: "deepseek-v4-flash",
    key_present: true,
    context_window_tokens: 1_000_000,
    supports_1m: true,
  }),
}));

vi.mock("../../api/analysisLoop", () => ({
  fetchAnalysisLoopPackets: vi.fn(),
}));

function renderAskAISection(
  activeRunId: string,
  mutateNode?: (node: ReturnType<typeof makeOwnerResolutionSeedFixture>["forest"]["nodes"][number]) => void,
) {
  const seed = makeOwnerResolutionSeedFixture();
  const selected = seed.forest.nodes.find(
    (node) => node.nodeKey === seed.sharedNodeKey,
  );
  if (!selected) throw new Error("missing selected node fixture");
  const selectedNode = selected;
  mutateNode?.(selectedNode);

  function tree(nextActiveRunId: string) {
    return (
      <ForestContext.Provider
        value={{
          forest: seed.forest,
          activeRunId: nextActiveRunId,
          setActiveRunId: vi.fn(),
        }}
      >
        <ProjectRootProvider projectRoot="/p">
          <NodeOperationContextProvider node={selectedNode}>
            <AskAISection node={selectedNode} />
          </NodeOperationContextProvider>
        </ProjectRootProvider>
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
    vi.mocked(fetchAnalysisLoopPackets).mockReset();
    vi.mocked(fetchLlmConfig).mockClear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("is visible by default when no opt-out flag is configured", () => {
    vi.unstubAllEnvs();
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId);

    expect(screen.getByTestId("ask-ai-section")).toBeInTheDocument();
  });

  it("can be explicitly disabled for deployments without Ask AI", () => {
    vi.stubEnv("VITE_WORKBENCH_ASK_AI", "0");
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId);

    expect(screen.queryByTestId("ask-ai-section")).not.toBeInTheDocument();
  });

  it("renders the context summary beside the preview when context resolves", async () => {
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

    const summary = screen.getByTestId("llm-context-summary");
    expect(summary).not.toHaveAttribute("open");
    expect(summary).toHaveTextContent("Packet version: ask-ai-context/v1");
    expect(summary).toHaveTextContent("Preview budget: 8,000 characters");
    await waitFor(() => {
      expect(summary).toHaveTextContent("Model context capacity: 1,000,000 tokens");
      expect(summary).toHaveTextContent("Supports 1M: Yes");
    });
  });

  it("shows elapsed time while an Ask AI request is still pending", async () => {
    vi.useFakeTimers();
    const deferred = deferredAskAIResponse();
    vi.mocked(askAiForNode).mockReturnValueOnce(deferred.promise);
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId);

    fireEvent.click(screen.getByRole("button", { name: "Ask AI about this node" }));
    expect(screen.getByTestId("ask-ai-elapsed")).toHaveTextContent("Working · 0s");

    await act(async () => {
      vi.advanceTimersByTime(3_000);
    });
    expect(screen.getByTestId("ask-ai-elapsed")).toHaveTextContent("Working · 3s");

    await act(async () => {
      deferred.resolve({ text: "completed" });
      await deferred.promise;
    });
    expect(screen.queryByTestId("ask-ai-elapsed")).toBeNull();
    vi.useRealTimers();
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

  it("adds backend-owned source and compare facts to a rerun child packet", async () => {
    const seed = makeOwnerResolutionSeedFixture();
    vi.mocked(fetchAnalysisLoopPackets).mockResolvedValueOnce({
      status: "complete",
      run: {
        run_id: "run_c",
        status: "completed",
        model: "ols",
        contract_version: "ols_result/v1",
        covariance: "clustered",
        covariance_product: "clustered",
        covariance_wire: "clustered",
        entity_col: "company_id",
        stable_result_ids: ["coef:treatment"],
        primary_estimand: { result_id: "coef:treatment", estimate: 0.41 },
        analysis_sample: { row_count: 428, row_order: [] },
        fingerprints: {},
      },
      source_run: {
        run_id: "run_a",
        status: "completed",
        model: "ols",
        contract_version: "ols_result/v1",
        covariance: "unadjusted",
        covariance_product: "conventional",
        covariance_wire: "unadjusted",
        entity_col: null,
        stable_result_ids: ["coef:treatment"],
        primary_estimand: { result_id: "coef:treatment", estimate: 0.42 },
        analysis_sample: { row_count: 428, row_order: [] },
        fingerprints: {},
      },
      packet: {
        child_run_id: "run_c",
        source_run_id: "run_a",
        plan_diff: { plan_hash: "plan:ols-clustered" },
        validation_packet: { status: "complete", overall_status: "passed" },
        compare_packet: {
          compare_status: "complete",
          result_diff: { estimate: { before: 0.42, after: 0.41 } },
          conclusion_diff: { classification: "UNCERTAINTY_INCREASED" },
        },
      },
      children: [],
    } satisfies AnalysisLoopPacketsResponse);
    renderAskAISection(seed.activeHeadRunId, (node) => {
      node.runRerunFrom = {
        owner_run_id: "run_a",
        op_node_id: seed.sharedOpNodeId,
        node_hash: seed.sharedNodeKey,
        context_fingerprint: "ctx:run-c",
        rerun_request_id: "req:run-c",
      };

    });

    expect(
      screen.getByRole("button", { name: "Ask AI about this node" }),
    ).toBeDisabled();

    await waitFor(() => {
      expect(fetchAnalysisLoopPackets).toHaveBeenCalledWith("/p", "run_c");
    });
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Ask AI about this node" }),
      ).toBeEnabled();
    });
    vi.mocked(askAiForNode).mockResolvedValueOnce({ text: "grounded" });
    fireEvent.click(screen.getByRole("button", { name: "Ask AI about this node" }));

    await waitFor(() => expect(askAiForNode).toHaveBeenCalledTimes(1));
    const packet = vi.mocked(askAiForNode).mock.calls[0][0] as Record<string, any>;
    expect(packet.analysis_loop.source_run.primary_estimand.estimate).toBe(0.42);
    expect(packet.analysis_loop.run.primary_estimand.estimate).toBe(0.41);
    expect(packet.analysis_loop.packet.compare_packet.result_diff).toEqual({
      estimate: { before: 0.42, after: 0.41 },
    });
    expect(packet.node_summary.params).not.toEqual({ covariance: "clustered" });
  });

  it("shows resolver failure and omits packet preview when context cannot resolve", async () => {
    renderAskAISection("run_not_owner");

    expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent(
      "ambiguous_owner_run",
    );
    expect(screen.queryByTestId("ask-ai-context-preview")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("llm-provider-badge")).toHaveTextContent(
        "deepseek-v4-flash",
      );
    });
  });

  it("does not call Ask AI when resolver fails", async () => {
    renderAskAISection("run_not_owner");

    expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent(
      "ambiguous_owner_run",
    );
    expect(vi.mocked(askAiForNode)).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.getByTestId("llm-provider-badge")).toHaveTextContent(
        "deepseek-v4-flash",
      );
    });
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

  it("renders per-artifact Explain buttons that fire a focused question (A3)", async () => {
    vi.mocked(askAiForNode).mockResolvedValueOnce({ text: "profile explained" });
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId, (node) => {
      node.artifacts = [{ name: "data_profile.json" }] as never;
    });

    fireEvent.click(screen.getByTestId("ask-ai-explain-data_profile.json"));

    await waitFor(() => {
      expect(screen.getByTestId("ask-ai-answer")).toHaveTextContent(
        "profile explained",
      );
    });
    const calls = vi.mocked(askAiForNode).mock.calls;
    expect(calls[calls.length - 1][1]).toContain('"data_profile.json"');
  });

  it("collapses long artifact lists into a categorized summary", () => {
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId, (node) => {
      node.artifacts = [
        { name: "data_profile.json", mime: "application/json" },
        { name: "statistical_exploration_summary.json", mime: "application/json" },
        { name: "statistical_exploration_corr.xlsx", mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" },
        { name: "workflow_report.pdf", mime: "application/pdf" },
      ] as never;
    });

    expect(screen.getByTestId("ask-ai-artifact-count")).toHaveTextContent("4 total");
    expect(screen.getByTestId("ask-ai-artifact-category-data")).toHaveTextContent("1 data");
    expect(screen.getByTestId("ask-ai-artifact-category-tables")).toHaveTextContent("1 table");
    expect(screen.getByTestId("ask-ai-artifact-category-analysis")).toHaveTextContent("2 analysis");
    expect(screen.getByTestId("ask-ai-explain-data_profile.json")).toBeInTheDocument();
    expect(screen.queryByTestId("ask-ai-explain-statistical_exploration_summary.json")).not.toBeInTheDocument();

    const toggle = screen.getByTestId("ask-ai-artifacts-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("ask-ai-explain-statistical_exploration_summary.json")).toBeInTheDocument();
    expect(screen.getByTestId("ask-ai-explain-statistical_exploration_corr.xlsx")).toBeInTheDocument();
    expect(screen.getByTestId("ask-ai-explain-workflow_report.pdf")).toBeInTheDocument();
  });

  it("shows the read-only LLM provider badge with the configured model (A4)", async () => {
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId);
    await waitFor(() => {
      expect(screen.getByTestId("llm-provider-badge")).toHaveTextContent(
        "deepseek-v4-flash",
      );
    });
    // read-only surface: no input to change the key, key never displayed
    expect(screen.getByTestId("llm-provider-badge").textContent).not.toContain("sk-");
  });

  it("fetches LLM config once when packet visibility rerenders", async () => {
    const seed = makeOwnerResolutionSeedFixture();
    const { rerenderWithActiveRunId } = renderAskAISection(seed.activeHeadRunId);

    rerenderWithActiveRunId("run_not_owner");
    rerenderWithActiveRunId(seed.activeHeadRunId);

    await waitFor(() => {
      expect(screen.getByTestId("llm-provider-badge")).toHaveTextContent(
        "deepseek-v4-flash",
      );
    });
    expect(vi.mocked(fetchLlmConfig)).toHaveBeenCalledTimes(1);
  });
});
