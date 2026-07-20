export type JsonRecord = Record<string, unknown>;

const digest = "a".repeat(64);

export function completePublicModelResult(): JsonRecord {
  return {
    artifact_id: "artifact-lmm-1",
    artifact_path: "artifacts/model_results/linear_mixed_effects_1.result.json",
    artifact_sha256: digest,
    model_id: "linear_mixed_effects_1",
    model_type: "linear_mixed_effects",
    source_contract: "linear_mixed_effects.result",
    source_contract_version: "1.0",
    source_producer_version: "linear_mixed_effects@1.0",
    source_packet_digest: "b".repeat(64),
    legacy_compatibility: "projected_from_versioned_packet",
    payload: {
      schema_version: 1,
      contract_version: "1.0",
      estimator_version: "statsmodels_mixedlm_v1",
      model_id: "linear_mixed_effects_1",
      model_type: "linear_mixed_effects",
      converged: true,
      status: "complete",
      reference_group: "control",
      comparison_group: "treated",
      primary_target_id: "group_time_interaction",
      coefficients: {
        group_time_interaction: {
          result_id: "group_time_interaction",
          label: "treated × time",
          estimate: 0.8,
          std_error: 0.2,
          p_value: 0.001,
          confidence_interval: [0.4, 1.2],
          confidence_level: 0.95,
          inference_method: "asymptotic_wald_z_v1",
          source_id: "model_results.linear_mixed_effects_1.coefficients.group_time_interaction",
        },
      },
      diagnostics: [{
        code: "LMM_RANDOM_SLOPE_NEAR_ZERO",
        severity: "warning",
        status: "complete",
        evidence: { slope_variance: 0.00001 },
        action_candidate: {
          action_id: "lmm.simplify_random_effects_v1",
          operation_id: "model.rerun",
          patch: { model_options: { random_slope: false } },
          required_confirmation: true,
        },
      }],
      figure_context: {
        chart_type: "lmm_group_trajectory",
        time: [0, 1],
        groups: [
          { label: "control", observed_mean: [10, 9], fitted_mean: [10, 9.1] },
          { label: "treated", observed_mean: [10, 8], fitted_mean: [10, 8.2] },
        ],
      },
      warnings: ["LMM_RANDOM_SLOPE_NEAR_ZERO"],
    },
  };
}

export function unbalancedPublicModelResult(): JsonRecord {
  const result = completePublicModelResult();
  const payload = result.payload as JsonRecord;
  payload.figure_context = null;
  payload.diagnostics = [{
    code: "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME",
    severity: "warning",
    status: "complete",
    evidence: {
      reason: "unbalanced_observed_time_support",
      first_nonshared_time: 2,
      group_support: [
        { label: "control", observed_time_sha256: "c".repeat(64) },
        { label: "treated", observed_time_sha256: "d".repeat(64) },
      ],
    },
    action_candidate: null,
  }];
  payload.warnings = ["LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME"];
  return result;
}

export function failedPublicModelResult(): JsonRecord {
  const result = completePublicModelResult();
  const payload = result.payload as JsonRecord;
  payload.status = "failed";
  payload.converged = false;
  payload.coefficients = {};
  payload.random_effects = {};
  payload.figure_context = null;
  payload.diagnostics = [{
    code: "LMM_CONVERGENCE_FAILED",
    severity: "error",
    status: "failed",
    evidence: { optimizer: "lbfgs" },
    action_candidate: null,
  }];
  payload.warnings = [];
  return result;
}

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
