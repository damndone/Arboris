import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { AgentPlanPanel } from "./AgentPlanPanel";
import { AgentRunControls } from "./AgentRunControls";
const state = vi.hoisted(() => ({ agent: {} as Record<string, any> }));
vi.mock("./AgentSurfaceContext", () => ({ useAgentSurfaceOptional: () => state.agent }));
const plan = () => ({ plan_id:"p1",version:3,status:"draft",question:"Compare groups",criteria:["Report uncertainty"],steps:[
  {step_id:"a",title:"Inspect",status:"done",operation_ids:["stat.describe"],depends_on:[],expected_outputs:["summary"]},
  {step_id:"b",title:"Compare",status:"pending",operation_ids:["stat.test"],depends_on:["a"],expected_outputs:[]}],approved_version:null });
beforeEach(() => { state.agent = {plan:plan(),planVersions:[{version:3,status:"draft",updated_at:"today"}],planBusy:false,planError:null,
  approvePlan:vi.fn().mockResolvedValue(undefined),savePlan:vi.fn().mockResolvedValue(undefined),refreshPlan:vi.fn().mockResolvedValue(undefined),
  executionMode:"ask",setExecutionMode:vi.fn(),isSubmitting:false,sessionStatus:"idle",prompt:"new direction",queueTurnMessage:vi.fn().mockResolvedValue(undefined),sendPrompt:vi.fn(),continueTurn:vi.fn(),durableTurns:[]}; });
it("keeps an old done label but does not count missing execution evidence as complete", () => {
  render(<AgentPlanPanel />);
  expect(screen.getByText(/0\/2 completed steps/)).toBeInTheDocument();
  expect(screen.getByText("done")).toBeInTheDocument();
  expect(screen.getByText(/execution evidence is unavailable/i)).toBeInTheDocument();
});
it("counts completion only when every declared operation has a server receipt", () => {
  state.agent.plan = {...plan(), steps: [
    {...plan().steps[0], completed_operation_ids: ["stat.describe"]}, plan().steps[1]]};
  render(<AgentPlanPanel />);
  expect(screen.getByText(/1\/2 completed steps/)).toBeInTheDocument();
  expect(screen.queryByText(/execution evidence is unavailable/i)).not.toBeInTheDocument();
});
it("shows partial execution coverage without completing the step", () => {
  state.agent.plan = {...plan(), steps: [
    {...plan().steps[0], status: "pending", operation_ids: ["stat.describe", "stat.test"],
      completed_operation_ids: ["stat.describe"]}, plan().steps[1]]};
  render(<AgentPlanPanel />);
  expect(screen.getByText(/0\/2 completed steps/)).toBeInTheDocument();
  expect(screen.getByText("Recorded operations: 1/2")).toBeInTheDocument();
});
it("keeps verified deliverables separate from failed or missing execution receipts", () => {
  state.agent.planVerification = {plan_id:"p1",plan_version:3,status:"partial",playbook_status:"requirements_met",
    criteria_verification:{plan_id:"p1",plan_version:3,basis_sha256:"a".repeat(64),status:"partial",
      requirements:[{id:"covariance",status:"verified",reason:"Registered alternate fit matches the approved request.",
        verified_artifacts:[{run_id:"run-a",artifact_id:"model-a"}]}],unbound_slots:[{criterion_index:0}]}};
  render(<AgentPlanPanel />);
  expect(screen.getByText(/0\/2 completed steps/)).toBeInTheDocument();
  expect(screen.getByRole("region",{name:"Deliverable verification"})).toHaveTextContent("Partial completion");
  expect(screen.getByText(/covariance · verified/)).toBeInTheDocument();
  expect(screen.getByText(/Not bound: Report uncertainty/)).toBeInTheDocument();
  expect(screen.getByText(/1 registered artifact/)).toBeInTheDocument();
});
it("checks deliverables only on request and reports local verification failure", () => {
  state.agent.verifyPlan = vi.fn().mockResolvedValue(undefined);
  const view = render(<AgentPlanPanel />);
  expect(state.agent.verifyPlan).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"Check deliverables"}));
  expect(state.agent.verifyPlan).toHaveBeenCalledTimes(1);
  state.agent.planVerificationError = "Registered evidence could not be read.";
  view.rerender(<AgentPlanPanel />);
  expect(screen.getByRole("alert")).toHaveTextContent("Registered evidence could not be read.");
  expect(state.agent.sendPrompt).not.toHaveBeenCalled();
});
it("shows the exact scientific specification before approving its machine meaning", () => {
  state.agent.plan = {...plan(),completion:{requirements:[{id:"alternate_covariance",
    covers:[{criterion_index:0},{step_id:"a",output_index:0}],allow_not_applicable:true,
    operation:{step_id:"fit",operation_id:"model.genesis",spec:{model_family:"panel_ols",covariance:"clustered"}}}]}};
  render(<AgentPlanPanel />);
  const definitions = screen.getByRole("region",{name:"Fixed deliverable definitions"});
  expect(definitions).toHaveTextContent("alternate_covariance · model.genesis");
  expect(definitions).toHaveTextContent("Report uncertainty");
  expect(definitions).toHaveTextContent("summary");
  expect(definitions).toHaveTextContent('"covariance": "clustered"');
  expect(definitions).toHaveTextContent("producer-verified");
  expect(state.agent.approvePlan).not.toHaveBeenCalled();
});
it("names a missing legacy plan definition rather than showing an empty requirement title", () => {
  state.agent.planVerification = {plan_id:"p1",plan_version:3,status:"partial",playbook_status:"requirements_met",
    criteria_verification:{plan_id:"p1",plan_version:3,basis_sha256:"a".repeat(64),status:"partial",
      requirements:[{id:"",status:"unverified",reason:"No machine-checkable approved deliverable definitions were saved.",verified_artifacts:[]}],
      unbound_slots:[{criterion_index:0}]}};
  render(<AgentPlanPanel />);
  expect(screen.getByText("Plan definitions · unverified")).toBeInTheDocument();
  expect(screen.getByText(/Not bound: Report uncertainty/)).toBeInTheDocument();
});
it("observes plan-event to DOM latency separately from browser paint", () => {
  const view = render(<AgentPlanPanel />);
  const samples: number[] = [];
  for (let index = 0; index < 20; index += 1) {
    const started = performance.now();
    state.agent.plan = { ...plan(), version: index + 4, question: `Recorded plan update ${index}` };
    view.rerender(<AgentPlanPanel />);
    expect(screen.getByText(`Recorded plan update ${index}`)).toBeInTheDocument();
    samples.push(performance.now() - started);
  }
  console.info("PLAN_DOM_LATENCY_MS", JSON.stringify(samples));
  expect(Math.max(...samples)).toBeLessThanOrEqual(200);
});
it("shows server states and dependencies; approves exactly the displayed version without continuing", () => {
  render(<AgentPlanPanel />);
  expect(screen.getByText("Compare groups")).toBeInTheDocument();
  expect(screen.getByText(/after a/)).toBeInTheDocument();
  expect(screen.getByText("done")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Approve plan v3"}));
  expect(state.agent.approvePlan).toHaveBeenCalledWith(3);
  expect(state.agent.sendPrompt).not.toHaveBeenCalled();
  expect(state.agent.continueTurn).not.toHaveBeenCalled();
});
it("sends the version and editable envelope without step status", async () => {
  render(<AgentPlanPanel />);
  fireEvent.click(screen.getByRole("button",{name:"Edit plan"}));
  fireEvent.change(screen.getByRole("textbox",{name:"Plan question"}),{target:{value:"Edited question"}});
  fireEvent.change(screen.getByRole("textbox",{name:"Step b title"}),{target:{value:"Edited title"}});
  fireEvent.click(screen.getByRole("button",{name:"Save plan"}));
  await waitFor(() => expect(state.agent.savePlan).toHaveBeenCalledWith({version:3,question:"Edited question",criteria:["Report uncertainty"],steps:[
    {step_id:"a",title:"Inspect",operation_ids:["stat.describe"],depends_on:[],expected_outputs:["summary"]},
    {step_id:"b",title:"Edited title",operation_ids:["stat.test"],depends_on:["a"],expected_outputs:[]}]}));
});
it("retains drafts on conflict and server refresh", async () => {
  state.agent.savePlan.mockRejectedValue(Object.assign(new Error("Plan changed; reload the current plan."),{status:409}));
  const view=render(<AgentPlanPanel />);
  fireEvent.click(screen.getByRole("button",{name:"Edit plan"}));
  fireEvent.change(screen.getByRole("textbox",{name:"Plan question"}),{target:{value:"My draft"}});
  fireEvent.click(screen.getByRole("button",{name:"Save plan"}));
  expect(await screen.findByRole("alert")).toHaveTextContent(/reload/i);
  fireEvent.click(screen.getByRole("button",{name:"Reload current plan"}));
  state.agent.plan={...plan(),version:4,question:"Another edit"};view.rerender(<AgentPlanPanel />);
  expect(screen.getByRole("textbox",{name:"Plan question"})).toHaveValue("My draft");
  expect(state.agent.refreshPlan).toHaveBeenCalled();
});
it("requires explicit delivery selection during an active turn", () => {
  state.agent.isSubmitting=true;render(<AgentRunControls />);
  expect(screen.getByRole("combobox",{name:"Agent execution mode"})).toBeDisabled();
  expect(screen.getByRole("button",{name:"Send active-turn message"})).toBeDisabled();
  fireEvent.change(screen.getByRole("combobox",{name:"Active-turn message delivery"}),{target:{value:"steer"}});
  fireEvent.click(screen.getByRole("button",{name:"Send active-turn message"}));
  expect(state.agent.queueTurnMessage).toHaveBeenCalledWith("steer","new direction");
  expect(state.agent.sendPrompt).not.toHaveBeenCalled();
});

it("does not offer manual continuation for an idle session", () => {
  state.agent.sessionId="saved";
  render(<AgentRunControls />);
  expect(state.agent.continueTurn).not.toHaveBeenCalled();
  expect(screen.queryByRole("button",{name:"Continue Agent"})).not.toBeInTheDocument();
  expect(state.agent.approvePlan).not.toHaveBeenCalled();
});

it("discards the local editor when moving to another session", () => {
  state.agent.sessionId="session-a";
  const view=render(<AgentPlanPanel />);
  fireEvent.click(screen.getByRole("button",{name:"Edit plan"}));
  fireEvent.change(screen.getByRole("textbox",{name:"Plan question"}),{target:{value:"A draft"}});
  state.agent.sessionId="session-b";
  state.agent.plan={...plan(),plan_id:"b",question:"B question"};
  view.rerender(<AgentPlanPanel />);
  expect(screen.queryByRole("textbox",{name:"Plan question"})).not.toBeInTheDocument();
  expect(screen.getByText("B question")).toBeInTheDocument();
  expect(state.agent.savePlan).not.toHaveBeenCalled();
});
it("shows approval failures without an unhandled rejection", async () => {
  state.agent.approvePlan.mockRejectedValue(new Error("Version changed"));
  render(<AgentPlanPanel />);
  fireEvent.click(screen.getByRole("button",{name:"Approve plan v3"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Version changed");
});

it("offers non-local running turn recovery and explains server ownership validation", () => {
  state.agent.sessionId="saved";
  state.agent.sessionStatus="idle";
  state.agent.durableTurns=[{turn_id:"orphan",status:"running",requires_reconcile:false}];
  state.agent.resumeTurn=vi.fn().mockResolvedValue(undefined);
  render(<AgentRunControls />);
  fireEvent.click(screen.getByRole("button",{name:"Resume original turn"}));
  expect(state.agent.resumeTurn).toHaveBeenCalledWith("orphan");
  expect(screen.getByText(/server verifies.*still running/i)).toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"Continue Agent"})).not.toBeInTheDocument();
});
it("hides recovery during a local submission", () => {
  state.agent.isSubmitting=true;
  state.agent.durableTurns=[{turn_id:"local",status:"running",requires_reconcile:false}];
  render(<AgentRunControls />);
  expect(screen.queryByRole("button",{name:"Resume original turn"})).not.toBeInTheDocument();
});

it("keeps edits made while an earlier draft save is pending without rebasing them", async () => {
  let finishSave!: () => void;
  state.agent.savePlan.mockReturnValue(new Promise<void>(resolve => { finishSave=resolve; }));
  const view=render(<AgentPlanPanel />);
  fireEvent.click(screen.getByRole("button",{name:"Edit plan"}));
  fireEvent.change(screen.getByRole("textbox",{name:"Plan question"}),{target:{value:"Submitted A"}});
  fireEvent.click(screen.getByRole("button",{name:"Save plan"}));
  state.agent.planBusy=true;view.rerender(<AgentPlanPanel />);
  fireEvent.change(screen.getByRole("textbox",{name:"Plan question"}),{target:{value:"Unsubmitted B"}});
  state.agent.plan={...plan(),version:4,question:"Submitted A"};
  state.agent.planBusy=false;
  await act(async () => { finishSave(); });
  view.rerender(<AgentPlanPanel />);
  expect(screen.getByRole("textbox",{name:"Plan question"})).toHaveValue("Unsubmitted B");
  expect(screen.getByText(/A newer plan is available/)).toHaveAttribute("role", "status");
  expect(screen.getByRole("button",{name:"Save plan"})).toBeDisabled();
  expect(state.agent.savePlan).toHaveBeenCalledTimes(1);
  expect(state.agent.savePlan).toHaveBeenCalledWith(expect.objectContaining({version:3,question:"Submitted A"}));
});

it("offers a single explicit Auto approve-and-run action while retaining approval only", () => {
  state.agent.executionMode="auto";
  state.agent.approveAndRunPlan=vi.fn().mockResolvedValue(undefined);
  render(<AgentPlanPanel />);
  expect(screen.getByRole("button",{name:"Approve plan v3"})).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Approve and run plan v3"}));
  expect(state.agent.approveAndRunPlan).toHaveBeenCalledWith(3);
  expect(state.agent.approvePlan).not.toHaveBeenCalled();
  expect(state.agent.continueTurn).not.toHaveBeenCalled();
});
it("hides approve-and-run in Ask mode and while editing a draft", () => {
  state.agent.approveAndRunPlan=vi.fn();
  const view=render(<AgentPlanPanel />);
  expect(screen.queryByRole("button",{name:/Approve and run/})).not.toBeInTheDocument();
  state.agent.executionMode="auto";view.rerender(<AgentPlanPanel />);
  fireEvent.click(screen.getByRole("button",{name:"Edit plan"}));
  expect(screen.queryByRole("button",{name:/Approve and run/})).not.toBeInTheDocument();
});
