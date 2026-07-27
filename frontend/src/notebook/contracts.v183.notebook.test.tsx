import { describe, expect, it } from "vitest";

import { parseNotebookOptionRevision } from "./contracts";

function v12Packet(): Record<string, unknown> {
  return {
    contract_version: "1.2",
    option_id: "opt_capability",
    option_revision: 1,
    notebook_id: "notebook_capability",
    run_family_id: "family_capability",
    generation_context_id: "context_capability",
    generation_context_hash: "context-hash",
    freshness_dependency_fingerprint: "freshness-hash",
    typed_proposal_id: "proposal_capability",
    typed_proposal_revision: 1,
    artifact_contract: {
      contract_version: "1.0",
      expected: [],
      checked_dimensions: ["artifact_id"],
      not_evaluated_dimensions: ["payload_schema"],
    },
    rationale: "server-owned capability option",
    assumptions: [],
    risk_level: "low",
    lifecycle_status: "proposed",
    freshness_status: "fresh",
    validation_status: "valid",
    rank: 1,
    batch_id: "batch_capability",
    created_at: "2026-07-27T00:00:00Z",
    supersedes_option_revision: null,
    evidence_refs: [],
    comparative_claims: [],
    recommendation_decision_id: "decision_capability",
    recommendation_status: "recommended",
    capability_resolution_binding_ref: "a".repeat(64),
    execution_modes: ["materialize_only", "confirm_and_execute"],
  };
}

describe("v1.8.3 NotebookOptionRevision@1.2", () => {
  it("preserves the server binding and explicit execution modes", () => {
    const option = parseNotebookOptionRevision(v12Packet());

    expect(option.contract_version).toBe("1.2");
    expect(option.capability_resolution_binding_ref).toBe("a".repeat(64));
    expect(option.execution_modes).toEqual(["materialize_only", "confirm_and_execute"]);
    expect(option.confirmAndExecute).toBe(true);
  });

  it("rejects an unbound packet that claims confirm_and_execute", () => {
    const packet = v12Packet();
    delete packet.capability_resolution_binding_ref;

    expect(() => parseNotebookOptionRevision(packet)).toThrow(
      "capability_resolution_binding_ref",
    );
  });
});
