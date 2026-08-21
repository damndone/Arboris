import "@testing-library/jest-dom/vitest";
import { createHash } from "node:crypto";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { canonicalRequestSchemaDigest } from "./dataOperationManifest";
import { DataOperationsSection } from "./detail/sections/DataOperationsSection";

const requestSchema = {
  type: "object",
  additionalProperties: false,
  required: ["source_run_id", "source_node_id", "source_artifact_id", "label"],
  properties: {
    source_run_id: { type: "string" },
    source_node_id: { type: "string" },
    source_artifact_id: { type: "string" },
    label: { type: "string", minLength: 1 },
  },
} as const;

const manifest = {
  schema_version: "data-operation-manifest.v1",
  operations: [{
    operation_id: "data.safe_subset",
    operation_version: "v1",
    effect_level: "mutation",
    risk_level: "mutating",
    confirmation_policy: "required",
    executor_key: "executor:data.safe_subset",
    reconciler_key: "reconciler:data.safe_subset",
    validator_key: "validator:data.safe_subset",
    request_schema: requestSchema,
    input_ports: [{ name: "source", port_type: "dataset", dataset_kind: "source_data", cardinality: "one", required: true, identity_fields: ["source_run_id", "source_node_id", "source_artifact_id"] }],
    output_ports: [
      { name: "derived", port_type: "dataset", dataset_kind: "derived_data", cardinality: "one", required: true, identity_fields: [] },
      { name: "operation_record", port_type: "operation_record", dataset_kind: null, cardinality: "one", required: true, identity_fields: ["record_id"] },
      { name: "evidence", port_type: "evidence", dataset_kind: null, cardinality: "one", required: true, identity_fields: ["record_id", "method"] },
    ],
    metadata_effect: "preserve",
    metadata_risk: "loss is blocked",
    output_kind: "derived_data",
    request_schema_digest: canonicalRequestSchemaDigest(requestSchema),
    preview_ref: "/data-operations/safe-subset/preview",
    confirm_ref: "/data-operations/safe-subset/confirm",
    confirm_requires: ["preview_fingerprint"],
    replay: { recipe_kind: "typed_operation_request", request_identity_fields: ["operation_id"], source_fingerprint_field: "source_sha256", request_digest_field: "request_sha256" },
    clarification_requirements: ["Provide the typed operation values."],
  }],
} as const;

const sourceIdentity = {
  source_run_id: "run-1",
  source_node_id: "node-1",
  source_artifact_id: "artifact-source",
};

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

function digest(value: unknown): string {
  return createHash("sha256").update(canonicalJson(value)).digest("hex");
}

function responsePreview(request: Record<string, unknown>, fingerprint: string) {
  const { source_run_id: _run, source_node_id: _node, source_artifact_id: _artifact, ...options } = request;
  return {
    status: "ready",
    fingerprint,
    request_sha256: digest(request),
    options_sha256: digest(options),
    catalog_digest: "c".repeat(64),
    evidence_method: "data.safe_subset",
    source_run_id: sourceIdentity.source_run_id,
    source_node_id: sourceIdentity.source_node_id,
    source_artifact_id: sourceIdentity.source_artifact_id,
  };
}

function completedPayload(request: Record<string, unknown>) {
  const { preview_fingerprint: _previewFingerprint, ...requestWithoutFingerprint } = request;
  const effect = {
    execution_key: "exec-1",
    child_node_id: "child-1",
    artifact_id: "artifact-child",
  };
  const operation = {
    record_id: "record-1",
    operation_id: "data.safe_subset",
    operation_version: "v1",
    status: "completed",
    target: { run_id: sourceIdentity.source_run_id, node_ref: sourceIdentity.source_node_id, artifact_id: sourceIdentity.source_artifact_id },
    execution: {
      execution_key: effect.execution_key,
      bindings: { artifact_id: effect.artifact_id, child_node_id: effect.child_node_id },
    },
    outputs: {
      ports: {
        derived: { ...effect },
        operation_record: { record_id: "record-1", operation_id: "data.safe_subset", operation_version: "v1" },
        evidence: { method: "data.safe_subset", record_id: "record-1", operation_id: "data.safe_subset", execution_key: effect.execution_key, child_node_id: effect.child_node_id, artifact_id: effect.artifact_id },
      },
      consumer_slots: {
        "data.agent": { record_id: "record-1", port: "derived" },
        "data.notebook": { record_id: "record-1", port: "derived" },
        "data.report": { record_id: "record-1", port: "evidence" },
      },
      catalog_digest: "c".repeat(64),
    },
  };
  return {
    status: "completed",
    preview: responsePreview(requestWithoutFingerprint, "fp-1"),
    effect,
    operation,
  };
}

describe("v1.8.9 integrated lineage/data acceptance", () => {
  it("requires a ready preview before confirmation and preserves source identity", async () => {
    const preview = vi.fn().mockImplementation(async (_projectRoot, _descriptor, request) => (
      new Response(JSON.stringify({ preview: { ...responsePreview(request, "fp-1"), row_count_after: 2 } }), { status: 200 })
    ));
    const confirm = vi.fn().mockImplementation(async (_projectRoot, _descriptor, request) => (
      new Response(JSON.stringify(completedPayload(request)), { status: 200 })
    ));
    render(<DataOperationsSection
      manifest={manifest}
      projectRoot="/tmp/project"
      {...sourceIdentity}
      preview={preview}
      confirm={confirm}
    />);

    fireEvent.change(screen.getByLabelText("Data operation"), { target: { value: "data.safe_subset" } });
    fireEvent.change(screen.getByLabelText("label"), { target: { value: "approved subset" } });
    fireEvent.click(screen.getByTestId("data-operation-preview"));
    await screen.findByTestId("data-operation-preview-ready");

    expect(confirm).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("data-operation-confirm"));
    await screen.findByTestId("data-operation-complete");
    expect(confirm).toHaveBeenCalledWith(
      "/tmp/project",
      expect.anything(),
      expect.objectContaining({ source_artifact_id: "artifact-source", preview_fingerprint: "fp-1" }),
    );
  });
});
