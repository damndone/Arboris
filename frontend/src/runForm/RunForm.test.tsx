import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

vi.mock("../capabilities/useCapabilities", () => ({
  useCapabilities: () => ({
    data: {
      schema_version: 1,
      model_types: [
        { key: "auto", label: "Auto (infer from y)", group: "auto" },
        { key: "ols", label: "OLS (linear)", group: "Linear" },
        { key: "iv_2sls", label: "IV / 2SLS", group: "IV" },
        { key: "did", label: "DID", group: "Causal" },
        { key: "cs_did", label: "Callaway-Sant'Anna", group: "Causal" },
        { key: "sa_did", label: "Sun-Abraham", group: "Causal" },
        { key: "time_series.arma_garch", label: "ARMA-GARCH", group: "Time Series" },
        { key: "ordinal_logit", label: "Ordinal logit", group: "Ordinal" },
        { key: "multinomial_logit", label: "Multinomial logit", group: "Nominal" },
        { key: "survival_cox", label: "Survival / Cox", group: "Survival" },
        { key: "quantile_regression", label: "Quantile regression", group: "Quantile" },
      ],
      imputation_methods: [],
      covariance_options: [
        { key: "robust", label: "Robust (HC)" },
        { key: "unadjusted", label: "Unadjusted" },
      ],
    },
    loading: false,
    error: null,
    refetch: () => {},
  }),
}));

import * as api from "../api";
import { RunForm } from "./RunForm";
import type { RunResponse } from "../api";

const RUN_RESPONSE: RunResponse = {
  run_id: "run-iv-1",
  status: "completed",
} as unknown as RunResponse;

function renderForm() {
  return render(
    <MemoryRouter>
      <RunForm
        projectRoot="/tmp/proj"
        setError={() => {}}
        setActivity={() => {}}
        activity=""
        requestState="idle"
        setRequestState={() => {}}
      />
    </MemoryRouter>,
  );
}

function fillForm(): void {
  fireEvent.change(screen.getByLabelText("dependent variable"), {
    target: { value: "wage" },
  });
  fireEvent.change(screen.getByLabelText("independent variables"), {
    target: { value: "age, educ, dist" },
  });
  const file = new File(["a\n1\n"], "data.csv", { type: "text/csv" });
  fireEvent.change(screen.getByLabelText("data file"), {
    target: { files: [file] },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
  try {
    sessionStorage.clear();
  } catch {
    // ignore
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("RunForm IV wiring", () => {
  it("renders IV role selects and a covariance select when model is iv_2sls", () => {
    renderForm();
    fillForm();
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "iv_2sls" },
    });
    expect(screen.getByLabelText("role-age")).toBeInTheDocument();
    expect(screen.getByLabelText("role-educ")).toBeInTheDocument();
    expect(screen.getByLabelText("role-dist")).toBeInTheDocument();
    expect(screen.getByLabelText("covariance")).toBeInTheDocument();
  });

  it("posts x = exog only plus iv_endog / iv_instruments arrays", async () => {
    const spy = vi
      .spyOn(api, "runWorkflow")
      .mockResolvedValue(RUN_RESPONSE);
    renderForm();
    fillForm();
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "iv_2sls" },
    });
    fireEvent.change(screen.getByLabelText("role-educ"), {
      target: { value: "endog" },
    });
    fireEvent.change(screen.getByLabelText("role-dist"), {
      target: { value: "instrument" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run workflow/i }));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    const call = spy.mock.calls[0];
    // x argument (index 3) must be exog only — no endog/instrument cols.
    expect(call[3]).toBe("age");
    const extra = call[9];
    expect(extra?.ivEndog).toEqual(["educ"]);
    expect(extra?.ivInstruments).toEqual(["dist"]);
  });

  it("does not send did fields for a non-DID model", async () => {
    const spy = vi
      .spyOn(api, "runWorkflow")
      .mockResolvedValue(RUN_RESPONSE);
    renderForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /run workflow/i }));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    const extra = spy.mock.calls[0][9];
    expect(extra?.didMode).toBeUndefined();
  });

  it("does not send iv fields for a non-IV model", async () => {
    const spy = vi
      .spyOn(api, "runWorkflow")
      .mockResolvedValue(RUN_RESPONSE);
    renderForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /run workflow/i }));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    const call = spy.mock.calls[0];
    expect(call[3]).toBe("age,educ,dist");
    const extra = call[9];
    expect(extra?.ivEndog).toBeUndefined();
    expect(extra?.ivInstruments).toBeUndefined();
  });

  it("renders v1.8.6 model controls and posts model options from the ordinary Run form", async () => {
    const spy = vi.spyOn(api, "runWorkflow").mockResolvedValue(RUN_RESPONSE);
    renderForm();
    fillForm();
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "ordinal_logit" },
    });
    expect(screen.getByLabelText("ordinal model options")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("ordinal model options"), {
      target: { value: '{"optimizer":"lbfgs","maxiter":800}' },
    });
    fireEvent.click(screen.getByRole("button", { name: /run workflow/i }));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls[0]?.[9]?.modelOptions).toEqual({
      optimizer: "lbfgs",
      maxiter: 800,
    });
  });
});

const PREVIEW: api.FilePreview = {
  fileName: "data.csv",
  sheetNames: ["Sheet1"],
  selectedSheet: "Sheet1",
  rowCount: 10,
  columnCount: 4,
  columns: [
    { name: "y", dtype: "numeric", missingRate: 0, uniqueCount: 10, suggestedRole: "y" },
    { name: "x1", dtype: "numeric", missingRate: 0, uniqueCount: 10, suggestedRole: "x" },
    { name: "id", dtype: "numeric", missingRate: 0, uniqueCount: 4, suggestedRole: "id" },
    { name: "year", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "time" },
    { name: "cohort", dtype: "numeric", missingRate: 0, uniqueCount: 3, suggestedRole: "x" },
  ],
  previewRows: [],
  suggestedY: "y",
  suggestedX: ["x1"],
  excludedColumns: [],
};

describe("RunForm DID wiring", () => {
  async function setupDID() {
    vi.spyOn(api, "previewFile").mockResolvedValue(PREVIEW);
    renderForm();
    const file = new File(["a\n1\n"], "data.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("data file"), {
      target: { files: [file] },
    });
    // wait for the preview panel (and its column list) to render
    await screen.findByLabelText("column selector");
    fireEvent.change(screen.getByLabelText("dependent variable"), {
      target: { value: "y" },
    });
    fireEvent.change(screen.getByLabelText("independent variables"), {
      target: { value: "x1, cohort" },
    });
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "did" },
    });
  }

  it("renders DID controls when model is did", async () => {
    await setupDID();
    expect(screen.getByLabelText("did-mode")).toBeInTheDocument();
    expect(screen.getByLabelText("did-entity")).toBeInTheDocument();
    expect(screen.getByLabelText("did-cohort")).toBeInTheDocument();
  });

  it("posts did_mode and excludes the DID role columns from x", async () => {
    const spy = vi.spyOn(api, "runWorkflow").mockResolvedValue(RUN_RESPONSE);
    await setupDID();
    fireEvent.change(screen.getByLabelText("did-entity"), {
      target: { value: "id" },
    });
    fireEvent.change(screen.getByLabelText("did-time"), {
      target: { value: "year" },
    });
    fireEvent.change(screen.getByLabelText("did-cohort"), {
      target: { value: "cohort" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run workflow/i }));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    const call = spy.mock.calls[0];
    // x (index 3) must drop the cohort role column, keeping only x1.
    expect(call[3]).toBe("x1");
    const extra = call[9];
    expect(extra?.didMode).toBe("cohort");
    expect(extra?.didCohortCol).toBe("cohort");
    expect(extra?.entityCol).toBe("id");
    expect(extra?.timeCol).toBe("year");
  });
});

describe("RunForm ARMA-GARCH wiring", () => {
  it("requests and displays the canonical full-data transform preflight", async () => {
    const timePreview: api.FilePreview = {
      ...PREVIEW,
      columns: [
        { name: "date", dtype: "datetime", missingRate: 0, uniqueCount: 10, suggestedRole: "time" },
        { name: "vix", dtype: "numeric", missingRate: 0.03, uniqueCount: 9, suggestedRole: "y" },
      ],
      previewRows: [{ date: "2025-01-02", vix: 14.2 }],
      suggestedY: "vix",
      suggestedX: [],
    };
    vi.spyOn(api, "previewFile").mockResolvedValue(timePreview);
    const preflight = vi.spyOn(api, "fetchArmaGarchTransformPreflight").mockResolvedValue({
      schema_version: 1,
      source_row_count: 2610,
      analysis_row_count: 2542,
      diagnostics: [],
      transform_profiles: {},
      recommendation: {
        transform_id: "log_return_pct",
        score: 5,
        reason: "Full-series profile favors changes.",
      },
      transform_confirmation_required: true,
    });
    renderForm();
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "time_series.arma_garch" },
    });
    const file = new File(["date,vix\n2025-01-02,14.2\n"], "vix.csv", {
      type: "text/csv",
    });
    fireEvent.change(screen.getByLabelText("data file"), {
      target: { files: [file] },
    });

    await waitFor(() => expect(preflight).toHaveBeenCalled());
    expect(await screen.findByText(/System suggestion: Log difference/)).toBeInTheDocument();
  });

  it("posts an explicit confirmed time-series model_options contract with no regressors", async () => {
    const timePreview: api.FilePreview = {
      ...PREVIEW,
      columns: [
        { name: "date", dtype: "datetime", missingRate: 0, uniqueCount: 10, suggestedRole: "time" },
        { name: "vix", dtype: "numeric", missingRate: 0, uniqueCount: 10, suggestedRole: "y" },
      ],
      previewRows: [{ date: "2025-01-02", vix: 14.2 }],
      suggestedY: "vix",
      suggestedX: [],
    };
    vi.spyOn(api, "previewFile").mockResolvedValue(timePreview);
    const spy = vi.spyOn(api, "runWorkflow").mockResolvedValue(RUN_RESPONSE);
    renderForm();
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "time_series.arma_garch" },
    });
    const file = new File(["date,vix\n2025-01-02,14.2\n"], "vix.csv", {
      type: "text/csv",
    });
    fireEvent.change(screen.getByLabelText("data file"), {
      target: { files: [file] },
    });
    await waitFor(() => {
      expect(screen.getByLabelText("time column")).toHaveValue("date");
      expect(screen.getByLabelText("value column")).toHaveValue("vix");
    });
    fireEvent.click(screen.getByLabelText("confirm drop missing values"));
    fireEvent.click(screen.getByLabelText(/confirm transform/i));
    fireEvent.click(screen.getByRole("button", { name: /run workflow/i }));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    const call = spy.mock.calls[0];
    expect(call[2]).toBe("vix");
    expect(call[3]).toBe("");
    expect(call[5]).toBe("time_series.arma_garch");
    expect(call[9]?.modelOptions).toMatchObject({
      dataset_ref: "upload:vix.csv",
      time_column: "date",
      value_column: "vix",
      transform: "level",
      transform_confirmed: true,
      missing_value_policy: "drop_missing_confirmed",
      selection_mode: "auto",
    });
  });
});

describe("RunForm SA (sun-abraham) wiring", () => {
  async function setupSA() {
    vi.spyOn(api, "previewFile").mockResolvedValue(PREVIEW);
    renderForm();
    const file = new File(["a\n1\n"], "data.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("data file"), {
      target: { files: [file] },
    });
    await screen.findByLabelText("column selector");
    fireEvent.change(screen.getByLabelText("dependent variable"), {
      target: { value: "y" },
    });
    fireEvent.change(screen.getByLabelText("independent variables"), {
      target: { value: "x1, cohort" },
    });
    fireEvent.change(screen.getByLabelText("model type"), {
      target: { value: "sa_did" },
    });
  }

  it("renders DID + CS controls when model is sa_did", async () => {
    await setupSA();
    // DID role selects (entity/time/cohort) reused for SA
    expect(screen.getByLabelText("did-entity")).toBeInTheDocument();
    expect(screen.getByLabelText("did-time")).toBeInTheDocument();
    expect(screen.getByLabelText("did-cohort")).toBeInTheDocument();
    // CS cohort/cluster/honest-DID knobs reused for SA
    expect(screen.getByLabelText("cs-cluster-var")).toBeInTheDocument();
    expect(screen.getByLabelText("cs-honest-did")).toBeInTheDocument();
  });

  it("posts model_type=sa_did with cohort/entity/time roles excluded from x", async () => {
    const spy = vi.spyOn(api, "runWorkflow").mockResolvedValue(RUN_RESPONSE);
    await setupSA();
    fireEvent.change(screen.getByLabelText("did-entity"), {
      target: { value: "id" },
    });
    fireEvent.change(screen.getByLabelText("did-time"), {
      target: { value: "year" },
    });
    fireEvent.change(screen.getByLabelText("did-cohort"), {
      target: { value: "cohort" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run workflow/i }));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    const call = spy.mock.calls[0];
    // model_type argument (index 5)
    expect(call[5]).toBe("sa_did");
    // x (index 3) drops the cohort role column, keeping only x1.
    expect(call[3]).toBe("x1");
    const extra = call[9];
    expect(extra?.didCohortCol).toBe("cohort");
    expect(extra?.entityCol).toBe("id");
    expect(extra?.timeCol).toBe("year");
    // CS-channel params (honest_did etc.) posted for SA too
    expect(extra?.honestDid).toBe(false);
  });
});
