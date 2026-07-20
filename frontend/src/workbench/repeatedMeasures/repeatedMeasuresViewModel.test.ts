import { describe, expect, it } from "vitest";

import {
  clone,
  completePublicModelResult,
  failedPublicModelResult,
  unbalancedPublicModelResult,
} from "./__fixtures__/publicModelResults";
import { buildRepeatedMeasuresViewModel } from "./repeatedMeasuresViewModel";

describe("buildRepeatedMeasuresViewModel", () => {
  it("accepts only a complete trusted projection with a canonical trajectory", () => {
    const viewModel = buildRepeatedMeasuresViewModel(completePublicModelResult());
    expect(viewModel).toMatchObject({
      kind: "complete",
      trajectory: {
        chart_type: "lmm_group_trajectory",
        time: [0, 1],
      },
      primaryCoefficient: {
        result_id: "group_time_interaction",
        estimate: 0.8,
      },
    });
    expect(viewModel).not.toHaveProperty("recovery");
    expect(viewModel).not.toHaveProperty("canExecute");
  });

  it("accepts a non-trajectory complete result only for the exact unbalanced-time diagnostic", () => {
    expect(buildRepeatedMeasuresViewModel(unbalancedPublicModelResult())).toMatchObject({
      kind: "complete",
      trajectory: null,
      diagnostics: [{ code: "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME" }],
    });
  });

  it("allows independent complete warnings alongside one exact unbalanced-time warning", () => {
    const result = clone(unbalancedPublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    payload.diagnostics = [
      ...(payload.diagnostics as Array<Record<string, unknown>>),
      {
        code: "LMM_RANDOM_EFFECTS_SINGULAR",
        severity: "warning",
        status: "complete",
        evidence: { covariance: 0 },
        action_candidate: null,
      },
    ];
    payload.warnings = [
      "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME",
      "LMM_RANDOM_EFFECTS_SINGULAR",
    ];

    expect(buildRepeatedMeasuresViewModel(result)).toMatchObject({
      kind: "complete",
      trajectory: null,
      diagnostics: [
        { code: "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME" },
        { code: "LMM_RANDOM_EFFECTS_SINGULAR" },
      ],
    });
  });

  it("accepts a failed terminal result without any trajectory or recovery action", () => {
    expect(buildRepeatedMeasuresViewModel(failedPublicModelResult())).toEqual({
      kind: "failed",
      terminalDiagnostics: ["LMM_CONVERGENCE_FAILED"],
      trajectory: null,
    });
  });

  it("accepts the other closed terminal code only at its failed state", () => {
    const result = clone(failedPublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    const diagnostics = payload.diagnostics as Array<Record<string, unknown>>;
    diagnostics[0].code = "LMM_UNEXPECTED_FIT_EXCEPTION";
    diagnostics[0].evidence = {};
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({
      kind: "failed",
      terminalDiagnostics: ["LMM_UNEXPECTED_FIT_EXCEPTION"],
      trajectory: null,
    });
  });

  it("accepts multiple unique closed terminal diagnostics without exposing partial statistics", () => {
    const result = clone(failedPublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    payload.diagnostics = [
      ...(payload.diagnostics as Array<Record<string, unknown>>),
      {
        code: "LMM_UNEXPECTED_FIT_EXCEPTION",
        severity: "error",
        status: "failed",
        evidence: {},
        action_candidate: null,
      },
    ];
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({
      kind: "failed",
      terminalDiagnostics: ["LMM_CONVERGENCE_FAILED", "LMM_UNEXPECTED_FIT_EXCEPTION"],
      trajectory: null,
    });
  });

  it.each([
    ["convergence with the wrong evidence", "LMM_CONVERGENCE_FAILED", {}],
    ["unexpected exception with leaked evidence", "LMM_UNEXPECTED_FIT_EXCEPTION", { detail: "leak" }],
  ])("rejects a terminal result for %s", (_label, code, evidence) => {
    const result = clone(failedPublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    payload.diagnostics = [{ code, severity: "error", status: "failed", evidence, action_candidate: null }];
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
  });

  it("rejects a failed result with partial random-effect statistics", () => {
    const result = clone(failedPublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    payload.random_effects = { intercept_variance: 0.1 };
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
  });

  it("rejects a raw packet envelope rather than treating it as a server projection", () => {
    expect(buildRepeatedMeasuresViewModel({
      contract: "linear_mixed_effects.result",
      contract_version: "1.0",
      producer_version: "linear_mixed_effects@1.0",
      payload: (completePublicModelResult().payload),
    })).toEqual({ kind: "rejected" });
  });

  it("rejects an outer accessor without evaluating it", () => {
    const result = clone(completePublicModelResult());
    let accessorRead = false;
    Object.defineProperty(result, "artifact_id", {
      enumerable: true,
      get() {
        accessorRead = true;
        throw new Error("must not be evaluated");
      },
    });

    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
    expect(accessorRead).toBe(false);
  });

  it("rejects a nested evidence accessor without evaluating it", () => {
    const result = clone(completePublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    const diagnostic = (payload.diagnostics as Array<Record<string, unknown>>)[0]!;
    let accessorRead = false;
    Object.defineProperty(diagnostic, "evidence", {
      enumerable: true,
      get() {
        accessorRead = true;
        throw new Error("must not be evaluated");
      },
    });

    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
    expect(accessorRead).toBe(false);
  });

  it("safely rejects a Proxy that refuses descriptor inspection", () => {
    const result = new Proxy(completePublicModelResult(), {
      getOwnPropertyDescriptor() {
        throw new Error("untrusted proxy");
      },
    });

    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
  });

  it.each([
    ["missing artifact id", (value: Record<string, unknown>) => delete value.artifact_id],
    ["bad artifact digest", (value: Record<string, unknown>) => { value.artifact_sha256 = "UPPER"; }],
    ["wrong compatibility marker", (value: Record<string, unknown>) => { value.legacy_compatibility = "raw"; }],
    ["wrong model type", (value: Record<string, unknown>) => { value.model_type = "ols"; }],
  ])("rejects a projection with %s", (_label, mutate) => {
    const result = clone(completePublicModelResult());
    mutate(result);
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
  });

  it("rejects an absent nested primary coefficient instead of using a top-level fallback", () => {
    const result = clone(completePublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    payload.coefficients = {};
    payload.result_id = "group_time_interaction";
    payload.estimate = 999;
    payload.inference_method = "forged";
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
  });

  it.each([
    ["unknown diagnostic", "LMM_FUTURE_DIAGNOSTIC", "warning", "complete"],
    ["wrong terminal state", "LMM_CONVERGENCE_FAILED", "warning", "complete"],
    ["wrong unbalanced state", "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME", "error", "failed"],
  ])("rejects a %s", (_label, code, severity, status) => {
    const result = clone(completePublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    payload.diagnostics = [{ code, severity, status, evidence: {}, action_candidate: null }];
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
  });

  it("rejects malformed unbalanced evidence", () => {
    const result = clone(unbalancedPublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    const diagnostics = payload.diagnostics as Array<Record<string, unknown>>;
    diagnostics[0].evidence = { reason: "unbalanced_observed_time_support" };
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
  });

  it.each([
    ["a label longer than 128 characters", (evidence: Record<string, unknown>) => {
      (evidence.group_support as Array<Record<string, unknown>>)[0].label = "x".repeat(129);
    }],
    ["non-lexical group support", (evidence: Record<string, unknown>) => {
      evidence.group_support = [...(evidence.group_support as Array<Record<string, unknown>>) ].reverse();
    }],
    ["identical support digests", (evidence: Record<string, unknown>) => {
      const support = evidence.group_support as Array<Record<string, unknown>>;
      support[1].observed_time_sha256 = support[0].observed_time_sha256;
    }],
  ])("rejects unbalanced evidence with %s", (_label, mutate) => {
    const result = clone(unbalancedPublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    const diagnostics = payload.diagnostics as Array<Record<string, unknown>>;
    mutate(diagnostics[0].evidence as Record<string, unknown>);
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
  });

  it.each([
    ["a non-increasing time vector", (context: Record<string, unknown>) => { context.time = [0, 0]; }],
    ["duplicate groups", (context: Record<string, unknown>) => {
      const groups = context.groups as Array<Record<string, unknown>>;
      groups[1].label = groups[0].label;
    }],
    ["only one group", (context: Record<string, unknown>) => { context.groups = (context.groups as unknown[]).slice(0, 1); }],
    ["a group label not matching the canonical pair", (context: Record<string, unknown>) => {
      (context.groups as Array<Record<string, unknown>>)[1].label = "forged";
    }],
  ])("rejects a trajectory with %s", (_label, mutate) => {
    const result = clone(completePublicModelResult());
    const payload = result.payload as Record<string, unknown>;
    mutate(payload.figure_context as Record<string, unknown>);
    expect(buildRepeatedMeasuresViewModel(result)).toEqual({ kind: "rejected" });
  });
});
