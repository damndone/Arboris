import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NotebookSurface } from "./NotebookSurface";
import type { NotebookReadyView } from "./contracts";
import {
  canonicalEtsResult,
  canonicalOptionExecution,
  canonicalOptionRevision,
} from "./fixtures/canonicalMocks";
import { provisionalContextSlice } from "./fixtures/provisionalContextSlice";

function ready(overrides: Partial<NotebookReadyView["notebook"]> = {}): NotebookReadyView {
  return {
    status: "ready",
    notebook: {
      notebook_id: "nb_0001",
      run_family_id: "run-family:11111111-1111-4111-8111-111111111111",
      narrative: [
        {
          entry_id: "nar_1",
          kind: "user",
          text: "Is the ARMA residual structure at lag 12 seasonality?",
          occurred_at: "2026-07-22T16:19:00+00:00",
        },
        {
          entry_id: "nar_2",
          kind: "agent",
          text: "The residual ACF still shows structure at lag 12.",
          occurred_at: "2026-07-22T16:20:00+00:00",
        },
      ],
      options: [canonicalOptionRevision()],
      contextSlice: provisionalContextSlice(),
      confirmation: null,
      execution: null,
      result: null,
      selection: null,
      ...overrides,
    },
  };
}

describe("NotebookSurface — six states, none of them lying", () => {
  it("loading: says the context is being compiled and shows no options", () => {
    render(<NotebookSurface view={{ status: "loading" }} />);
    expect(screen.getByTestId("notebook-loading")).toHaveTextContent(
      "Compiling the bounded notebook context…",
    );
    expect(screen.queryByTestId("notebook-option-list")).toBeNull();
  });

  it("error: shows the error code and message, and no success wording", () => {
    render(
      <NotebookSurface
        view={{
          status: "error",
          error: {
            code: "TOOL_OUTPUT_BUDGET_EXCEEDED",
            message: "artifacts_index projection exceeded the 8192-character tool budget",
          },
        }}
      />,
    );
    const error = screen.getByTestId("notebook-error");
    expect(error).toHaveTextContent("TOOL_OUTPUT_BUDGET_EXCEEDED");
    expect(error).toHaveTextContent(
      "artifacts_index projection exceeded the 8192-character tool budget",
    );
    expect(screen.queryByTestId("notebook-success")).toBeNull();
  });

  it("empty: says no options were proposed rather than rendering an empty list", () => {
    render(<NotebookSurface view={ready({ options: [] })} />);
    expect(screen.getByTestId("notebook-empty")).toHaveTextContent(
      "No analysis options for this context yet",
    );
  });

  it("pending: an executing option shows as running, never as a result", () => {
    render(
      <NotebookSurface
        view={ready({
          options: [{ ...canonicalOptionRevision(), lifecycle_status: "executing" }],
          execution: { ...canonicalOptionExecution(), run_id: "run-9ab" },
        })}
      />,
    );
    expect(screen.getByTestId("notebook-pending")).toHaveTextContent(
      "Executing opt_7f3a1c rev 2 as run-9ab — no result yet",
    );
    expect(screen.queryByTestId("notebook-success")).toBeNull();
  });

  it("confirmation: shows the plan diff and required artifacts before anything runs", () => {
    render(
      <NotebookSurface
        view={ready({
          confirmation: {
            option: canonicalOptionRevision(),
            execution: canonicalOptionExecution(),
            plan_diff: [
              { field: "model_type", from: "time_series.arma_garch", to: "time_series.ets" },
              { field: "damped_trend", from: null, to: "true" },
            ],
          },
        })}
      />,
    );

    const confirmation = screen.getByTestId("notebook-confirmation");
    expect(confirmation).toHaveTextContent(
      "model_type: time_series.arma_garch → time_series.ets",
    );
    expect(confirmation).toHaveTextContent("damped_trend: (unset) → true");
    expect(confirmation).toHaveTextContent("ets_1 · model_result · required");
    expect(screen.getByTestId("confirmation-pins")).toHaveTextContent(
      "opt_7f3a1c rev 2 · prop_51de90 rev 1",
    );
    expect(screen.queryByTestId("notebook-success")).toBeNull();
  });

  it("success: renders the executed result exactly as the ETS packet states it", () => {
    render(
      <NotebookSurface
        view={ready({
          options: [{ ...canonicalOptionRevision(), lifecycle_status: "executed" }],
          execution: { ...canonicalOptionExecution(), run_id: "run-9ab" },
          result: canonicalEtsResult(),
        })}
      />,
    );

    const success = screen.getByTestId("notebook-success");
    expect(success).toHaveTextContent("ETS(A,Ad,N)");
    expect(success).toHaveTextContent("VIXCLS");
    expect(success).toHaveTextContent("n_obs 2610");
    expect(success).toHaveTextContent("excluded 3 (missing_endog 3)");
    expect(success).toHaveTextContent("AIC 12043.72");
    expect(success).toHaveTextContent("BIC 12078.11");
    expect(success).toHaveTextContent("converged");
    expect(success).toHaveTextContent("run-9ab");
  });
  it("a run that finished but missed a required artifact is not shown as a result", () => {
    render(
      <NotebookSurface
        view={ready({
          options: [{ ...canonicalOptionRevision(), lifecycle_status: "selected" }],
          execution: { ...canonicalOptionExecution(), run_id: "run-9ab" },
          result: canonicalEtsResult(),
          outcome: {
            execution_status: "succeeded",
            validation_status: "failed",
            validation_profile: "artifact-identity-type-count/v1",
            checked_dimensions: ["artifact_id", "artifact_type", "count", "step"],
            not_evaluated_dimensions: ["payload_schema"],
            observed: [
              {
                artifact_id: "ets_1",
                observed_count: 0,
                satisfied: false,
                issue_code: "ARTIFACT_MISSING",
              },
            ],
          },
        })}
      />,
    );

    expect(screen.queryByTestId("notebook-success")).toBeNull();
    expect(screen.getByTestId("notebook-contract-failure")).toHaveTextContent(
      "execution succeeded · output contract failed — this is not a result",
    );
    expect(screen.getByTestId("notebook-contract-failure")).toHaveTextContent(
      "ets_1 · observed 0 · ARTIFACT_MISSING",
    );
  });
});

describe("NotebookSurface — generation limits and the visible slice", () => {
  it("renders at most three option cards and says so when given more", () => {
    const base = canonicalOptionRevision();
    render(
      <NotebookSurface
        view={ready({
          options: [
            { ...base, option_id: "opt_a", rank: 1 },
            { ...base, option_id: "opt_b", rank: 2 },
            { ...base, option_id: "opt_c", rank: 3 },
            { ...base, option_id: "opt_d", rank: 4 },
          ],
        })}
      />,
    );
    expect(screen.getAllByTestId(/^option-card-/)).toHaveLength(3);
    expect(screen.getByTestId("notebook-option-overflow")).toHaveTextContent(
      "1 option beyond the 3-option limit is not shown",
    );
  });

  it("always keeps the context slice visible next to the options", () => {
    render(<NotebookSurface view={ready()} />);
    expect(screen.getByTestId("context-omission-artifact_summaries")).toHaveTextContent(
      "5 of 59 included",
    );
  });

  it("offers the selected-text actions when text is selected", () => {
    const onSaveNote = vi.fn();
    render(
      <NotebookSurface
        view={ready({
          selection: {
            text: "structure at lag 12",
            source_label: "agent message nar_2",
            source_ref: "narrative:nar_2",
          },
        })}
        onSelectionSaveNote={onSaveNote}
      />,
    );
    expect(screen.getByTestId("notebook-selection-actions")).toHaveTextContent(
      "structure at lag 12",
    );
  });
});
