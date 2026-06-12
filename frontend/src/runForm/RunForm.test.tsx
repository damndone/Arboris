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
