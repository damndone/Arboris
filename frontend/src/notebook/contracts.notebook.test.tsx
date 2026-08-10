import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  parseArtifactContract,
  parseEtsResult,
  parseNotebookExecutionResult,
  parseNotebookOptionRevision,
  parseOptionMaterialization,
  parseOptionExecution,
  parseRecommendationDecision,
} from "./contracts";
import {
  canonicalEtsResult,
  canonicalOptionExecution,
  canonicalOptionRevision,
  readCanonicalFixture,
} from "./fixtures/canonicalMocks";

const V11_FIXTURE_DIR = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../tests/fixtures/contracts/v181",
);

function readV11Fixture(name: string): Record<string, unknown> {
  return JSON.parse(readFileSync(resolve(V11_FIXTURE_DIR, `${name}.json`), "utf8")) as Record<
    string,
    unknown
  >;
}

describe("contracts — the canonical v1.8.1 mocks parse into the locked shape", () => {
  it("keeps the two hashes as two separate fields", () => {
    const option = canonicalOptionRevision();
    expect(option.generation_context_hash).toBe(
      "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    );
    expect(option.freshness_dependency_fingerprint).toBe(
      "fresh1:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    );
    expect(option.generation_context_hash).not.toBe(option.freshness_dependency_fingerprint);
  });

  it("reads the artifact contract's checked and not-evaluated dimensions", () => {
    const contract = canonicalOptionRevision().artifact_contract;
    expect(contract.checked_dimensions).toEqual([
      "artifact_id",
      "artifact_type",
      "count",
      "step",
    ]);
    expect(contract.not_evaluated_dimensions).toEqual(["payload_schema"]);
    expect(contract.expected.map((item) => item.artifact_id)).toEqual([
      "ets_1",
      "ts_residual_acf",
    ]);
    expect(contract.expected[0].required).toBe(true);
    expect(contract.expected[1].required).toBe(false);
  });

  it("reads the execution five-tuple pins with a not-yet-assigned run_id", () => {
    const execution = canonicalOptionExecution();
    expect(execution.option_revision).toBe(2);
    expect(execution.proposal_revision).toBe(1);
    expect(execution.run_id).toBeNull();
  });

  it("reads a bounded multi-branch workflow receipt without inventing an active head", () => {
    const result = parseNotebookExecutionResult({
      option_id: "opt_workflow",
      option_revision: 1,
      run_id: null,
      execution_status: "succeeded",
      committed: true,
      artifact_validation: {
        contract_profile: "artifact-identity-type-count/v1",
        validation_status: "passed",
        checked_dimensions: ["artifact_id"],
        not_evaluated_dimensions: ["payload_schema"],
        issues: [],
      },
      workflow_execution: {
        workflow_id: "workflow_1",
        plan_fingerprint: "plan_1",
        status: "completed",
        branch_runs: [
          {
            branch_id: "baseline",
            run_id: "run_baseline",
            artifact_ids: ["model_result"],
          },
        ],
        post_estimation_artifact_ids: ["joint_f"],
      },
    });

    expect(result.run_id).toBeNull();
    expect(result.workflow_execution?.branch_runs).toEqual([
      {
        branch_id: "baseline",
        run_id: "run_baseline",
        artifact_ids: ["model_result"],
      },
    ]);
    expect(result.workflow_execution?.failed_steps).toEqual([]);
  });

  it("reads bounded workflow failure codes without accepting provider error prose", () => {
    const result = parseNotebookExecutionResult({
      option_id: "opt_failed_workflow",
      option_revision: 1,
      run_id: null,
      execution_status: "failed",
      committed: false,
      artifact_validation: {
        contract_profile: "artifact-identity-type-count/v1",
        validation_status: "failed",
        checked_dimensions: ["artifact_id"],
        not_evaluated_dimensions: ["payload_schema"],
        issues: [],
      },
      workflow_execution: {
        workflow_id: "workflow_failed",
        plan_fingerprint: "plan_failed",
        status: "failed",
        branch_runs: [],
        post_estimation_artifact_ids: [],
        failed_steps: [
          {
            step_id: "hurdle_nb",
            operation_id: "glm.hurdle_negative_binomial",
            status: "failed",
            error_code: "GLM_NONCONVERGENCE",
          },
        ],
      },
    });

    expect(result.workflow_execution?.failed_steps).toEqual([
      {
        step_id: "hurdle_nb",
        operation_id: "glm.hurdle_negative_binomial",
        status: "failed",
        error_code: "GLM_NONCONVERGENCE",
      },
    ]);
  });

  it("reads the server-owned artifact validation scope without treating ambient records as contract issues", () => {
    const result = parseNotebookExecutionResult({
      option_id: "opt_projection",
      option_revision: 1,
      run_id: "run_projection",
      execution_status: "succeeded",
      committed: true,
      artifact_validation: {
        contract_profile: "artifact-identity-type-count/v1",
        validation_status: "passed",
        checked_dimensions: ["artifact_id", "artifact_type", "count", "step"],
        not_evaluated_dimensions: ["payload_schema"],
        issues: [],
      },
      artifact_validation_scope: {
        mode: "server_owned_contract_projection",
        ambient_artifact_ids: ["cleaned_dataset", "ols_1"],
        ambient_artifact_count: 2,
      },
    });

    expect(result.artifact_validation_scope).toEqual({
      mode: "server_owned_contract_projection",
      ambient_artifact_ids: ["cleaned_dataset", "ols_1"],
      ambient_artifact_count: 2,
    });
  });

  it("projects a v1.0 option as legacy-unverified and not materializable", () => {
    const option = canonicalOptionRevision();
    expect(option.contract_version).toBe("1.0");
    expect(option.lifecycle_projection).toBe("legacy_unverified");
    expect(option.materializable).toBe(false);
  });

  it("defaults unversioned v1.0 optional option fields", () => {
    const raw = { ...readCanonicalFixture("notebook_option_revision") };
    delete raw.contract_version;
    delete raw.rationale;
    delete raw.assumptions;
    delete raw.supersedes_option_revision;

    const option = parseNotebookOptionRevision(raw);

    expect(option.contract_version).toBe("1.0");
    expect(option.rationale).toBe("");
    expect(option.assumptions).toEqual([]);
    expect(option.supersedes_option_revision).toBeNull();
  });

  it("reads the ETS result without deriving anything from it", () => {
    const result = canonicalEtsResult();
    expect(result.specification.canonical).toBe("ETS(A,Ad,N)");
    expect(result.aic).toBe(12043.72);
    expect(result.n_excluded).toBe(0);
    expect(result.exclusion_reasons).toEqual({});
    expect(result.convergence_code).toBe("converged");
  });
});

describe("contracts — a packet that does not match the lock is rejected, not coerced", () => {
  it("rejects an unknown contract_version on the option revision", () => {
    const raw = { ...readCanonicalFixture("notebook_option_revision"), contract_version: "2.0" };
    expect(() => parseNotebookOptionRevision(raw)).toThrow(
      "NotebookOptionRevision contract_version must be 1.0 or 1.1, got 2.0",
    );
  });

  it("rejects a lifecycle status outside the locked vocabulary", () => {
    const raw = { ...readCanonicalFixture("notebook_option_revision"), lifecycle_status: "done" };
    expect(() => parseNotebookOptionRevision(raw)).toThrow("lifecycle_status");
  });

  it("rejects materialized lifecycle on a v1.0 option", () => {
    const raw = { ...readCanonicalFixture("notebook_option_revision"), lifecycle_status: "materialized" };
    expect(() => parseNotebookOptionRevision(raw)).toThrow("lifecycle_status");
  });

  it("rejects an artifact expectation that declares an unsupported schema_ref", () => {
    const contract = readCanonicalFixture("notebook_option_revision")
      .artifact_contract as Record<string, unknown>;
    const expected = (contract.expected as Record<string, unknown>[]).map((item) => ({
      ...item,
      schema_ref: "ets_result.schema.json",
    }));
    expect(() => parseArtifactContract({ ...contract, expected })).toThrow(
      "ARTIFACT_SCHEMA_CONTRACT_UNSUPPORTED",
    );
  });

  it("rejects an execution packet missing a freshness fingerprint", () => {
    const raw = { ...readCanonicalFixture("option_execution") };
    delete raw.freshness_dependency_fingerprint;
    expect(() => parseOptionExecution(raw)).toThrow("freshness_dependency_fingerprint");
  });

  it("rejects an ETS packet whose model_type is not the ETS pack", () => {
    const raw = { ...readCanonicalFixture("ets_result"), model_type: "time_series.arma_garch" };
    expect(() => parseEtsResult(raw)).toThrow("model_type");
  });
});

describe("contracts — v1.1 evidence, decision, and materialization records", () => {
  it("reads a v1.3 option revision with server-applied memory-default provenance", () => {
    const option = parseNotebookOptionRevision({
      ...readV11Fixture("notebook_option_revision_v11"),
      contract_version: "1.3",
      memory_default_sources: [
        {
          memory_id: "memory-ols-covariance",
          revision: 2,
          target_ref: "model.genesis.ols.covariance.robust",
        },
      ],
    });

    if (option.contract_version !== "1.3") throw new Error("expected a v1.3 option fixture");
    expect(option.memory_default_sources).toEqual([
      {
        memory_id: "memory-ols-covariance",
        revision: 2,
        target_ref: "model.genesis.ols.covariance.robust",
      },
    ]);
  });

  it("reads a v1.4 option revision with server-owned target display metadata", () => {
    const option = parseNotebookOptionRevision({
      ...readV11Fixture("notebook_option_revision_v11"),
      contract_version: "1.4",
      memory_default_sources: [
        {
          memory_id: "memory-panel-covariance",
          revision: 4,
          target_ref: "model.genesis.panel_ols.covariance.clustered",
          target_label: "Covariance estimator",
          method_risk: "high",
          restore_value: null,
        },
      ],
    });

    if (option.contract_version !== "1.4") throw new Error("expected a v1.4 option fixture");
    expect(option.memory_default_sources).toEqual([
      {
        memory_id: "memory-panel-covariance",
        revision: 4,
        target_ref: "model.genesis.panel_ols.covariance.clustered",
        target_label: "Covariance estimator",
        method_risk: "high",
        restore_value: null,
      },
    ]);
  });

  it("rejects a v1.3 option without memory-default provenance", () => {
    const raw = {
      ...readV11Fixture("notebook_option_revision_v11"),
      contract_version: "1.3",
    };
    expect(() => parseNotebookOptionRevision(raw)).toThrow("memory_default_sources");
  });

  it("reads a v1.1 option revision with evidence and a materialized lifecycle", () => {
    const option = parseNotebookOptionRevision(readV11Fixture("notebook_option_revision_v11"));
    if (option.contract_version !== "1.1") throw new Error("expected a v1.1 option fixture");
    expect(option.contract_version).toBe("1.1");
    expect(option.lifecycle_status).toBe("materialized");
    expect(option.materializable).toBe(true);
    expect(option.evidence_refs[0]).toMatchObject({ evidence_id: "ev_ets_001" });
  });

  it("reads a valid recommendation decision and materialization", () => {
    const decision = parseRecommendationDecision(readV11Fixture("recommendation_decision_v1"));
    const materialization = parseOptionMaterialization(
      readV11Fixture("option_materialization_v1"),
    );
    expect(decision.recommended_option_id).toBe("opt_7f3a1c");
    expect(materialization.draft_execution_mode).toBe("rerun_child");
    expect(materialization.dataset_upload_sha256).toBeNull();
  });

  it("reads a valid genesis materialization", () => {
    const materialization = parseOptionMaterialization(
      readV11Fixture("option_materialization_genesis_v1"),
    );
    expect(materialization.draft_execution_mode).toBe("genesis");
    expect(materialization.source_run_id).toBeNull();
  });

  it("reads a v1.1 execution with all materialization pins", () => {
    const execution = parseOptionExecution(readV11Fixture("option_execution_v11"));
    if (execution.contract_version !== "1.1") throw new Error("expected a v1.1 execution fixture");
    expect(execution.contract_version).toBe("1.1");
    expect(execution.materialization_id).toBe("mat_6bca12");
    expect(execution.run_id).toBe("run_003");
  });

  it("rejects v1.0 option packets that carry v1.1-only fields", () => {
    const raw = { ...readCanonicalFixture("notebook_option_revision"), evidence_refs: [] };
    expect(() => parseNotebookOptionRevision(raw)).toThrow("unknown field");
  });

  it("rejects an invalid recommendation outcome selection", () => {
    const raw = { ...readV11Fixture("recommendation_decision_v1"), recommended_option_id: null };
    expect(() => parseRecommendationDecision(raw)).toThrow("recommended_option_id");
  });

  it("rejects a recommended id outside the candidate set", () => {
    const raw = {
      ...readV11Fixture("recommendation_decision_v1"),
      recommended_option_id: "opt_not_a_candidate",
    };
    expect(() => parseRecommendationDecision(raw)).toThrow("recommended_option_id");
  });

  it("rejects an invalid rerun-child materialization XOR", () => {
    const raw = {
      ...readV11Fixture("option_materialization_v1"),
      dataset_upload_sha256: "sha256:uploaded-dataset",
    };
    expect(() => parseOptionMaterialization(raw)).toThrow("rerun_child");
  });

  it("rejects a genesis materialization with a source pin", () => {
    const raw = {
      ...readV11Fixture("option_materialization_genesis_v1"),
      source_run_id: "run_002",
    };
    expect(() => parseOptionMaterialization(raw)).toThrow("genesis");
  });

  it("rejects a v1.1 execution without every required pin", () => {
    const raw = { ...readV11Fixture("option_execution_v11"), materialization_id: null };
    expect(() => parseOptionExecution(raw)).toThrow("materialization_id");
  });

  it("rejects a v1.0 execution that carries v1.1-only fields", () => {
    const raw = { ...readCanonicalFixture("option_execution"), materialization_id: "mat_6bca12" };
    expect(() => parseOptionExecution(raw)).toThrow("unknown field");
  });

  it("fails closed on unknown fields", () => {
    const raw = { ...readV11Fixture("option_execution_v11"), unversioned_extra: true };
    expect(() => parseOptionExecution(raw)).toThrow("unknown field");
  });

  it("requires every v1.1 option field and its explicit version", () => {
    for (const field of [
      "contract_version",
      "evidence_refs",
      "comparative_claims",
      "recommendation_decision_id",
      "recommendation_status",
    ]) {
      const raw = { ...readV11Fixture("notebook_option_revision_v11") };
      delete raw[field];
      expect(() => parseNotebookOptionRevision(raw)).toThrow();
    }
  });

  it("rejects zero and negative contract revision fields", () => {
    const cases = [
      ["notebook_option_revision_v11", parseNotebookOptionRevision, "option_revision"],
      ["notebook_option_revision_v11", parseNotebookOptionRevision, "typed_proposal_revision"],
      ["notebook_option_revision_v11", parseNotebookOptionRevision, "rank"],
      ["option_materialization_v1", parseOptionMaterialization, "option_revision"],
      ["option_materialization_v1", parseOptionMaterialization, "proposal_revision"],
      ["option_execution_v11", parseOptionExecution, "option_revision"],
      ["option_execution_v11", parseOptionExecution, "proposal_revision"],
    ] as const;
    for (const [fixture, parser, field] of cases) {
      for (const value of [0, -1]) {
        const raw = { ...readV11Fixture(fixture), [field]: value };
        expect(() => parser(raw)).toThrow(field);
      }
    }
  });

  it("rejects empty optional run and materialization pins", () => {
    const legacyExecution = { ...readCanonicalFixture("option_execution"), run_id: "" };
    const rerun = { ...readV11Fixture("option_materialization_v1"), source_run_id: "" };
    const genesis = {
      ...readV11Fixture("option_materialization_genesis_v1"),
      dataset_upload_sha256: "",
    };

    expect(() => parseOptionExecution(legacyExecution)).toThrow("run_id");
    expect(() => parseOptionMaterialization(rerun)).toThrow("source_run_id");
    expect(() => parseOptionMaterialization(genesis)).toThrow("dataset_upload_sha256");
  });

  it("rejects unknown versions for each new packet parser", () => {
    const cases = [
      ["notebook_option_revision_v11", parseNotebookOptionRevision],
      ["recommendation_decision_v1", parseRecommendationDecision],
      ["option_materialization_v1", parseOptionMaterialization],
      ["option_execution_v11", parseOptionExecution],
    ] as const;
    for (const [fixture, parser] of cases) {
      expect(() => parser({ ...readV11Fixture(fixture), contract_version: "2.0" })).toThrow(
        "contract_version",
      );
    }
  });
});
