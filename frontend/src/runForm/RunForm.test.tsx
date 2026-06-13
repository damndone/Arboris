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
