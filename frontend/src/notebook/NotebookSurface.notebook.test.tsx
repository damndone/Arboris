import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotebookSurface } from "./NotebookSurface";
import { rootToSlug } from "../workbench/projectSlug";
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
  afterEach(() => {
    vi.useRealTimers();
  });

  it("loading: says the context is being compiled and shows no options", () => {
    render(<NotebookSurface view={{ status: "loading" }} />);
    expect(screen.getByTestId("notebook-loading")).toHaveTextContent(
      "Compiling the bounded notebook context…",
    );
    expect(screen.queryByTestId("notebook-option-list")).toBeNull();
  });

  it("loading (planning phase): names the slow agent step so it does not read as a hang", () => {
    vi.useFakeTimers();
    const onCancelPlanning = vi.fn();
    render(
      <NotebookSurface
        view={{ status: "loading", phase: "planning" }}
        onCancelPlanning={onCancelPlanning}
      />,
    );
    expect(screen.getByTestId("notebook-loading")).toHaveTextContent(
      "Planning analysis options with the agent…",
    );
    expect(screen.getByTestId("notebook-planning-progress")).toHaveTextContent(
      "Validating evidence-bound options",
    );
    expect(screen.getByTestId("notebook-planning-progress")).toHaveTextContent(
      "How the plan is being formed",
    );
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.getByTestId("notebook-planning-elapsed")).toHaveTextContent(
      "Elapsed 5s",
    );
    fireEvent.click(screen.getByTestId("notebook-cancel-planning"));
    expect(onCancelPlanning).toHaveBeenCalledOnce();
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

  it("materialization failure exposes an explicit recovery action without success state", () => {
    const onReplan = vi.fn();
    render(
      <NotebookSurface
        view={{
          status: "error",
          error: {
            code: "OPTION_MATERIALIZATION_FAILED",
            message: "genesis materialization rejected an incomplete model",
          },
        }}
        onReplan={onReplan}
      />,
    );

    expect(screen.getByTestId("notebook-replan-options")).toHaveTextContent(
      "Replan with current evidence",
    );
    fireEvent.click(screen.getByTestId("notebook-replan-options"));
    expect(onReplan).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("notebook-success")).toBeNull();
  });

  it("planning timeout remains explicitly retryable", () => {
    const onReplan = vi.fn();
    render(
      <NotebookSurface
        view={{
          status: "error",
          error: {
            code: "NOTEBOOK_PLANNING_TIMEOUT",
            message: "Notebook planning provider exceeded 60s",
          },
        }}
        onReplan={onReplan}
      />,
    );

    fireEvent.click(screen.getByTestId("notebook-replan-options"));
    expect(onReplan).toHaveBeenCalledOnce();
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
    const selected = {
      ...canonicalOptionRevision(),
      lifecycle_status: "selected" as const,
      materializable: true,
    };
    render(
      <NotebookSurface
        view={ready({
          options: [selected],
          confirmation: {
            option: selected,
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
    expect(screen.getByTestId("confirmation-confirm")).toHaveTextContent("Prepare Draft");
    expect(screen.queryByTestId("notebook-success")).toBeNull();
    const card = screen.getByTestId(`option-card-${selected.option_id}`);
    expect(card.nextElementSibling).toBe(screen.getByTestId("notebook-confirmation-slot"));
    expect(screen.getByTestId("notebook-confirmation-slot")).toHaveFocus();
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
    expect(success).toHaveTextContent("excluded 0 ()");
    expect(success).toHaveTextContent("AIC 12043.72");
    expect(success).toHaveTextContent("BIC 12078.9226330019");
    expect(success).toHaveTextContent("converged");
    expect(success).toHaveTextContent("run-9ab");
  });

  it("renders a bounded model-neutral execution summary for non-ETS results", () => {
    const option = { ...canonicalOptionRevision(), lifecycle_status: "executed" as const };
    render(
      <NotebookSurface
        view={ready({
          options: [option],
          executionResults: {
            [option.option_id]: {
              option_id: option.option_id,
              option_revision: option.option_revision,
              run_id: "run-arma-1",
              execution_status: "succeeded",
              committed: true,
              artifact_validation: {
                contract_profile: "artifact-identity-type-count/v1",
                validation_status: "passed",
                checked_dimensions: ["artifact_id", "artifact_type", "count", "step"],
                not_evaluated_dimensions: ["payload_schema"],
                issues: Array.from({ length: 10 }, (_, index) => ({
                  code: "ARTIFACT_UNDECLARED",
                  severity: "informational",
                  artifact_id: `extra_${index}`,
                  detail: "not named by the contract",
                  observed_count: 1,
                })),
              },
            },
          },
        })}
      />,
    );

    const summary = screen.getByTestId("notebook-execution-summary");
    expect(summary).toHaveTextContent("run-arma-1");
    expect(summary).toHaveTextContent("output contract passed");
    expect(summary).toHaveTextContent("2 additional artifact notes omitted");
    expect(summary).not.toHaveTextContent("extra_9");
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

describe("NotebookSurface — persisted option batches and the visible slice", () => {
  it("shows every persisted option while grouping options by generation batch", () => {
    const base = canonicalOptionRevision();
    render(
      <NotebookSurface
        view={ready({
          options: [
            { ...base, option_id: "opt_a", rank: 1, batch_id: "batch_a" },
            { ...base, option_id: "opt_b", rank: 2, batch_id: "batch_a" },
            { ...base, option_id: "opt_c", rank: 1, batch_id: "batch_b" },
            { ...base, option_id: "opt_d", rank: 2, batch_id: "batch_b" },
          ],
        })}
      />,
    );
    expect(screen.getAllByTestId(/^option-card-/)).toHaveLength(4);
    expect(screen.getAllByTestId(/^notebook-option-batch-/)).toHaveLength(2);
    expect(screen.queryByTestId("notebook-option-overflow")).toBeNull();
  });

  it("collapses an older stale-only batch while keeping the latest actionable batch open", () => {
    const base = canonicalOptionRevision();
    render(
      <NotebookSurface
        view={ready({
          options: [
            {
              ...base,
              option_id: "opt_old",
              batch_id: "batch_old",
              freshness_status: "stale",
            },
            {
              ...base,
              option_id: "opt_current",
              batch_id: "batch_current",
              freshness_status: "fresh",
            },
          ],
        })}
      />,
    );

    expect(screen.getByTestId("notebook-option-batch-batch_old")).not.toHaveAttribute("open");
    expect(screen.getByTestId("notebook-option-batch-batch_old")).toHaveTextContent(
      "Previous option batch",
    );
    expect(screen.getByTestId("notebook-option-batch-batch_current")).toHaveAttribute("open");
    expect(screen.getByTestId("notebook-option-batch-batch_current")).toHaveTextContent(
      "Current option batch",
    );
  });

  it("orders batches by generation time and labels only the newest batch as current", () => {
    const base = canonicalOptionRevision();
    render(
      <NotebookSurface
        view={ready({
          options: [
            {
              ...base,
              option_id: "opt_old",
              batch_id: "batch_old",
              created_at: "2026-07-22T10:00:00+00:00",
              freshness_status: "stale",
            },
            {
              ...base,
              option_id: "opt_new",
              batch_id: "batch_new",
              created_at: "2026-07-22T12:00:00+00:00",
              freshness_status: "fresh",
            },
            {
              ...base,
              option_id: "opt_middle",
              batch_id: "batch_middle",
              created_at: "2026-07-22T11:00:00+00:00",
              freshness_status: "stale",
            },
          ],
        })}
      />,
    );

    const batches = screen.getAllByTestId(/^notebook-option-batch-/);
    expect(batches.map((batch) => batch.dataset.testid)).toEqual([
      "notebook-option-batch-batch_old",
      "notebook-option-batch-batch_middle",
      "notebook-option-batch-batch_new",
    ]);
    expect(screen.getAllByText("Current option batch")).toHaveLength(1);
    expect(screen.getByTestId("notebook-option-batch-batch_old")).toHaveTextContent(
      "Previous option batch",
    );
    expect(screen.getByTestId("notebook-option-batch-batch_middle")).toHaveTextContent(
      "Previous option batch",
    );
    expect(screen.getByTestId("notebook-option-batch-batch_new")).toHaveTextContent(
      "Current option batch",
    );
  });

  it("offers an explicit replan action when persisted options need recovery", () => {
    const onReplan = vi.fn();
    render(<NotebookSurface view={ready()} onReplan={onReplan} />);

    fireEvent.click(screen.getByTestId("notebook-replan-options"));

    expect(onReplan).toHaveBeenCalledOnce();
  });

  it("always keeps the context slice visible next to the options", () => {
    render(<NotebookSurface view={ready()} />);
    expect(screen.getByTestId("context-omission-artifact_summaries")).toHaveTextContent(
      "5 of 59 included",
    );
  });

  it("opens a materialized Draft inside the project Graph with Notebook context", () => {
    render(
      <NotebookSurface
        projectRoot="/tmp/project"
        view={ready({
          materialization: {
            contract_version: "1.0",
            materialization_id: "mat_1",
            option_id: "opt_7f3a1c",
            option_revision: 2,
            proposal_id: "prop_51de90",
            proposal_revision: 1,
            freshness_dependency_fingerprint: "fresh1:x",
            generation_context_id: "ctx_1",
            draft_id: "draft_genesis",
            draft_hash: "sha256:draft",
            draft_execution_mode: "genesis",
            source_run_id: null,
            source_model_node_id: null,
            source_op_node_id: null,
            source_node_hash: null,
            source_forest_node_key: null,
            source_context_fingerprint: null,
            dataset_upload_sha256: "a".repeat(64),
            run_family_id: "family_1",
          },
        })}
      />,
    );

    const href = screen.getByRole("link", { name: "Open Draft in Graph" }).getAttribute("href");
    expect(href).toContain(`/p/${rootToSlug("/tmp/project")}/graph`);
    const url = new URL(href!, "http://localhost");
    expect(url.searchParams.get("view")).toBe("graph");
    expect(url.searchParams.get("notebook")).toBe("nb_0001");
    expect(url.searchParams.get("active")).toBe("draft:draft_genesis:model_1");
    expect(url.searchParams.get("focus")).toBe("draft:draft_genesis:model_1");
  });

  it("uses a rerun-child Draft node key without inventing a genesis model node", () => {
    render(
      <NotebookSurface
        projectRoot="/tmp/project"
        view={ready({
          materialization: {
            contract_version: "1.0",
            materialization_id: "mat_2",
            option_id: "opt_7f3a1c",
            option_revision: 2,
            proposal_id: "prop_51de90",
            proposal_revision: 1,
            freshness_dependency_fingerprint: "fresh1:x",
            generation_context_id: "ctx_1",
            draft_id: "draft_rerun",
            draft_hash: "sha256:draft",
            draft_execution_mode: "rerun_child",
            source_run_id: "run_1",
            source_model_node_id: "model:1",
            source_op_node_id: "model:1",
            source_node_hash: "hash_1",
            source_forest_node_key: "hash_1::model:1",
            source_context_fingerprint: "nocv1:source",
            dataset_upload_sha256: null,
            run_family_id: "family_1",
          },
        })}
      />,
    );

    const href = screen.getByRole("link", { name: "Open Draft in Graph" }).getAttribute("href");
    const url = new URL(href!, "http://localhost");
    expect(url.searchParams.get("active")).toBe("draft:draft_rerun");
    expect(url.searchParams.get("focus")).toBe("draft:draft_rerun");
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

  it("captures a browser selection from a narrative entry with a typed source ref", () => {
    const onTextSelection = vi.fn();
    const getSelection = vi.spyOn(window, "getSelection").mockReturnValue({
      toString: () => "structure at lag 12",
      anchorNode: document.createTextNode("structure at lag 12"),
    } as unknown as Selection);

    render(<NotebookSurface view={ready()} onTextSelection={onTextSelection} />);
    const narrative = screen.getByTestId("narrative-nar_2");
    narrative.appendChild(document.createTextNode("structure at lag 12"));
    fireEvent.mouseUp(narrative);

    expect(onTextSelection).toHaveBeenCalledWith(
      {
        text: "structure at lag 12",
        source_label: "agent message nar_2",
        source_ref: "narrative:nar_2",
      },
      { top: 8, left: 0 },
    );
    getSelection.mockRestore();
  });
});
