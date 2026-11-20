import "@testing-library/jest-dom/vitest";
import {act, render, screen, waitFor} from "@testing-library/react";
import type {ReactNode} from "react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {ModelResultView} from "./ModelResultView";
import {fetchArtifactJson, fetchRunDetail, type RunDetail} from "../../api";
import type {GraphViewNode} from "../../lineage/api/graphViewTypes";
import type {IVDiagnostics} from "../../runResult/IVDiagnosticsCard";

vi.mock("../../api", () => ({fetchRunDetail: vi.fn(), fetchArtifactJson: vi.fn()}));
vi.mock("../../workbench/agent/useCompletedOperation", () => ({useCompletedOperation: () => null}));
vi.mock("./ResultActions", () => ({ResultActions: () => null}));
vi.mock("./ResultSelection", () => ({ResultSelection: ({children}: {children: ReactNode}) => children}));
afterEach(() => vi.clearAllMocks());
beforeEach(() => {
  vi.mocked(fetchRunDetail).mockReset();
  vi.mocked(fetchArtifactJson).mockReset().mockRejectedValue(new Error("HTTP 404: completion artifact not found"));
});

const node = {id: "model:iv_1", stage: "model", kind: "model", decisions: [], raw: null} as unknown as GraphViewNode;
const model = {model_id: "iv_1", model_type: "iv_2sls", coefficients: {d: {estimate: 1, std_error: 0.2}}};
const diagnostics: IVDiagnostics = {
  identification: "over",
  weak_instruments: {first_stage_f: 24.3, threshold: null, verdict: "unassessed", message: "Strength is not certified."},
  endogeneity: {test: "wu_hausman", statistic: 1.25, pvalue: 0.31437263764701706, verdict: "does_not_reject", message: "Bound Wu for selected model."},
  overidentification: {applicable: true, test: "sargan", statistic: 1.9, pvalue: 0.168, verdict: "not_rejected", message: "Validity is not certified."},
};
const completion = (iv = diagnostics) => ({contract: "analysis-completion.evidence.v2", model_id: "iv_1", model_type: "iv_2sls", diagnostics: {iv}});
const detail = (models = [model]) => ({model_results: models} as unknown as RunDetail);

it("shows the selected third model's actual reference fallback from its owner run", async () => {
  vi.mocked(fetchRunDetail).mockResolvedValue({model_results: [
    {...model, model_id: "sibling_1"}, {...model, model_id: "sibling_2"},
    {...model, engine_provenance: {requested: "fast", used: "reference", reason: "native engine is not built"}},
  ]} as unknown as RunDetail);
  render(<ModelResultView projectRoot="/project" runId="owner-run" node={node}/>);
  expect(await screen.findByText("Actual engine: reference")).toBeInTheDocument();
  expect(screen.getByText("native engine is not built")).toBeInTheDocument();
  expect(screen.getByText(/Experimental fast IV; resource acceptance pending/)).toBeInTheDocument();
  expect(fetchRunDetail).toHaveBeenCalledWith("/project", "owner-run");
});

it("leaves default results without an engine receipt", async () => {
  vi.mocked(fetchRunDetail).mockResolvedValue({model_results: [model]} as unknown as RunDetail);
  render(<ModelResultView projectRoot="/project" runId="owner-run" node={node}/>);
  await waitFor(() => expect(screen.getByRole("article", {name: "Result"})).toBeInTheDocument());
  expect(screen.queryByText(/Actual engine:/)).not.toBeInTheDocument();
});

it("shows the selected modern model's registered completion IV card", async () => {
  vi.mocked(fetchRunDetail).mockResolvedValue(detail([{...model, model_id: "sibling"}, model]));
  vi.mocked(fetchArtifactJson).mockResolvedValue(completion());
  render(<ModelResultView projectRoot="/project" runId="owner-run" node={node}/>);
  expect(await screen.findByRole("region", {name: "IV diagnostics"})).toHaveTextContent("Wu-Hausman stat=1.25");
  expect(screen.getByText("Bound Wu for selected model.")).toBeInTheDocument();
  expect(fetchArtifactJson).toHaveBeenCalledTimes(1);
  expect(fetchArtifactJson).toHaveBeenCalledWith("/project", "owner-run", "iv_1.completion");
});

it("keeps unavailable Wu reason and null probability visible on the modern page", async () => {
  vi.mocked(fetchRunDetail).mockResolvedValue(detail());
  vi.mocked(fetchArtifactJson).mockResolvedValue(completion({...diagnostics, endogeneity: {
    test: "wu_hausman", statistic: null, pvalue: null, verdict: "unavailable", reason: "insufficient_residual_df",
    message: "IV_WU_HAUSMAN_UNAVAILABLE: insufficient_residual_df: positive residual degrees of freedom required.",
  }}));
  render(<ModelResultView projectRoot="/project" runId="small-run" node={node}/>);
  expect(await screen.findByText("Wu-Hausman unavailable: insufficient_residual_df")).toBeInTheDocument();
  expect(screen.queryByText(/Wu-Hausman stat=/)).not.toBeInTheDocument();
  expect(screen.getByText(/IV_WU_HAUSMAN_UNAVAILABLE:/)).toBeInTheDocument();
});

it.each([
  ["owner model", {model_id: "sibling"}, /does not match the selected model/],
  ["model type", {model_type: "ols"}, /model type/],
  ["contract", {contract: "analysis-completion.evidence.v1"}, /contract/],
  ["missing diagnostics", {diagnostics: {}}, /no IV diagnostics/],
  ["malformed diagnostics", {diagnostics: {iv: {}}}, /malformed IV diagnostics/],
] as const)("refuses %s evidence with an explicit notice", async (_, override, message) => {
  vi.mocked(fetchRunDetail).mockResolvedValue(detail());
  vi.mocked(fetchArtifactJson).mockResolvedValue({...completion(), ...override});
  render(<ModelResultView projectRoot="/project" runId="owner-run" node={node}/>);
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.queryByRole("region", {name: "IV diagnostics"})).not.toBeInTheDocument();
});

it("shows HTTP/missing-artifact errors without using run-level standalone diagnostics", async () => {
  vi.mocked(fetchRunDetail).mockResolvedValue({...detail(), iv_diagnostics: diagnostics} as unknown as RunDetail);
  render(<ModelResultView projectRoot="/project" runId="owner-run" node={node}/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 404: completion artifact not found");
  expect(screen.queryByRole("region", {name: "IV diagnostics"})).not.toBeInTheDocument();
  expect(fetchArtifactJson).toHaveBeenCalledTimes(1);
  expect(fetchArtifactJson).toHaveBeenCalledWith("/project", "owner-run", "iv_1.completion");
});

it.each([
  ["weak verdict object", {verdict: {value: "unassessed"}}],
  ["weak reference object", {reference_distribution: {name: "F(2,60)"}}],
  ["AR components object", {anderson_rubin_95: {kind: "disjoint", components: {}}}],
  ["null AR component", {anderson_rubin_95: {kind: "disjoint", components: [null]}}],
] as const)("reports %s as a bad artifact while preserving the primary result", async (_, override) => {
  vi.mocked(fetchRunDetail).mockResolvedValue(detail());
  vi.mocked(fetchArtifactJson).mockResolvedValue({...completion(), diagnostics: {iv: {
    ...diagnostics, weak_instruments: {...diagnostics.weak_instruments, ...override},
  }}});
  render(<ModelResultView projectRoot="/project" runId="owner-run" node={node}/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("malformed IV diagnostics");
  expect(screen.getByRole("article", {name: "Result"})).toBeInTheDocument();
  expect(screen.getByRole("table")).toHaveTextContent("d");
  expect(screen.queryByRole("region", {name: "IV diagnostics"})).not.toBeInTheDocument();
});

it("discards a previous run's late completion response", async () => {
  vi.mocked(fetchRunDetail).mockResolvedValue(detail());
  let resolveOld!: (value: unknown) => void;
  const oldResponse = new Promise(resolve => {resolveOld = resolve;});
  vi.mocked(fetchArtifactJson).mockImplementation((_, runId) => runId === "old-run"
    ? oldResponse as Promise<never> : Promise.resolve(completion()) as Promise<never>);
  const view = render(<ModelResultView projectRoot="/project" runId="old-run" node={node}/>);
  await waitFor(() => expect(fetchArtifactJson).toHaveBeenCalledWith("/project", "old-run", "iv_1.completion"));
  view.rerender(<ModelResultView projectRoot="/project" runId="current-run" node={node}/>);
  expect(await screen.findByText("Bound Wu for selected model.")).toBeInTheDocument();
  await act(async () => {resolveOld(completion({...diagnostics, endogeneity: {...diagnostics.endogeneity, message: "Wrong old run Wu."}}));});
  expect(screen.queryByText("Wrong old run Wu.")).not.toBeInTheDocument();
  expect(screen.getByText("Bound Wu for selected model.")).toBeInTheDocument();
  expect(fetchArtifactJson).toHaveBeenCalledWith("/project", "current-run", "iv_1.completion");
});

it("fetches the newly selected sibling's evidence instead of retaining the previous card", async () => {
  vi.mocked(fetchRunDetail).mockResolvedValue(detail([model, {...model, model_id: "iv_2"}]));
  vi.mocked(fetchArtifactJson).mockResolvedValueOnce(completion()).mockResolvedValueOnce({...completion(), model_id: "iv_2",
    diagnostics: {iv: {...diagnostics, endogeneity: {...diagnostics.endogeneity, message: "Second model Wu."}}}});
  const view = render(<ModelResultView projectRoot="/project" runId="owner-run" node={node}/>);
  await screen.findByText("Bound Wu for selected model.");
  view.rerender(<ModelResultView projectRoot="/project" runId="owner-run" node={{...node, id: "model:iv_2"}}/>);
  expect(screen.queryByText("Bound Wu for selected model.")).not.toBeInTheDocument();
  expect(await screen.findByText("Second model Wu.")).toBeInTheDocument();
  expect(fetchArtifactJson).toHaveBeenLastCalledWith("/project", "owner-run", "iv_2.completion");
});

it("does not load IV evidence for other model families", async () => {
  vi.mocked(fetchRunDetail).mockResolvedValue(detail([{...model, model_type: "ols"}]));
  render(<ModelResultView projectRoot="/project" runId="owner-run" node={node}/>);
  await screen.findByRole("article", {name: "Result"});
  expect(fetchArtifactJson).not.toHaveBeenCalled();
});
