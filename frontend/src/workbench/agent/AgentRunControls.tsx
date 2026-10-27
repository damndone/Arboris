import { useEffect, useState } from "react";
import { useAgentSurfaceOptional } from "./AgentSurfaceContext";

export function agentTurnActive(agent: {isSubmitting:boolean;sessionStatus:string;confirmationBusyId?:string|null}) {
  return agent.isSubmitting || agent.confirmationBusyId != null || ["running","working","cancelling"].includes(agent.sessionStatus.toLowerCase());
}
export function AgentRunControls() {
  const agent = useAgentSurfaceOptional();
  const [delivery,setDelivery] = useState<""|"steer"|"follow_up">("");
  const active = agent ? agentTurnActive(agent) : false;
  useEffect(() => { setDelivery(""); }, [agent?.sessionId, active]);
  if (!agent?.setExecutionMode) return null;
  const turns = agent.durableTurns ?? [];
  return <div className="wb-agent-run-controls">
    <label>Mode <select aria-label="Agent execution mode" value={agent.executionMode ?? "ask"} disabled={active} onChange={e => agent.setExecutionMode?.(e.target.value as "ask"|"auto")}>
      <option value="ask">Ask every step</option><option value="auto">Auto within approved plan</option>
    </select></label>
    {active && agent.queueTurnMessage && !agent.prompt.trim().startsWith("/") && <>
      <select aria-label="Active-turn message delivery" value={delivery} onChange={e => setDelivery(e.target.value as typeof delivery)}>
        <option value="">Choose message delivery…</option><option value="steer">Steer current turn</option><option value="follow_up">Queue follow-up</option>
      </select>
      <button disabled={!delivery || !agent.prompt.trim() || agent.queueMessageBusy} onClick={() => {
        if (delivery) void agent.queueTurnMessage?.(delivery,agent.prompt);
      }}>Send active-turn message</button>
    </>}
    {!agent.isSubmitting && turns.map(turn => <div key={turn.turn_id}>
      <span>Unfinished turn: {turn.status}{turn.requires_reconcile ? " · reconciliation required" : ""}</span>
      <button onClick={() => void agent.resumeTurn?.(turn.turn_id)}>Resume original turn</button>
      <small>The server verifies whether the original owner is still running before recovery.</small>
    </div>)}
    {!agent.isSubmitting && turns.length > 0 && agent.sessionId && <small>Resuming starts a model request.</small>}
    {agent.queueMessageNotice && <span role="status">{agent.queueMessageNotice}</span>}
  </div>;
}
