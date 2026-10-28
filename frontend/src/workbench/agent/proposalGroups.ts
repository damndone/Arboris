import type { AgentCapabilityCatalog, AgentProposal } from "./agentTypes";

/** Presentation only. Every selected revision still needs its own server confirmation. */
export function groupPendingProposals(proposals: AgentProposal[], catalog?: AgentCapabilityCatalog | null): AgentProposal[][] {
  const groups: AgentProposal[][] = [];
  for (const proposal of proposals) {
    const capability = catalog?.capabilities.find(item => item.operation_id === proposal.operation_id
      && item.operation_version === proposal.operation_version);
    // Only ordinary reruns are covered by this first grouping contract. Unknown
    // declarations and operations with per-use authorization stay separate.
    const eligible = proposal.status === "pending" && proposal.operation_id === "model.rerun"
      && Boolean(proposal.command_id) && capability?.risk_authorization_policy === "none"
      && ["read_only", "mutating"].includes(capability.risk_level);
    const previousGroup = groups[groups.length - 1];
    const previous = previousGroup?.[previousGroup.length - 1];
    if (eligible && previous?.status === "pending" && previous.command_id === proposal.command_id
        && previous.session_id === proposal.session_id && previous.chain_id === proposal.chain_id
        && previous.operation_id === proposal.operation_id && previous.operation_version === proposal.operation_version) {
      groups[groups.length - 1].push(proposal);
    } else groups.push([proposal]);
  }
  return groups;
}
