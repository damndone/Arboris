import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  DataOperationManifestError,
  parseDataOperationManifest,
} from "../../dataOperationManifest";
import { DataOperationsSection } from "./DataOperationsSection";

const { previewMock, confirmMock } = vi.hoisted(() => ({
  previewMock: vi.fn(),
  confirmMock: vi.fn(),
}));

const SOURCE_IDENTITY = {
  source_run_id: "run-1",
  source_node_id: "node-1",
  source_artifact_id: "artifact-1",
};

function descriptor(overrides: Record<string, unknown> = {}) {
  return {
    operation_id: "data.example",
    operation_version: "v1",
    effect_level: "mutation",
    risk_level: "mutating",
    confirmation_policy: "required",
    executor_key: "executor:data.example",
    reconciler_key: "reconciler:data.example",
    validator_key: "validator:data.example",
    request_schema: {
      type: "object",
      additionalProperties: false,
      required: ["source_run_id", "source_node_id", "source_artifact_id", "label"],
      properties: {
        source_run_id: { type: "string", minLength: 1 },
        source_node_id: { type: "string", minLength: 1 },
        source_artifact_id: { type: "string", minLength: 1 },
        label: { type: "string", minLength: 1 },
        mode: { type: "string", enum: ["fast", "safe"] },
        limit: { type: "number", minimum: 1 },
        enabled: { type: "boolean" },
        columns: { type: "array", items: { type: "string" } },
        options: {
          type: "object",
          additionalProperties: false,
          properties: {
            strategy: { type: "string", enum: ["keep", "drop"] },
            retries: { type: "number", minimum: 0 },
          },
          required: ["strategy"],
        },
      },
    },
    input_ports: [
      {
        name: "source",
        port_type: "dataset",
        dataset_kind: "source_data",
        cardinality: "one",
        required: true,
        identity_fields: ["source_run_id", "source_node_id", "source_artifact_id"],
      },
    ],
    output_ports: [
      {
        name: "derived",
        port_type: "dataset",
        dataset_kind: "derived_data",
        cardinality: "one",
        required: true,
        identity_fields: [],
      },
    ],
    metadata_effect: "preserve source metadata",
    metadata_risk: "metadata loss is blocked",
    output_kind: "derived_data",
    request_schema_digest: "a".repeat(64),
    preview_ref: "/data-operations/example/preview",
    confirm_ref: "/data-operations/example/confirm",
    confirm_requires: ["preview_fingerprint"],
    replay: {
      recipe_kind: "typed_operation_request",
      request_identity_fields: [
        "operation_id",
        "operation_version",
        "source_run_id",
        "source_node_id",
        "source_artifact_id",
      ],
      source_fingerprint_field: "source_sha256",
      request_digest_field: "request_sha256",
    },
    clarification_requirements: ["Provide the typed operation values."],
    ...overrides,
  };
}

function manifest(
  operationOverrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    schema_version: "data-operation-manifest.v1",
    operations: [descriptor(operationOverrides)],
  };
}

function sectionProps(manifestValue: unknown = manifest()) {
  return {
    ...SOURCE_IDENTITY,
    projectRoot: "/tmp/project",
    manifest: manifestValue,
    preview: previewMock,
    confirm: confirmMock,
  };
}

describe("DataOperationManifest parser", () => {
  it("parses the complete descriptor without dropping safety metadata", () => {
    const parsed = parseDataOperationManifest(manifest());

    expect(parsed.schema_version).toBe("data-operation-manifest.v1");
    expect(parsed.operations[0]).toMatchObject({
      operation_id: "data.example",
      preview_ref: "/data-operations/example/preview",
      confirm_ref: "/data-operations/example/confirm",
      confirm_requires: ["preview_fingerprint"],
    });
    expect(parsed.operations[0].request_schema.properties.options.type).toBe("object");
  });

  it("rejects an unknown request field type with a typed error", () => {
    const invalid = manifest({
      request_schema: {
        ...descriptor().request_schema,
        properties: {
          ...(descriptor().request_schema as { properties: Record<string, unknown> }).properties,
          label: { type: "date" },
        },
      },
    });

    expect(() => parseDataOperationManifest(invalid)).toThrow(DataOperationManifestError);
    try {
      parseDataOperationManifest(invalid);
    } catch (error) {
      expect(error).toMatchObject({ code: "REQUEST_SCHEMA_FIELD_TYPE_UNSUPPORTED" });
    }
  });

  it("rejects a descriptor that omits server safety metadata", () => {
    const invalid = JSON.parse(JSON.stringify(manifest())) as Record<string, unknown>;
    delete (invalid.operations as Array<Record<string, unknown>>)[0].replay;

    expect(() => parseDataOperationManifest(invalid)).toThrow(DataOperationManifestError);
    try {
      parseDataOperationManifest(invalid);
    } catch (error) {
      expect(error).toMatchObject({ code: "DESCRIPTOR_FIELD_MISSING" });
    }
  });

  it("preserves the server-owned descriptor order", () => {
    const second = descriptor({ operation_id: "data.example.second" });
    const parsed = parseDataOperationManifest({
      schema_version: "data-operation-manifest.v1",
      operations: [descriptor(), second],
    });

    expect(parsed.operations.map((operation) => operation.operation_id)).toEqual([
      "data.example",
      "data.example.second",
    ]);
  });

  it("renders a typed unavailable boundary instead of an executable editor", () => {
    render(
      <DataOperationsSection
        {...sectionProps(
          manifest({
            availability: {
              status: "unavailable",
              reason_code: "optional_dependency",
              message: "pyreadstat is not installed",
            },
          }),
        )}
      />,
    );

    expect(screen.getByTestId("data-operation-unavailable")).toHaveTextContent(
      "optional_dependency",
    );
    expect(screen.queryByLabelText("Data operation")).toBeNull();
  });
});

describe("DataOperationsSection", () => {
  beforeEach(() => {
    previewMock.mockReset();
    confirmMock.mockReset();
    confirmMock.mockResolvedValue({ status: "completed" });
  });

  it("displays a typed error when the manifest omits source identity", () => {
    const invalid = JSON.parse(JSON.stringify(manifest())) as {
      operations: Array<{ request_schema: { properties: Record<string, unknown> } }>;
    };
    delete invalid.operations[0].request_schema.properties.source_artifact_id;

    render(<DataOperationsSection {...sectionProps(invalid)} />);

    expect(screen.getByTestId("data-operations-error")).toHaveTextContent(
      "SOURCE_IDENTITY_MISSING",
    );
    expect(screen.queryByLabelText("Data operation")).toBeNull();
  });

  it("renders an operation selector and schema-driven controls after selection", () => {
    render(<DataOperationsSection {...sectionProps()} />);

    fireEvent.change(screen.getByLabelText("Data operation"), {
      target: { value: "data.example" },
    });

    expect(screen.getByLabelText("label")).toBeInTheDocument();
    expect(screen.getByLabelText("mode")).toBeInTheDocument();
    expect(screen.getByLabelText("limit")).toBeInTheDocument();
    expect(screen.getByLabelText("enabled")).toBeInTheDocument();
    expect(screen.getByLabelText("columns")).toBeInTheDocument();
    expect(screen.getByLabelText("options")).toBeInTheDocument();
  });

  it("only confirms after a ready preview fingerprint and uses descriptor refs", async () => {
    previewMock.mockResolvedValue({
      preview: { status: "ready", fingerprint: "preview-fp-1", row_count_after: 2 },
    });

    render(<DataOperationsSection {...sectionProps()} />);
    fireEvent.change(screen.getByLabelText("Data operation"), {
      target: { value: "data.example" },
    });
    fireEvent.change(screen.getByLabelText("label"), {
      target: { value: "approved" },
    });

    expect(screen.queryByTestId("data-operation-confirm")).toBeNull();
    expect(confirmMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("data-operation-preview"));
    await screen.findByTestId("data-operation-preview-ready");

    expect(previewMock).toHaveBeenCalledWith(
      "/tmp/project",
      expect.objectContaining({
        operation_id: "data.example",
        preview_ref: "/data-operations/example/preview",
      }),
      {
        ...SOURCE_IDENTITY,
        label: "approved",
      },
    );
    expect(screen.getByTestId("data-operation-confirm")).toBeEnabled();

    fireEvent.click(screen.getByTestId("data-operation-confirm"));
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(confirmMock).toHaveBeenCalledWith(
      "/tmp/project",
      expect.objectContaining({
        operation_id: "data.example",
        confirm_ref: "/data-operations/example/confirm",
        confirm_requires: ["preview_fingerprint"],
      }),
      {
        ...SOURCE_IDENTITY,
        label: "approved",
        preview_fingerprint: "preview-fp-1",
      },
    );
    expect(screen.getByTestId("data-operation-complete")).toHaveTextContent(
      "completed",
    );
  });
});
