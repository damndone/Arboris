import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ArmaGarchOperationSection } from "./ArmaGarchOperationSection";
import { RerunContext } from "../RerunContext";
import type { RerunContextValue } from "../RerunContext";
import type { HeadSetNode } from "../../api/graphViewTypes";
import type {
  NodeOperationContextV1,
  ResolveNodeOperationContextResult,
} from "../../api/nodeOperationContext";

const { resolvedContextMock } = vi.hoisted(() => ({
  resolvedContextMock: {
    current: null as ResolveNodeOperationContextResult | null,
  },
}));

vi.mock("../NodeOperationContextProvider", () => ({
  useResolvedNodeOperationContext: () => resolvedContextMock.current,
}));

function armaGarchNode(): HeadSetNode {
  return {
    id: "M1",
    nodeKey: "M1",
    opNodeId: "model:arma_garch_1",
    raw: {},
    stage: "model",
    kind: "model",
    title: "ARMA(1,1)-GARCH(1,1)",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    nodeHash: "M1",
    producingStage: "model",
    casRef: null,
    runs: ["run_a"],
    editable: true,
    opType: "time_series.arma_garch",
    schemaId: "time_series.arma_garch@1.0",
    editableSchemaSource: "run_inputs",
    editableSchema: [
      { kind: "select", key: "model_type", label: "Model", options: [], value: "time_series.arma_garch" },
      {
        kind: "object",
        key: "model_options",
        label: "Options",
        value: {
          dataset_ref: "dataset:vix:1",
          time_column: "observation_date",
          value_column: "vixcls",
          time_index_semantics: "business_or_trading_observations",
          transform: "log_return_pct",
          transform_confirmed: true,
          analysis_goal: "balanced",
          selection_mode: "manual",
          arma: { p: 1, q: 1, constant_mode: "exclude" },
          variance: { model: "garch", garch_p: 1, garch_q: 1 },
          estimation_strategy: "sequential",
          innovation_distribution: "normal",
          validation: { validation_n: 250, refit_every: 1 },
          random_seed: 0,
        },
      },
    ],
  } as unknown as HeadSetNode;
}

function resolvedOk() {
  resolvedContextMock.current = {
    ok: true,
    context: { context_fingerprint: "nocv1:test" } as NodeOperationContextV1,
  };
}

test("forks a model_options child rerun when a field changes", async () => {
  resolvedOk();
  const submitRerun = vi.fn().mockResolvedValue({ focus: {} });
  const value: RerunContextValue = { submitRerun, activeRunId: "run_a" };
  render(
    <RerunContext.Provider value={value}>
      <ArmaGarchOperationSection node={armaGarchNode()} />
    </RerunContext.Provider>,
  );

  fireEvent.change(screen.getByLabelText("innovation distribution"), {
    target: { value: "student_t" },
  });
  fireEvent.click(screen.getByTestId("arma-garch-op-submit"));

  await waitFor(() => expect(submitRerun).toHaveBeenCalledTimes(1));
  const arg = submitRerun.mock.calls[0][0];
  expect(arg.opOverrides.model_options.innovation_distribution).toBe("student_t");
  expect(arg.opOverrides.model_options.dataset_ref).toBe("dataset:vix:1");
  expect(arg.context.context_fingerprint).toBe("nocv1:test");
});

test("renders nothing without a resolved rerun context", () => {
  resolvedContextMock.current = null;
  const { container } = render(
    <RerunContext.Provider value={{ submitRerun: vi.fn(), activeRunId: "run_a" }}>
      <ArmaGarchOperationSection node={armaGarchNode()} />
    </RerunContext.Provider>,
  );
  expect(container.querySelector('[data-testid="arma-garch-operation-section"]')).toBeNull();
});
