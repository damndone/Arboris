import { useEffect, useState } from "react";
import { useAgentSurfaceOptional } from "./AgentSurfaceContext";
import type { AgentPlanPatch } from "./agentTypes";

/** This plan authorizes workflow scope; it is not statistical preregistration. */
export function AgentPlanPanel() {
  const agent = useAgentSurfaceOptional();
  const [draft, setDraft] = useState<AgentPlanPatch | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const plan = agent?.plan;
  useEffect(() => { setDraft(null); setFailure(null); }, [agent?.sessionId]);
  if (!agent) return null;
  if (!plan) return agent.planError ? <section className="wb-agent-plan" aria-label="Analysis plan"><p role="alert">{agent.planError}</p><button onClick={() => void agent.refreshPlan?.()}>Reload current plan</button></section> : null;
  const busy = agent.planBusy || agent.isSubmitting || agent.sessionStatus === "running";
  const changed = draft !== null && draft.version !== plan.version;
  return <section className="wb-agent-plan" aria-label="Analysis plan">
    <header><strong>Analysis plan · v{plan.version}</strong><span>{plan.status}</span></header>
    <p className="wb-agent-plan__note">Approval authorizes this plan version. It does not establish statistical preregistration.</p>
    {draft ? <>
      <label>Question<textarea aria-label="Plan question" maxLength={1000} value={draft.question ?? ""} onChange={e => setDraft({...draft,question:e.target.value})}/></label>
      <label>Criteria (one per line)<textarea aria-label="Plan criteria" value={(draft.criteria ?? []).join("\n")} onChange={e => setDraft({...draft,criteria:e.target.value.split("\n")})}/></label>
    </> : <><p>{plan.question}</p><ul>{plan.criteria.map((criterion, i) => <li key={i}>{criterion}</li>)}</ul></>}
    <ol>{plan.steps.map(step => <li key={step.step_id}>
      <div><code>{step.step_id}</code> · <span className="wb-agent-plan__status">{step.status}</span></div>
      {draft ? <input aria-label={`Step ${step.step_id} title`} maxLength={200} value={draft.steps?.find(s => s.step_id === step.step_id)?.title ?? step.title}
        onChange={e => setDraft({...draft,steps:draft.steps?.map(s => s.step_id === step.step_id ? {...s,title:e.target.value} : s)})}/> : <strong>{step.title}</strong>}
      <div>Depends on: {step.depends_on.length ? step.depends_on.join(", ") : "none"}</div>
      <div>{step.operation_ids.join(", ")}</div>
      {step.expected_outputs.length > 0 && <div>Expected: {step.expected_outputs.join(", ")}</div>}
      {step.added_after_results && <small>Later plan change</small>}
    </li>)}</ol>
    {changed && <p role="status">A newer plan is available. Your draft is kept; discard it to edit the current version.</p>}
    {(failure || agent.planError) && <p role="alert">{failure ?? agent.planError}{draft ? " Your draft is kept." : ""} Reload the current plan to review changes.</p>}
    <div className="wb-agent-plan__actions">
      {draft ? <>
        <button disabled={busy || changed} onClick={() => {
          setFailure(null);
          const submittedDraft = draft;
          void agent.savePlan?.({...submittedDraft,criteria:submittedDraft.criteria?.filter(criterion => criterion.trim())})
            .then(() => setDraft(current => current === submittedDraft ? null : current))
            .catch(error => setFailure(error instanceof Error ? error.message : "Could not save plan."));
        }}>Save plan</button>
        <button disabled={busy} onClick={() => {setDraft(null);setFailure(null);}}>Discard draft</button>
      </> : <>
        <button disabled={busy} onClick={() => setDraft({version:plan.version,question:plan.question,criteria:[...plan.criteria],steps:plan.steps.map(s => ({step_id:s.step_id,title:s.title,operation_ids:[...s.operation_ids],depends_on:[...s.depends_on],expected_outputs:[...s.expected_outputs]}))})}>Edit plan</button>
        {plan.approved_version !== plan.version && ["draft","needs_approval"].includes(plan.status) && <button disabled={busy} onClick={() => {setFailure(null);void agent.approvePlan?.(plan.version).catch(error => setFailure(error instanceof Error ? error.message : "Could not approve plan."));}}>Approve plan v{plan.version}</button>}
        {agent.executionMode === "auto" && agent.approveAndRunPlan && plan.approved_version !== plan.version && ["draft","needs_approval"].includes(plan.status) && <>
          <button disabled={busy || Boolean(agent.durableTurns?.length)} onClick={() => {
            setFailure(null);
            void agent.approveAndRunPlan?.(plan.version).catch(error => setFailure(error instanceof Error ? error.message : "Could not approve and run plan."));
          }}>Approve and run plan v{plan.version}</button>
          <small>Approve and run starts a model request.</small>
        </>}
      </>}
      <button disabled={agent.planBusy} onClick={() => void agent.refreshPlan?.()}>Reload current plan</button>
    </div>
    {agent.planVersions && agent.planVersions.length > 1 && <details><summary>Plan versions</summary><ul>{agent.planVersions.map(v => <li key={v.version}>v{v.version} · {v.status} · {v.updated_at}</li>)}</ul></details>}
  </section>;
}
