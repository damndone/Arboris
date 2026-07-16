import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AgentHierarchyNode } from "./agentTypes";
import { AgentHierarchyTree } from "./AgentHierarchyTree";

function ref(
  kind: AgentHierarchyNode["ref"]["kind"],
  id: string,
  label: string,
  relation: AgentHierarchyNode["ref"]["relation"],
): AgentHierarchyNode["ref"] {
  return {
    kind,
    id,
    label,
    relation,
    available: true,
    href: { view: "agent", session_id: id },
  };
}

describe("AgentHierarchyTree", () => {
  it("renders Main to Chain to child operation hierarchy and uses typed navigation", () => {
    const openNavigation = vi.fn(() => true);
    const operationRef = ref(
      "operation",
      "oprec-1",
      "model.rerun · completed",
      "audit",
    );
    const root: AgentHierarchyNode = {
      ref: ref("agent_session", "main-session", "Main Agent", "context"),
      status: "idle",
      children: [{
        ref: ref("chain", "chain-a", "Chain chain-a", "child"),
        status: "idle",
        children: [{
          ref: ref("agent_session", "chain-session", "Agent chain-session", "child"),
          status: "idle",
          children: [{
            ref: operationRef,
            status: "completed",
            children: [],
          }],
        }],
      }],
    };

    render(<AgentHierarchyTree root={root} openNavigation={openNavigation} />);

    expect(screen.getByRole("tree", { name: "Main and Chain hierarchy" })).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: /Main Agent/ })).toBeInTheDocument();
    expect(screen.getByRole("treeitem", { name: /Chain chain-a/ })).toBeInTheDocument();
    const operation = screen.getByRole("button", { name: /model\.rerun · completed/ });
    fireEvent.click(operation);
    expect(openNavigation).toHaveBeenCalledWith(operationRef);
  });
});
