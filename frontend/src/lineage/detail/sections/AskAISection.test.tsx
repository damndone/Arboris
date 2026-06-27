import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ForestContext } from "../../../workbench/ForestContext";
import { makeOwnerResolutionSeedFixture } from "../../api/nodeOperationContext";
import { NodeOperationContextProvider } from "../NodeOperationContextProvider";
import { AskAISection } from "./AskAISection";

function renderAskAISection(activeRunId: string) {
  const seed = makeOwnerResolutionSeedFixture();
  const selected = seed.forest.nodes.find(
    (node) => node.nodeKey === seed.sharedNodeKey,
  );
  if (!selected) throw new Error("missing selected node fixture");

  render(
    <ForestContext.Provider
      value={{
        forest: seed.forest,
        activeRunId,
        setActiveRunId: vi.fn(),
      }}
    >
      <NodeOperationContextProvider node={selected}>
        <AskAISection node={selected} />
      </NodeOperationContextProvider>
    </ForestContext.Provider>,
  );
}

describe("AskAISection", () => {
  it("renders a disabled ask button and context preview JSON when context resolves", () => {
    const seed = makeOwnerResolutionSeedFixture();
    renderAskAISection(seed.activeHeadRunId);

    expect(
      screen.getByRole("button", { name: "Ask AI about this node" }),
    ).toBeDisabled();
    const preview = screen.getByTestId("ask-ai-context-preview");
    const packet = JSON.parse(preview.textContent ?? "{}");
    expect(packet.packet_version).toBe("ask-ai-context/v1");
    expect(packet.packet_scope.scope_type).toBe("selected_node");
    expect(packet.context_visibility_notice.full_datasets_included).toBe(false);
  });

  it("shows resolver failure and omits packet preview when context cannot resolve", () => {
    renderAskAISection("run_not_owner");

    expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent(
      "ambiguous_owner_run",
    );
    expect(screen.queryByTestId("ask-ai-context-preview")).not.toBeInTheDocument();
  });
});
