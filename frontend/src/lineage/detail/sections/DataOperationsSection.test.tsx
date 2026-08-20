import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  canonicalRequestSchemaDigest,
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

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    return `{${Object.keys(value as Record<string, unknown>)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson((value as Record<string, unknown>)[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

async function requestDigest(request: Record<string, unknown>): Promise<string> {
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(canonicalJson(request)),
  );
  return Array.from(new Uint8Array(bytes), (item) => item.toString(16).padStart(2, "0")).join("");
}

async function optionsDigest(request: Record<string, unknown>): Promise<string> {
  const {
    source_run_id: _run,
    source_node_id: _node,
    source_artifact_id: _artifact,
    ...options
  } = request;
  return requestDigest(options);
}

function rawTransport(value: unknown) {
  return { __rawTransport: value };
}

async function testResponse(
  value: unknown,
  request: Record<string, unknown>,
  phase: "preview" | "confirm",
): Promise<Response> {
  if (value instanceof Response) return value;
  if (typeof value === "object" && value !== null && "__rawTransport" in value) {
    return (value as { __rawTransport: Response }).__rawTransport;
  }
  let body: Record<string, unknown>;
  let status = 200;
  if (typeof value === "object" && value !== null && typeof (value as { json?: unknown }).json === "function") {
    const responseLike = value as { json: () => Promise<unknown>; status?: number };
    body = (await responseLike.json()) as Record<string, unknown>;
    status = responseLike.status ?? 200;
  } else {
    body = value as Record<string, unknown>;
  }
  const preview = body.preview;
  if (phase === "preview" && typeof preview === "object" && preview !== null) {
    body.preview = {
      ...(preview as Record<string, unknown>),
      request_sha256: await requestDigest(request),
      options_sha256: await optionsDigest(request),
      catalog_digest: "c".repeat(64),
      evidence_method: "data.example",
    };
  }
  if (phase === "confirm" && typeof preview === "object" && preview !== null) {
    const { preview_fingerprint: _previewFingerprint, ...requestWithoutFingerprint } = request;
    body.preview = {
      ...(preview as Record<string, unknown>),
      request_sha256: await requestDigest(requestWithoutFingerprint),
      options_sha256: await optionsDigest(requestWithoutFingerprint),
      catalog_digest: "c".repeat(64),
      evidence_method: "data.example",
    };
  }
  return new Response(JSON.stringify(body), { status });
}

function completedResponse(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    status: 200,
    json: async () => ({
      status: "completed",
      preview: {
        status: "ready",
        fingerprint: "preview-fp-default",
        catalog_digest: "c".repeat(64),
        source_run_id: SOURCE_IDENTITY.source_run_id,
        source_node_id: SOURCE_IDENTITY.source_node_id,
        source_artifact_id: SOURCE_IDENTITY.source_artifact_id,
      },
      effect: {
        execution_key: "exec-1",
        child_node_id: "child-1",
        artifact_id: "artifact-2",
        metadata_artifact_id: "metadata-2",
        recipe_artifact_id: "recipe-2",
        group_manifest_id: "group-2",
      },
      operation: {
        record_id: "record-1",
        operation_id: "data.example",
        operation_version: "v1",
        status: "completed",
        target: {
          run_id: SOURCE_IDENTITY.source_run_id,
          node_ref: SOURCE_IDENTITY.source_node_id,
          artifact_id: SOURCE_IDENTITY.source_artifact_id,
        },
        execution: {
          execution_key: "exec-1",
          bindings: {
            artifact_id: "artifact-2",
            child_node_id: "child-1",
            metadata_artifact_id: "metadata-2",
            recipe_artifact_id: "recipe-2",
            group_manifest_id: "group-2",
          },
        },
        outputs: {
          ports: {
            derived: {
              execution_key: "exec-1",
              artifact_id: "artifact-2",
              metadata_artifact_id: "metadata-2",
              recipe_artifact_id: "recipe-2",
              group_manifest_id: "group-2",
              child_node_id: "child-1",
            },
            operation_record: {
              record_id: "record-1",
              operation_id: "data.example",
              operation_version: "v1",
            },
            evidence: {
              method: "data.example",
              record_id: "record-1",
              operation_id: "data.example",
              execution_key: "exec-1",
              artifact_id: "artifact-2",
              metadata_artifact_id: "metadata-2",
              recipe_artifact_id: "recipe-2",
              group_manifest_id: "group-2",
              child_node_id: "child-1",
            },
          },
          consumer_slots: {
            "data.agent": { record_id: "record-1", port: "derived" },
            "data.notebook": { record_id: "record-1", port: "derived" },
            "data.report": { record_id: "record-1", port: "evidence" },
          },
          catalog_digest: "c".repeat(64),
        },
      },
      ...overrides,
    }),
  };
}

function descriptor(overrides: Record<string, unknown> = {}) {
  const value = {
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
      {
        name: "operation_record",
        port_type: "operation_record",
        dataset_kind: null,
        cardinality: "one",
        required: true,
        identity_fields: ["record_id"],
      },
      {
        name: "evidence",
        port_type: "evidence",
        dataset_kind: null,
        cardinality: "one",
        required: true,
        identity_fields: ["method"],
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
  return {
    ...value,
    request_schema_digest: canonicalRequestSchemaDigest(value.request_schema),
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
    preview: async (...args: Parameters<typeof previewMock>) =>
      testResponse(await previewMock(...args), args[2] as Record<string, unknown>, "preview"),
    confirm: async (...args: Parameters<typeof confirmMock>) =>
      testResponse(await confirmMock(...args), args[2] as Record<string, unknown>, "confirm"),
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

  it("rejects a request schema changed without a matching canonical digest", () => {
    const invalid = manifest();
    const operation = (invalid.operations as Array<Record<string, unknown>>)[0];
    const schema = operation.request_schema as Record<string, unknown>;
    const properties = schema.properties as Record<string, unknown>;
    properties.label = { type: "string", minLength: 2 };

    expect(() => parseDataOperationManifest(invalid)).toThrow(DataOperationManifestError);
    try {
      parseDataOperationManifest(invalid);
    } catch (error) {
      expect(error).toMatchObject({ code: "REQUEST_SCHEMA_DIGEST_MISMATCH" });
    }
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
    confirmMock.mockResolvedValue(completedResponse());
  });

  it("displays a typed error when the manifest omits source identity", () => {
    const invalid = JSON.parse(JSON.stringify(manifest())) as {
      operations: Array<{
        request_schema: { properties: Record<string, unknown> };
        request_schema_digest: string;
      }>;
    };
    delete invalid.operations[0].request_schema.properties.source_artifact_id;
    invalid.operations[0].request_schema_digest = canonicalRequestSchemaDigest(
      invalid.operations[0].request_schema,
    );

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
      preview: { status: "ready", fingerprint: "preview-fp-default", row_count_after: 2 },
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
        preview_fingerprint: "preview-fp-default",
      },
    );
    expect(await screen.findByTestId("data-operation-complete")).toHaveTextContent(
      "completed",
    );
  });

  it("rejects a plain preview object instead of treating it as server transport", async () => {
    previewMock.mockResolvedValue(rawTransport({
      preview: { status: "ready", fingerprint: "preview-fp-default" },
    }));

    render(<DataOperationsSection {...sectionProps()} />);
    fireEvent.change(screen.getByLabelText("Data operation"), {
      target: { value: "data.example" },
    });
    fireEvent.change(screen.getByLabelText("label"), {
      target: { value: "plain-preview" },
    });
    fireEvent.click(screen.getByTestId("data-operation-preview"));

    await waitFor(() => expect(screen.getByTestId("data-operation-error")).toHaveTextContent("PREVIEW_INVALID"));
    expect(screen.queryByTestId("data-operation-confirm")).toBeNull();
  });

  it("rejects a forged Response-like confirmation transport", async () => {
    const valid = completedResponse();
    confirmMock.mockResolvedValue(rawTransport({
      ok: true,
      status: 200,
      json: valid.json,
    }));
    previewMock.mockResolvedValue({
      preview: { status: "ready", fingerprint: "preview-fp-default" },
    });

    render(<DataOperationsSection {...sectionProps()} />);
    fireEvent.change(screen.getByLabelText("Data operation"), {
      target: { value: "data.example" },
    });
    fireEvent.change(screen.getByLabelText("label"), {
      target: { value: "forged-response" },
    });
    fireEvent.click(screen.getByTestId("data-operation-preview"));
    await screen.findByTestId("data-operation-preview-ready");
    fireEvent.click(screen.getByTestId("data-operation-confirm"));
    await waitFor(() => expect(screen.getByTestId("data-operation-error")).toHaveTextContent("CONFIRM_INVALID"));
  });

  it("does not show completed for a typed non-success confirmation", async () => {
    confirmMock.mockResolvedValue({
      status: "blocked",
      reason_code: "DATA_OPERATION_BLOCKED",
      message: "The operation is unavailable on this source.",
    });
    previewMock.mockResolvedValue({
      preview: { status: "ready", fingerprint: "preview-fp-2" },
    });

    render(<DataOperationsSection {...sectionProps()} />);
    fireEvent.change(screen.getByLabelText("Data operation"), {
      target: { value: "data.example" },
    });
    fireEvent.change(screen.getByLabelText("label"), {
      target: { value: "blocked" },
    });
    fireEvent.click(screen.getByTestId("data-operation-preview"));
    await screen.findByTestId("data-operation-preview-ready");
    fireEvent.click(screen.getByTestId("data-operation-confirm"));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("data-operation-complete")).toBeNull();
    expect(screen.getByTestId("data-operation-result")).toHaveTextContent("blocked");
    expect(screen.getByTestId("data-operation-result")).toHaveTextContent(
      "DATA_OPERATION_BLOCKED",
    );
  });

  it("does not show completed when the HTTP confirmation status is not successful", async () => {
    confirmMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        status: "error",
        reason_code: "DATA_OPERATION_STALE",
        message: "The preview is stale.",
      }),
    });
    previewMock.mockResolvedValue({
      preview: { status: "ready", fingerprint: "preview-fp-3" },
    });

    render(<DataOperationsSection {...sectionProps()} />);
    fireEvent.change(screen.getByLabelText("Data operation"), {
      target: { value: "data.example" },
    });
    fireEvent.change(screen.getByLabelText("label"), {
      target: { value: "stale" },
    });
    fireEvent.click(screen.getByTestId("data-operation-preview"));
    await screen.findByTestId("data-operation-preview-ready");
    fireEvent.click(screen.getByTestId("data-operation-confirm"));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("data-operation-complete")).toBeNull();
    expect(screen.getByTestId("data-operation-error")).toHaveTextContent(
      "HTTP 409",
    );
  });

  it("does not treat a plain object completion as a verified HTTP success", async () => {
    confirmMock.mockResolvedValue(rawTransport({
      status: "completed",
      effect: { execution_key: "exec-1", child_node_id: "child-1", artifact_id: "artifact-2" },
      operation: { record_id: "record-1", operation_id: "data.example", status: "completed" },
    }));
    previewMock.mockResolvedValue({ preview: { status: "ready", fingerprint: "preview-fp-default" } });

    render(<DataOperationsSection {...sectionProps()} />);
    fireEvent.change(screen.getByLabelText("Data operation"), { target: { value: "data.example" } });
    fireEvent.change(screen.getByLabelText("label"), { target: { value: "plain-object" } });
    fireEvent.click(screen.getByTestId("data-operation-preview"));
    await screen.findByTestId("data-operation-preview-ready");
    fireEvent.click(screen.getByTestId("data-operation-confirm"));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("data-operation-complete")).toBeNull();
    expect(await screen.findByTestId("data-operation-error")).toHaveTextContent("CONFIRM_INVALID");
  });

  it("does not complete when the response preview or source identity is stale", async () => {
    confirmMock.mockResolvedValue(
      completedResponse({
        preview: {
          status: "ready",
          fingerprint: "stale-preview",
          source_run_id: "foreign-run",
          source_node_id: SOURCE_IDENTITY.source_node_id,
          source_artifact_id: SOURCE_IDENTITY.source_artifact_id,
        },
      }),
    );
    previewMock.mockResolvedValue({ preview: { status: "ready", fingerprint: "preview-fp-default" } });

    render(<DataOperationsSection {...sectionProps()} />);
    fireEvent.change(screen.getByLabelText("Data operation"), { target: { value: "data.example" } });
    fireEvent.change(screen.getByLabelText("label"), { target: { value: "stale-identity" } });
    fireEvent.click(screen.getByTestId("data-operation-preview"));
    await screen.findByTestId("data-operation-preview-ready");
    fireEvent.click(screen.getByTestId("data-operation-confirm"));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("data-operation-complete")).toBeNull();
    expect(await screen.findByTestId("data-operation-error")).toHaveTextContent("CONFIRM_INVALID");
  });

  it("rejects an effect identity that only matches a different binding field", async () => {
    const valid = completedResponse();
    const body = (await valid.json()) as {
      operation: { execution: { bindings: Record<string, string> } };
      [key: string]: unknown;
    };
    body.operation.execution.bindings = {
      artifact_id: "artifact-2",
      data_child_node_id: "child-1",
      metadata_artifact_id: "metadata-2",
      recipe_artifact_id: "recipe-2",
      group_manifest_id: "group-2",
    };
    confirmMock.mockResolvedValue(body);
    previewMock.mockResolvedValue({
      preview: { status: "ready", fingerprint: "preview-fp-default" },
    });

    render(<DataOperationsSection {...sectionProps()} />);
    fireEvent.change(screen.getByLabelText("Data operation"), {
      target: { value: "data.example" },
    });
    fireEvent.change(screen.getByLabelText("label"), {
      target: { value: "binding-mutation" },
    });
    fireEvent.click(screen.getByTestId("data-operation-preview"));
    await screen.findByTestId("data-operation-preview-ready");
    fireEvent.click(screen.getByTestId("data-operation-confirm"));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("data-operation-complete")).toBeNull();
    expect(await screen.findByTestId("data-operation-error")).toHaveTextContent(
      "CONFIRM_INVALID",
    );
  });

  it("requires typed effect and operation identity before showing completed", async () => {
    confirmMock.mockResolvedValue({
      status: "completed",
      effect: { child_node_id: "child-1" },
      operation: { record_id: "record-1", operation_id: "data.other", status: "completed" },
    });
    previewMock.mockResolvedValue({
      preview: { status: "ready", fingerprint: "preview-fp-4" },
    });

    render(<DataOperationsSection {...sectionProps()} />);
    fireEvent.change(screen.getByLabelText("Data operation"), {
      target: { value: "data.example" },
    });
    fireEvent.change(screen.getByLabelText("label"), {
      target: { value: "identity-mismatch" },
    });
    fireEvent.click(screen.getByTestId("data-operation-preview"));
    await screen.findByTestId("data-operation-preview-ready");
    fireEvent.click(screen.getByTestId("data-operation-confirm"));

    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("data-operation-complete")).toBeNull();
    await waitFor(() =>
      expect(screen.getByTestId("data-operation-error")).toHaveTextContent("CONFIRM_INVALID"),
    );
  });
});
