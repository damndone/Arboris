import { describe, expect, it } from "vitest";
import { agentCapabilitiesFixture, agentProposalFixture, operationCapabilityFixture } from "../../apiFixtures";
import { groupPendingProposals } from "./proposalGroups";

const catalog = agentCapabilitiesFixture({ capabilities: [operationCapabilityFixture({ operation_id: "model.rerun" })] });
const proposal = (id: string) => agentProposalFixture({ proposal_id: id, operation_id: "model.rerun", command_id: "turn-1",
  record_type:"revision",operation_version:"v1",session_id:"s",chain_id:"c",revision:1,fingerprint:id,
  status:"pending",target:{},preconditions:{},changes:{},evidence_refs:[],expected_effect:[],risks:[],created_at:"2026-10-28T00:00:00Z" });

describe("groupPendingProposals", () => {
  it("joins only adjacent same-turn reruns with an ordinary registered risk", () => {
    const a = proposal("a"), b = proposal("b"), c = { ...proposal("c"), command_id: "turn-2" };
    expect(groupPendingProposals([a, b, c], catalog).map(group => group.map(p => p.proposal_id))).toEqual([["a", "b"], ["c"]]);
    expect(groupPendingProposals([a, c, b], catalog)).toHaveLength(3);
  });
  it("keeps missing declarations, high risk, extra authorization and unknown kinds separate", () => {
    const pair = [proposal("a"), proposal("b")];
    expect(groupPendingProposals(pair, null)).toHaveLength(2);
    for (const capability of [
      operationCapabilityFixture({ operation_id: "model.rerun", risk_level: "high" }),
      operationCapabilityFixture({ operation_id: "model.rerun", risk_authorization_policy: "required" }),
    ]) expect(groupPendingProposals(pair, agentCapabilitiesFixture({ capabilities: [capability] }))).toHaveLength(2);
    for (const operation_id of ["data.column.cast", "metadata.edit", "data.export", "code.execute", "operation.multi_step", "unknown"])
      expect(groupPendingProposals(pair.map(p => ({ ...p, operation_id })), catalog)).toHaveLength(2);
    expect(groupPendingProposals(pair.map(p => ({ ...p, command_id: null })), catalog)).toHaveLength(2);
  });
});
