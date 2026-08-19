import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DataOperationsSection } from "./detail/sections/DataOperationsSection";

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
    request_schema: {
      type: "object",
      additionalProperties: false,
      required: ["source_run_id", "source_node_id", "source_artifact_id", "label"],
      properties: {
        source_run_id: { type: "string" },
        source_node_id: { type: "string" },
        source_artifact_id: { type: "string" },
        label: { type: "string", minLength: 1 },
      },
    },
    input_ports: [{ name: "source", port_type: "dataset", dataset_kind: "source_data", cardinality: "one", required: true, identity_fields: ["source_run_id", "source_node_id", "source_artifact_id"] }],
    output_ports: [{ name: "derived", port_type: "dataset", dataset_kind: "derived_data", cardinality: "one", required: true, identity_fields: [] }],
    metadata_effect: "preserve",
    metadata_risk: "loss is blocked",
    output_kind: "derived_data",
    request_schema_digest: "a".repeat(64),
    preview_ref: "/data-operations/safe-subset/preview",
    confirm_ref: "/data-operations/safe-subset/confirm",
    confirm_requires: ["preview_fingerprint"],
    replay: { recipe_kind: "typed_operation_request", request_identity_fields: ["operation_id"], source_fingerprint_field: "source_sha256", request_digest_field: "request_sha256" },
    clarification_requirements: ["Provide the typed operation values."],
  }],
} as const;

describe("v1.8.9 integrated lineage/data acceptance", () => {
  it("requires a ready preview before confirmation and preserves source identity", async () => {
    const preview = vi.fn().mockResolvedValue({ preview: { status: "ready", fingerprint: "fp-1", row_count_after: 2 } });
    const confirm = vi.fn().mockResolvedValue({ status: "completed", artifact_id: "artifact-child" });
    render(<DataOperationsSection
      manifest={manifest}
      projectRoot="/tmp/project"
      source_run_id="run-1"
      source_node_id="node-1"
      source_artifact_id="artifact-source"
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

