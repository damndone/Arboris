import { describe, expect, it } from "vitest";

import {
  parseArtifactContract,
  parseEtsResult,
  parseNotebookOptionRevision,
  parseOptionExecution,
} from "./contracts";
import {
  canonicalEtsResult,
  canonicalOptionExecution,
  canonicalOptionRevision,
  readCanonicalFixture,
} from "./fixtures/canonicalMocks";

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

  it("reads the ETS result without deriving anything from it", () => {
    const result = canonicalEtsResult();
    expect(result.specification.canonical).toBe("ETS(A,Ad,N)");
    expect(result.aic).toBe(12043.72);
    expect(result.n_excluded).toBe(3);
    expect(result.exclusion_reasons).toEqual({ missing_endog: 3 });
    expect(result.convergence_code).toBe("converged");
  });
});

describe("contracts — a packet that does not match the lock is rejected, not coerced", () => {
  it("rejects an unknown contract_version on the option revision", () => {
    const raw = { ...readCanonicalFixture("notebook_option_revision"), contract_version: "2.0" };
    expect(() => parseNotebookOptionRevision(raw)).toThrow(
      "NotebookOptionRevision contract_version must be 1.0, got 2.0",
    );
  });

  it("rejects a lifecycle status outside the locked vocabulary", () => {
    const raw = { ...readCanonicalFixture("notebook_option_revision"), lifecycle_status: "done" };
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
