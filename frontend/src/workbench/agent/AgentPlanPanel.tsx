import { useEffect, useRef, useState } from "react";
import { useAgentSurfaceOptional } from "./AgentSurfaceContext";
import type { AgentPlan, AgentPlanPatch, AgentPlanRequirement } from "./agentTypes";

function slotText(plan: AgentPlan, slot: AgentPlanRequirement["covers"][number]) {
  return "criterion_index" in slot ? plan.criteria[slot.criterion_index]
    : plan.steps.find(step => step.step_id === slot.step_id)?.expected_outputs[slot.output_index];
}

/** This plan authorizes workflow scope; it is not statistical preregistration. */
export function AgentPlanPanel() {
  const agent = useAgentSurfaceOptional();
  const [draft, setDraft] = useState<AgentPlanPatch | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const summaryRef = useRef<HTMLElement>(null);
  const plan = agent?.plan;
  useEffect(() => { setDraft(null); setFailure(null); }, [agent?.sessionId]);
  useEffect(() => {
    if (!agent?.planViewRequest) return;
    setOpen(true);
    summaryRef.current?.focus();
    summaryRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [agent?.planViewRequest]);
  if (!agent) return null;
  if (!plan) return agent.planError ? <section className="wb-agent-plan" aria-label="Analysis plan"><p role="alert">{agent.planError}</p><button onClick={() => void agent.refreshPlan?.()}>Reload current plan</button></section> : null;
  const busy = agent.planBusy || agent.isSubmitting || agent.sessionStatus === "running";
  const changed = draft !== null && draft.version !== plan.version;
  const awaitingApproval = plan.approved_version !== plan.version && ["draft","needs_approval"].includes(plan.status);
  const approve = () => {setFailure(null);void agent.approvePlan?.(plan.version).catch(error => setFailure(error instanceof Error ? error.message : "Could not approve plan."));};
  const verifiedDone = new Set(plan.steps.filter(step => ["done", "completed"].includes(step.status)
    && step.operation_ids.every(operation => step.completed_operation_ids?.includes(operation))).map(step => step.step_id));
  const verification = agent.planVerification?.plan_id === plan.plan_id && agent.planVerification.plan_version === plan.version
    ? agent.planVerification : null;
  // v1.9.1: one line until opened, so the conversation keeps the panel.
  return <details className="wb-agent-plan" aria-label="Analysis plan" open={open || draft !== null || undefined}
    onToggle={event => setOpen((event.currentTarget as HTMLDetailsElement).open)}>
    <summary ref={summaryRef} tabIndex={0}>
      <span className="wb-agent-plan__title">Plan v{plan.version}</span>
      <span className="wb-agent-plan__meta">{plan.status} · Execution: {verifiedDone.size}/{plan.steps.length} completed {plan.steps.length === 1 ? "step" : "steps"}</span>
      {!draft && awaitingApproval && <button type="button" className="wb-agent-plan__approve" disabled={busy}
        onClick={event => {event.preventDefault();approve();}}>Approve plan v{plan.version}</button>}
    </summary>
    <p className="wb-agent-plan__note">Approval authorizes this plan version. It does not establish statistical preregistration.</p>
    {draft ? <>
      <label>Question<textarea aria-label="Plan question" maxLength={1000} value={draft.question ?? ""} onChange={e => setDraft({...draft,question:e.target.value})}/></label>
      <label>Criteria (one per line)<textarea aria-label="Plan criteria" value={(draft.criteria ?? []).join("\n")} onChange={e => setDraft({...draft,criteria:e.target.value.split("\n")})}/></label>
    </> : <><p>{plan.question}</p><ul>{plan.criteria.map((criterion, i) => <li key={i}>{criterion}</li>)}</ul></>}
    {Boolean(plan.completion?.requirements?.length) && <section aria-label="Fixed deliverable definitions">
      <strong>Machine-checkable definitions</strong>
      <p className="wb-agent-plan__note">Approval fixes these exact requests as the operational meaning of the covered criteria.</p>
      <ul>{plan.completion?.requirements?.map(requirement => <li key={requirement.id}>
        <strong>{requirement.id}</strong>{" · "}{requirement.operation.operation_id}
        <ul>{requirement.covers.map((slot, index) => <li key={index}>{slotText(plan, slot)}</li>)}</ul>
        <details><summary>Exact specification · {requirement.operation.step_id}</summary>
          <pre className="wb-agent-plan__spec">{JSON.stringify(requirement.operation.spec, null, 2)}</pre>
        </details>
        {requirement.allow_not_applicable && <small>A producer-verified “not applicable” outcome is permitted.</small>}
      </li>)}</ul>
    </section>}
    <ol>{plan.steps.map(step => <li key={step.step_id} data-status={["done", "completed"].includes(step.status) && !verifiedDone.has(step.step_id) ? "unverified" : step.status}>
      <span className="wb-agent-plan__dot" aria-hidden="true" />
      <div className="wb-agent-plan__step">
        {draft ? <input aria-label={`Step ${step.step_id} title`} maxLength={200} value={draft.steps?.find(s => s.step_id === step.step_id)?.title ?? step.title}
          onChange={e => setDraft({...draft,steps:draft.steps?.map(s => s.step_id === step.step_id ? {...s,title:e.target.value} : s)})}/> : <strong>{step.title}</strong>}
        <div className="wb-agent-plan__detail">
          <span className="wb-agent-plan__status">{step.status}</span>
          {step.depends_on.length > 0 && <> · after {step.depends_on.join(", ")}</>}
          {" · "}{step.operation_ids.join(", ")}
          {step.added_after_results && <> · later plan change</>}
        </div>
        {["done", "completed"].includes(step.status) && !verifiedDone.has(step.step_id) && <p role="note">
          Recorded as done; execution evidence is unavailable. Inspect the original operations before continuing.
        </p>}
        {Boolean(step.completed_operation_ids?.length) && <div className="wb-agent-plan__detail">
          Recorded operations: {step.operation_ids.filter(operation => step.completed_operation_ids?.includes(operation)).length}/{step.operation_ids.length}
        </div>}
        {step.expected_outputs.length > 0 && <div className="wb-agent-plan__detail">Expected: {step.expected_outputs.join(", ")}</div>}
      </div>
    </li>)}</ol>
    <section className="wb-agent-plan__verification" aria-label="Deliverable verification">
      <div className="wb-agent-plan__actions"><strong>Deliverable verification</strong>
        <button type="button" disabled={agent.planBusy || agent.planVerificationBusy}
          onClick={() => void agent.verifyPlan?.()}>{agent.planVerificationBusy ? "Checking…" : "Check deliverables"}</button>
      </div>
      <p className="wb-agent-plan__note">Execution counts use operation receipts. Deliverables can reuse registered artifacts. Results reflect the last check; recheck after operations change. This does not call a model.</p>
      {agent.planVerificationError && <p role="alert">{agent.planVerificationError}</p>}
      {verification ? <>
        <p role="status">{verification.status === "requirements_met" ? "Delivery requirements met" : "Partial completion"}
          {" · "}Playbook: {verification.playbook_status}</p>
        <ul>{verification.criteria_verification.requirements.map(requirement => <li key={requirement.id}>
          <strong>{requirement.id} · {requirement.status}</strong>
          <p>{requirement.reason}</p>
          {requirement.verified_artifacts.length > 0 && <small>{requirement.verified_artifacts.length} registered artifact{requirement.verified_artifacts.length === 1 ? "" : "s"}</small>}
        </li>)}
          {verification.criteria_verification.unbound_slots.map((slot, index) => <li key={`unbound-${index}`}>
            Not bound: {slotText(plan, slot)}
          </li>)}
        </ul>
      </> : !agent.planVerificationError && <p className="wb-agent-plan__note" role="status">Not checked for this plan version.</p>}
    </section>
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
  </details>;
}
