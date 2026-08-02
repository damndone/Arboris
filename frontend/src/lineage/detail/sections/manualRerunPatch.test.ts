import { describe, expect, it } from "vitest";
import {
  buildManualRerunPatch,
  buildManualRerunPatchId,
  normalizeForCompare,
} from "./manualRerunPatch";

describe("manualRerunPatch", () => {
  it("builds a single-node patch with old and new values", () => {
    const patch = buildManualRerunPatch({
      patchId: "patch_1",
      sourceContextFingerprint: "nocv1:source",
      editableSchemaVersion: "schema:v1",
      target: {
        owner_run_id: "run_source",
        op_node_id: "model:ols_1",
        node_hash: "hash_source",
      },
      initialValues: { covariance: "clustered" },
      currentValues: { covariance: "robust" },
    });

    expect(patch?.changes).toEqual([
      {
        field_id: "covariance",
        old_value: "clustered",
        new_value: "robust",
      },
    ]);
  });

  it("returns null for no-op normalized changes", () => {
    expect(
      buildManualRerunPatch({
        patchId: "patch_1",
        sourceContextFingerprint: "nocv1:source",
        editableSchemaVersion: "schema:v1",
        target: {
          owner_run_id: "run_source",
          op_node_id: "model:ols_1",
          node_hash: "hash_source",
        },
        initialValues: { covariance: "clustered" },
        currentValues: { covariance: "clustered" },
      }),
    ).toBeNull();
  });

  it("normalizes object keys deterministically", () => {
    expect(normalizeForCompare({ b: 2, a: 1 })).toBe(
      normalizeForCompare({ a: 1, b: 2 }),
    );
  });

  it("changes the id when the same field is changed to a different value", () => {
    const from = { model_type: "logit" };
    expect(
      buildManualRerunPatchId("nocv1:source", from, { model_type: "probit" }),
    ).not.toBe(
      buildManualRerunPatchId("nocv1:source", from, { model_type: "glm:binomial" }),
    );
  });
});
