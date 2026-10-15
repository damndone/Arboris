import * as dataApi from "../dataView/dataViewApi";
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { OperationsPanel } from "./OperationsPanel";
import { ManualReportPanel } from "./ManualReportPanel";
import * as api from "./manualApi";
vi.mock("./manualApi", async (original) => ({ ...await original<typeof api>(), catalog: vi.fn(), execute: vi.fn(), reportDraft: vi.fn(), reportHistory: vi.fn(), saveReport: vi.fn() }));
vi.mock("../dataView/dataViewApi", () => ({ listDatasets: vi.fn(async () => [{ node_id: "data", label: "Input" }]), fetchDatasetPage: vi.fn(async () => ({ artifact_id: "input.csv", columns: ["x"] })) }));
const operation = { id: "test.example", name: "Example", category: "test", summary: "Example test", spec_schema: { type: "object", properties: { options: { type: "object" } }, required: ["options"] }, execution: { kind: "workflow" }, availability: { status: "available" } };
const preview = { request_id: "request-frozen", preview_id: "preview-frozen", fingerprint: "sha256:frozen", status: "awaiting_confirmation", expected_effect: ["Read data"], risks: [], steps: [] };
const draft = { run_id: "run", title: "Evidence report", text: "Computed findings", source_fingerprint: "sha256:original", facts: [{ id: "fact1", label: "N", value: 80, field: "n", source: { run_id: "run" } }], figures: [], limitations: [] };
beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.catalog).mockResolvedValue({ operations: [operation] } as never); vi.mocked(api.execute).mockResolvedValue(preview as never); vi.mocked(api.reportDraft).mockResolvedValue(draft as never); vi.mocked(api.reportHistory).mockResolvedValue({ reports: [] } as never); });
afterEach(cleanup);
function operations() { return render(<OperationsPanel projectRoot="/test" runId="run" models={[]} onClose={vi.fn()} onRefresh={vi.fn()} onOpenRun={vi.fn()} onDedicated={vi.fn()}/>); }
async function add() { await screen.findByRole("button", { name: /^Example$/ }); await waitFor(() => expect(screen.getByLabelText("Analysis target")).toHaveValue("0")); fireEvent.click(screen.getByRole("button", { name: /^Example$/ })); }
function addOption() {fireEvent.change(screen.getByLabelText("Step 1.options new field name"),{target:{value:"alpha"}});fireEvent.click(screen.getByRole("button",{name:"Add Step 1.options field"}));}
it("confirms only frozen tokens and invalidates confirmation on structure changes",async()=>{operations();await add();fireEvent.click(screen.getByRole("button",{name:"Preview analysis"}));fireEvent.click(await screen.findByRole("button",{name:"Confirm analysis"}));await waitFor(()=>expect(api.execute).toHaveBeenCalledTimes(2));expect(vi.mocked(api.execute).mock.calls[1][1]).toEqual({mode:"confirm",request_id:"request-frozen",preview_id:"preview-frozen",fingerprint:"sha256:frozen"});addOption();expect(screen.queryByRole("button",{name:"Confirm analysis"})).toBeNull();});
it("blocks incomplete typed values and preserves the request id for network retry",async()=>{vi.mocked(api.execute).mockRejectedValueOnce(new Error("Network interrupted")).mockResolvedValue(preview as never);operations();await add();addOption();fireEvent.click(screen.getByRole("button",{name:"Preview analysis"}));expect(api.execute).not.toHaveBeenCalled();fireEvent.change(screen.getByLabelText("Step 1.options.alpha value type"),{target:{value:"1"}});fireEvent.change(screen.getByLabelText("Step 1.options.alpha"),{target:{value:"0.05"}});fireEvent.click(screen.getByRole("button",{name:"Preview analysis"}));await screen.findByText("Network interrupted");fireEvent.click(screen.getByRole("button",{name:"Preview analysis"}));await screen.findByRole("button",{name:"Confirm analysis"});expect(vi.mocked(api.execute).mock.calls[0][1]).toEqual(vi.mocked(api.execute).mock.calls[1][1]);});
it("target changes discard the preview and its editable steps", async () => { operations(); await add(); fireEvent.click(screen.getByRole("button", { name: "Preview analysis" })); await screen.findByRole("button", { name: "Confirm analysis" }); fireEvent.change(screen.getByLabelText("Analysis target"), { target: { value: "" } }); expect(screen.queryByRole("button", { name: "Confirm analysis" })).toBeNull(); expect(screen.queryByLabelText("Step 1.options")).toBeNull(); await waitFor(() => expect(screen.queryByText("Loading operations…")).toBeNull()); });
it("saves immutable evidence references and creates a linked report revision", async () => { vi.mocked(api.saveReport).mockImplementation(async (_root, _run, body) => ({ record: { ...draft, ...body, id: body.id, revision_number: body.parent_report_id ? 2 : 1, created_at: "2026-10-09", author: "user" } } as never)); render(<ManualReportPanel projectRoot="/test" runId="run"/>); await screen.findByDisplayValue("Evidence report"); fireEvent.click(screen.getByRole("button", { name: "Edit text" })); fireEvent.change(screen.getByLabelText("Report text"), { target: { value: "My interpretation" } }); fireEvent.click(screen.getByRole("button", { name: "Save manual report" })); await screen.findByText("Saved · version 1 · author: user"); fireEvent.click(screen.getByRole("button", {name:"Evidence"})); const evidenceList = screen.getByText(/Computed evidence/).closest("details")!; expect(screen.queryByRole("checkbox")).toBeNull(); evidenceList.open = true; fireEvent(evidenceList, new Event("toggle")); expect(await screen.findByRole("checkbox")).toBeDisabled(); const first = vi.mocked(api.saveReport).mock.calls[0][2]; expect(first).toMatchObject({ title: "Evidence report", text: "My interpretation", source_fingerprint: "sha256:original", fact_ids: ["fact1"], figure_ids: [] }); expect(first).not.toHaveProperty("facts"); expect(screen.getByRole("link", { name: "Export DOCX" })).toHaveAttribute("href", expect.stringContaining("format=docx")); fireEvent.change(screen.getByLabelText("Report text"), { target: { value: "Revised interpretation" } }); fireEvent.click(screen.getByRole("button", { name: "Save report revision" })); await screen.findByText("Saved · version 2 · author: user"); expect(vi.mocked(api.saveReport).mock.calls[1][2]).toMatchObject({ parent_report_id: first.id, text: "Revised interpretation" }); });
it("keeps typed union values consistent after deleting an earlier rule",async()=>{vi.mocked(api.catalog).mockResolvedValue({operations:[{...operation,spec_schema:{type:"object",properties:{rules:{type:"array",items:{type:"object",required:["from"],properties:{from:{anyOf:[{type:"string"},{type:"number"}]}}}}},required:["rules"]}}]} as never);operations();await add();for(const [index,value] of ["first","second"].entries()){fireEvent.click(screen.getByRole("button",{name:"Add Step 1.rules item"}));fireEvent.change(screen.getByLabelText(`Step 1.rules[${index+1}].from value type`),{target:{value:"0"}});fireEvent.change(screen.getByLabelText(`Step 1.rules[${index+1}].from`),{target:{value}});}fireEvent.click(screen.getByRole("button",{name:"Remove Step 1.rules item 1"}));expect(screen.getByLabelText("Step 1.rules[1].from")).toHaveValue("second");fireEvent.click(screen.getByRole("button",{name:"Preview analysis"}));await screen.findByRole("button",{name:"Confirm analysis"});expect(vi.mocked(api.execute).mock.calls[0][1].steps?.[0].spec).toEqual({rules:[{from:"second"}]});});
it('passes a selected producer binding through preview and refuses a deleted producer',async()=>{
  vi.mocked(api.catalog).mockResolvedValue({operations:[{...operation,spec_schema:{...operation.spec_schema,additionalProperties:false}}]} as never);
  operations();await add();fireEvent.click(screen.getByRole('button',{name:'Add a step'}));fireEvent.click(screen.getByRole('button',{name:/^Example$/}));
  const select=screen.getByLabelText('Step 2 dataset producer') as HTMLSelectElement;
  fireEvent.change(select,{target:{value:select.options[1].value}});
  fireEvent.click(screen.getByRole('button',{name:'Preview analysis'}));await screen.findByRole('button',{name:'Confirm analysis'});
  const steps=vi.mocked(api.execute).mock.calls[0][1].steps as {step_id:string;spec:Record<string,unknown>}[];
  expect(steps[1].spec.source).toEqual({from_step:steps[0].step_id,output:'produced_dataset'});
  fireEvent.click(screen.getByRole('button',{name:'Remove step 1'}));
  fireEvent.click(screen.getByRole('button',{name:'Preview analysis'}));
  expect(screen.getByRole('alert')).toHaveTextContent('dataset producer no longer exists');expect(api.execute).toHaveBeenCalledTimes(1);
});
it('selects an earlier model branch and removes a stale explicit owner run',async()=>{
  const branch = {type: 'object', required: ['branch_id'], additionalProperties: false, properties: {branch_id: {type: 'string'}}};
  const producer = {...operation, spec_schema: {type: 'object', required: ['branches'], additionalProperties: false, properties: {branches: {type: 'array', items: branch}}}};
  const consumer={...operation,id:'postestimation.example',name:'Model test',spec_schema:{type:'object',required:['model_ref'],additionalProperties:false,properties:{model_ref:{type:'string'},model_run_id:{type:'string'}}}};
  vi.mocked(api.catalog).mockResolvedValue({operations:[producer,consumer]} as never);
  operations();await add();fireEvent.click(screen.getByRole('button',{name:'Add Step 1.branches item'}));fireEvent.change(screen.getByLabelText('Step 1.branches[1].branch_id'),{target:{value:'fit'}});
  fireEvent.click(screen.getByRole('button',{name:'Add a step'}));fireEvent.click(screen.getByRole('button',{name:/^Model test$/}));fireEvent.change(screen.getByLabelText('Step 2 optional field'),{target:{value:'model_run_id'}});fireEvent.change(screen.getByLabelText('Step 2.model_run_id'),{target:{value:'stale-owner'}});
  const select=screen.getByLabelText('Step 2 model producer') as HTMLSelectElement;fireEvent.change(select,{target:{value:select.options[1].value}});
  fireEvent.click(screen.getByRole('button',{name:'Preview analysis'}));await screen.findByRole('button',{name:'Confirm analysis'});
  const steps=vi.mocked(api.execute).mock.calls[0][1].steps as {step_id:string;spec:Record<string,unknown>}[];
  expect(steps[1].spec.model_ref).toBe(`step:${steps[0].step_id}:fit`);expect(steps[1].spec).not.toHaveProperty('model_run_id');
});

it('keeps dedicated navigation on the explicitly selected target and explains mismatches',async()=>{
 const onDedicated=vi.fn();
 vi.mocked(api.catalog).mockResolvedValue({operations:[{...operation,id:'code.execute',name:'Run code',target_requirements:['dataset_node','risk_authorization'],execution:{kind:'dedicated'}}]} as never);
 render(<OperationsPanel projectRoot="/test" runId="run" models={[{runId:'other',nodeId:'model:ols',label:'OLS'}]} onClose={vi.fn()} onRefresh={vi.fn()} onOpenRun={vi.fn()} onDedicated={onDedicated}/>);
 await waitFor(()=>expect(screen.getByLabelText('Analysis target')).toHaveValue('0'));
 fireEvent.click(await screen.findByRole('button',{name:/Run code/}));
 expect(onDedicated).toHaveBeenCalledWith(expect.objectContaining({id:'code.execute'}),{kind:'dataset_node',run_id:'run',node_id:'data',artifact_id:'input.csv'});
 fireEvent.change(screen.getByLabelText('Analysis target'),{target:{value:'1'}});
 await waitFor(()=>expect(screen.getByRole('button',{name:/Run code/})).toBeDisabled());
 expect(screen.getByRole('button',{name:/Run code/})).toHaveTextContent('Select a dataset target first.');
});
it('retains the original target and receipt when execution refresh selects a new run',async()=>{
 vi.mocked(api.execute).mockResolvedValue({...preview,status:'completed'} as never);
 const props={projectRoot:'/test',models:[],onClose:vi.fn(),onRefresh:vi.fn(),onOpenRun:vi.fn(),onDedicated:vi.fn()};
 const view=render(<OperationsPanel {...props} runId="original"/>);await add();
 fireEvent.click(screen.getByRole('button',{name:'Preview analysis'}));await screen.findByRole('heading',{name:'Completed'});
 view.rerender(<OperationsPanel {...props} runId="newly-created" models={[{runId:'newly-created',nodeId:'model:iv',label:'IV'}]}/>);
 await waitFor(()=>expect(screen.getByLabelText('Analysis target')).toHaveTextContent('IV'));
 expect(screen.getByRole('heading',{name:'Completed'})).toBeVisible();
 expect(vi.mocked(api.catalog).mock.calls.some(([,target]) => target?.kind === 'dataset_node' && target.run_id === 'original')).toBe(true);
 expect(api.execute).toHaveBeenCalledOnce();
});

it("binds an inline model test to its owner rather than the first dataset", async () => {
  render(<OperationsPanel projectRoot="/test" runId="run" models={[{runId:"source",nodeId:"model:ols_1",label:"OLS"}]} initialTarget={{kind:"model_node",run_id:"source",node_id:"model:ols_1"}} onClose={vi.fn()} onRefresh={vi.fn()} onOpenRun={vi.fn()} onDedicated={vi.fn()}/>);
  await waitFor(()=>expect(screen.getByLabelText("Analysis target")).toHaveValue("1"));
  await waitFor(()=>expect(api.catalog).toHaveBeenLastCalledWith("/test",{kind:"model_node",run_id:"source",node_id:"model:ols_1"}));
});

it('distinguishes repeated dataset labels and exposes the selected source', async () => {
  vi.mocked(dataApi.listDatasets).mockResolvedValueOnce([{node_id:'recode:first',label:'Recode dataset'},{node_id:'recode:second',label:'Recode dataset'}] as never);
  operations();
  await screen.findByRole('option',{name:'Recode dataset (2)'});
  fireEvent.change(screen.getByLabelText('Analysis target'),{target:{value:'1'}});
  fireEvent.click(screen.getByText('Source details'));
  expect(screen.getByText('recode:second')).toBeVisible();
  await waitFor(()=>expect(api.catalog).toHaveBeenLastCalledWith('/test',expect.objectContaining({node_id:'recode:second'})));
});

it("groups operations by the catalog's own words and says why one cannot run", async () => {
  vi.mocked(api.catalog).mockResolvedValue({ operations: [
    { ...operation, id: "postestimation.wald", name: "Wald test", blurb: "Jointly test restrictions.", group: "check", group_label: "Check a model", group_order: 4 },
    { ...operation, id: "data.rename", name: "Rename columns", blurb: "Give columns new names.", group: "prepare", group_label: "Prepare data", group_order: 0 },
    { ...operation, id: "model.custom", name: "Custom model", blurb: "Admitted custom models.", group: "advanced", group_label: "Advanced", group_order: 14,
      availability: { status: "unavailable", message: "Needs an admitted notebook option." } },
  ] } as never);
  operations();
  const groups = await screen.findByRole("navigation", { name: "Operation groups" });
  expect([...groups.querySelectorAll("button")].map((b) => b.firstChild?.textContent)).toEqual(["All", "Prepare data", "Check a model", "Advanced"]);
  expect(screen.getByRole("button", { name: "Custom model" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Custom model" })).toHaveAccessibleDescription("Needs an admitted notebook option.");
  fireEvent.change(screen.getByLabelText("Find an operation"), { target: { value: "restrictions" } });
  expect(screen.getByRole("button", { name: "Wald test" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Rename columns" })).toBeNull();
});
