// Promoting an on-screen diff to a stored comparison node.
//
// The button must send only what the user pointed at, and when the backend
// refuses a pair it must show the reason rather than a generic failure — the
// refusal codes are the whole explanation of why a pair cannot be compared.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api", async () => {
  const actual = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...actual, createCompareNode: vi.fn() };
});

import { ApiError, createCompareNode } from "../../api";
import { ProjectRootProvider } from "../../workbench/ProjectRootContext";
import type { NodeOperationContextV1 } from "../api/nodeOperationContext";
import { KeepComparisonButton } from "./KeepComparisonButton";

function context(runId: string, nodeId: string): NodeOperationContextV1 {
  return {
    ownership: {
      owner_run_id: runId,
      candidate_run_refs: [{ run_id: runId, op_node_id: nodeId }],
    },
  } as unknown as NodeOperationContextV1;
}

const onKept = vi.fn();

function renderButton(
  left = context("run-a", "model:arma_garch_1"),
  right = context("run-b", "model:arma_garch_1"),
  projectRoot: string | null = "/p",
) {
  return render(
    <ProjectRootProvider projectRoot={projectRoot as string}>
      <KeepComparisonButton projectRoot={projectRoot} left={left} right={right} onKept={onKept} />
    </ProjectRootProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(createCompareNode).mockResolvedValue({ compare_id: "c1" } as never);
});

describe("KeepComparisonButton", () => {
  it("sends each side's owning run and node, and nothing else", async () => {
    renderButton();

    fireEvent.click(screen.getByTestId("keep-comparison"));

    await waitFor(() =>
      expect(createCompareNode).toHaveBeenCalledWith(
        "/p",
        { runId: "run-a", nodeId: "model:arma_garch_1" },
        { runId: "run-b", nodeId: "model:arma_garch_1" },
      ),
    );
    expect(onKept).toHaveBeenCalled();
  });

  it("shows the backend's refusal code so the user learns why", async () => {
    vi.mocked(createCompareNode).mockRejectedValue(
      new ApiError(422, "only available between two ARMA-GARCH runs", "COMPARE_UNSUPPORTED_PACK"),
    );

    renderButton();
    fireEvent.click(screen.getByTestId("keep-comparison"));

    const alert = await screen.findByTestId("keep-comparison-error");
    expect(alert).toHaveTextContent("COMPARE_UNSUPPORTED_PACK");
    expect(alert).toHaveTextContent("only available between two ARMA-GARCH runs");
    expect(onKept).not.toHaveBeenCalled();
  });

  it("does not offer to keep a comparison it cannot address", () => {
    const unowned = { ownership: { owner_run_id: "", candidate_run_refs: [] } } as unknown as
      NodeOperationContextV1;

    const { container } = renderButton(unowned);

    expect(container).toBeEmptyDOMElement();
  });

  it("hides rather than crashing when a context carries no candidate refs", () => {
    // Caught by the existing CompareNodesSection suite: a resolved context can
    // omit candidate_run_refs entirely, and reading through it took down the
    // whole drawer instead of just hiding one button.
    const bare = { ownership: { owner_run_id: "run-a" } } as unknown as NodeOperationContextV1;

    const { container } = renderButton(bare);

    expect(container).toBeEmptyDOMElement();
  });

  it("does not offer to keep one without a project", () => {
    const { container } = renderButton(undefined, undefined, null);

    expect(container).toBeEmptyDOMElement();
  });
});
