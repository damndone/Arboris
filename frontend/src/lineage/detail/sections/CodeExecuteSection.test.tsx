import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CodeExecuteSection } from "./CodeExecuteSection";
import type { GraphViewNode } from "../../api/graphViewTypes";

const {
  resolvedMock,
  projectRootMock,
  contextMock,
  previewMock,
  authorizeMock,
  confirmMock,
} = vi.hoisted(
  () => ({
    resolvedMock: { current: null as unknown },
    projectRootMock: { current: null as unknown },
    contextMock: vi.fn(),
    previewMock: vi.fn(),
    authorizeMock: vi.fn(),
    confirmMock: vi.fn(),
  }),
);

vi.mock("../NodeOperationContextProvider", () => ({
  useResolvedNodeOperationContext: () => resolvedMock.current,
}));
vi.mock("../../../workbench/ProjectRootContext", () => ({
  useProjectRootOptional: () => projectRootMock.current,
}));
vi.mock("../../dataOperations", () => ({
  fetchDataColumnCastContext: (...args: unknown[]) => contextMock(...args),
  previewCodeExecute: (...args: unknown[]) => previewMock(...args),
  authorizeCodeExecuteRisk: (...args: unknown[]) => authorizeMock(...args),
  confirmCodeExecute: (...args: unknown[]) => confirmMock(...args),
}));

function node(kind: GraphViewNode["kind"] = "dataset_stage"): GraphViewNode {
  return {
    id: "hash-source::stage:cleaned",
    nodeKey: "hash-source::stage:cleaned",
    raw: { id: "stage:cleaned", payload_ref: "processed/cleaned.parquet" },
    stage: "clean",
    kind,
    title: "Cleaned data",
    parentStageId: null,
    trust: "ok",
    decisions: [],
  };
}

function readyPreview(overrides: Record<string, unknown> = {}) {
  return {
    preview: {
      operation_id: "code.execute",
      operation_version: "v1",
      status: "ready",
      fingerprint: "fp-1",
      code: "result = df",
      code_sha256: "abc",
      language: "python",
      output_format: "csv",
      source_sha256: "sha-1",
      row_count_before: 2,
      row_count_after: 2,
      columns_added: ["doubled"],
      columns_removed: [],
      dtype_changes: [],
      schema_fingerprint_before: "s1",
      schema_fingerprint_after: "s2",
      result_fingerprint: "r1",
      result_preview_rows: [],
      stdout: "",
      downstream_invalidation: ["model:ols"],
      error: null,
      ...overrides,
    },
  };
}

function riskAuthorizationResponse() {
  return {
    status: "risk_authorized",
    proposal: {},
    risk_authorization: {
      authorization_id: "risk-1",
      token: "opaque-risk-token",
      operation_id: "code.execute",
      operation_version: "v1",
      proposal_id: "proposal-1",
      revision: 1,
      fingerprint: "fp-1",
      active_head_run_id: "run-1",
      expires_at: "2026-07-16T00:05:00Z",
      status: "issued",
    },
  };
}

describe("CodeExecuteSection", () => {
  beforeEach(() => {
    projectRootMock.current = "/tmp/project";
    resolvedMock.current = {
      ok: true,
      context: {
        ownership: { owner_run_id: "run-1" },
        operation_target: { op_node_id: "stage:cleaned" },
      },
    };
    contextMock.mockReset();
    previewMock.mockReset();
    authorizeMock.mockReset();
    authorizeMock.mockResolvedValue(riskAuthorizationResponse());
    confirmMock.mockReset();
    contextMock.mockResolvedValue({
      source_run_id: "run-1",
      source_node_id: "stage:cleaned",
      source_artifact_id: "artifact-1",
      source_artifact_path: "processed/cleaned.parquet",
      source_sha256: "sha-1",
      row_count: 2,
      columns: [
        { name: "age", dtype: "int64" },
        { name: "name", dtype: "object" },
      ],
      downstream_invalidation: ["model:ols"],
    });
  });

  it("renders only for dataset nodes", () => {
    const { container } = render(<CodeExecuteSection node={node("model")} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("states the sandbox boundary the user is relying on", async () => {
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-section");

    const section = screen.getByTestId("code-execute-section");
    expect(section.textContent).toContain("no network");
    expect(section.textContent).toContain("read-only");
  });

  it("previews by really running the code and shows the schema diff", async () => {
    previewMock.mockResolvedValue(readyPreview());
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.change(screen.getByTestId("code-execute-code"), {
      target: { value: "result = df.assign(doubled=df['age'] * 2)" },
    });
    fireEvent.click(screen.getByTestId("code-execute-preview-button"));

    await screen.findByTestId("code-execute-diff");
    expect(previewMock).toHaveBeenCalledWith("/tmp/project", {
      source_run_id: "run-1",
      source_node_id: "stage:cleaned",
      source_artifact_id: "artifact-1",
      code: "result = df.assign(doubled=df['age'] * 2)",
      language: "python",
      output_format: "csv",
    });
    expect(screen.getByTestId("code-execute-diff").textContent).toContain("+ doubled");
  });

  it("cannot apply before previewing, because there is nothing confirmed yet", async () => {
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    expect(screen.getByTestId("code-execute-confirm-button")).toBeDisabled();
  });

  it("requires explicit high-risk authorization after the preview", async () => {
    previewMock.mockResolvedValue(readyPreview());
    authorizeMock.mockResolvedValue({
      status: "risk_authorized",
      proposal: {},
      risk_authorization: {
        authorization_id: "risk-1",
        token: "opaque-risk-token",
        operation_id: "code.execute",
        operation_version: "v1",
        proposal_id: "proposal-1",
        revision: 1,
        fingerprint: "fp-1",
        active_head_run_id: "run-1",
        expires_at: "2026-07-16T00:05:00Z",
        status: "issued",
      },
    });
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.click(screen.getByTestId("code-execute-preview-button"));
    await screen.findByTestId("code-execute-diff");
    expect(screen.getByTestId("code-execute-confirm-button")).toBeDisabled();
    expect(screen.getByTestId("code-execute-risk-warning").textContent).toContain(
      "sandboxed does not mean low risk",
    );

    fireEvent.click(screen.getByTestId("code-execute-risk-acknowledgement"));
    fireEvent.click(screen.getByTestId("code-execute-authorize-button"));
    await screen.findByTestId("code-execute-risk-authorized");

    expect(authorizeMock).toHaveBeenCalledWith(
      "/tmp/project",
      expect.objectContaining({
        preview_fingerprint: "fp-1",
        acknowledge_risk: true,
      }),
    );
    expect(screen.getByTestId("code-execute-confirm-button")).toBeEnabled();
  });

  it("invalidates a stale preview when the code changes", async () => {
    previewMock.mockResolvedValue(readyPreview());
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.click(screen.getByTestId("code-execute-preview-button"));
    await screen.findByTestId("code-execute-diff");
    expect(screen.getByTestId("code-execute-confirm-button")).toBeDisabled();

    fireEvent.change(screen.getByTestId("code-execute-code"), {
      target: { value: "result = df.head(1)" },
    });

    expect(screen.queryByTestId("code-execute-diff")).toBeNull();
    expect(screen.getByTestId("code-execute-confirm-button")).toBeDisabled();
  });

  it("clears the applied state when code changes after a successful apply", async () => {
    previewMock.mockResolvedValue(readyPreview());
    confirmMock.mockResolvedValue({
      proposal: {},
      operation: { record_id: "op-9" },
      status: "completed",
    });
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.click(screen.getByTestId("code-execute-preview-button"));
    await screen.findByTestId("code-execute-diff");
    fireEvent.click(screen.getByTestId("code-execute-risk-acknowledgement"));
    fireEvent.click(screen.getByTestId("code-execute-authorize-button"));
    await screen.findByTestId("code-execute-risk-authorized");
    fireEvent.click(screen.getByTestId("code-execute-confirm-button"));
    await screen.findByTestId("code-execute-complete");

    fireEvent.change(screen.getByTestId("code-execute-code"), {
      target: { value: "result = df.head(1)" },
    });

    expect(screen.queryByTestId("code-execute-complete")).toBeNull();
    expect(screen.getByTestId("code-execute-preview-button")).toBeEnabled();
  });

  it("locks the operation inputs while apply is in flight", async () => {
    previewMock.mockResolvedValue(readyPreview());
    let resolveConfirm: ((value: unknown) => void) | undefined;
    confirmMock.mockReturnValue(
      new Promise((resolve) => {
        resolveConfirm = resolve;
      }),
    );
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.click(screen.getByTestId("code-execute-preview-button"));
    await screen.findByTestId("code-execute-diff");
    fireEvent.click(screen.getByTestId("code-execute-risk-acknowledgement"));
    fireEvent.click(screen.getByTestId("code-execute-authorize-button"));
    await screen.findByTestId("code-execute-risk-authorized");
    fireEvent.click(screen.getByTestId("code-execute-confirm-button"));

    expect(screen.getByTestId("code-execute-code")).toBeDisabled();
    expect(screen.getByTestId("code-execute-format")).toBeDisabled();

    resolveConfirm?.({
      proposal: {},
      operation: { record_id: "op-10" },
      status: "completed",
    });
    await screen.findByTestId("code-execute-complete");
  });

  it("shows the traceback and blocks applying when the code fails", async () => {
    previewMock.mockResolvedValue(
      readyPreview({ status: "blocked", error: "KeyError: 'nope'", fingerprint: "" }),
    );
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.click(screen.getByTestId("code-execute-preview-button"));

    await screen.findByTestId("code-execute-error");
    expect(screen.getByTestId("code-execute-error").textContent).toContain("KeyError");
    expect(screen.getByTestId("code-execute-confirm-button")).toBeDisabled();
    expect(screen.queryByTestId("code-execute-diff")).toBeNull();
  });

  it("surfaces stdout so the run is inspectable", async () => {
    previewMock.mockResolvedValue(readyPreview({ stdout: "hello from the sandbox" }));
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.click(screen.getByTestId("code-execute-preview-button"));

    await screen.findByTestId("code-execute-stdout");
    expect(screen.getByTestId("code-execute-stdout").textContent).toContain(
      "hello from the sandbox",
    );
  });

  it("confirms with the previewed fingerprint and reports the operation record", async () => {
    previewMock.mockResolvedValue(readyPreview());
    confirmMock.mockResolvedValue({
      proposal: {},
      operation: { record_id: "op-9" },
      status: "completed",
    });
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.click(screen.getByTestId("code-execute-preview-button"));
    await screen.findByTestId("code-execute-diff");
    fireEvent.click(screen.getByTestId("code-execute-risk-acknowledgement"));
    fireEvent.click(screen.getByTestId("code-execute-authorize-button"));
    await screen.findByTestId("code-execute-risk-authorized");
    fireEvent.click(screen.getByTestId("code-execute-confirm-button"));

    await screen.findByTestId("code-execute-complete");
    expect(confirmMock).toHaveBeenCalledWith(
      "/tmp/project",
      expect.objectContaining({
        preview_fingerprint: "fp-1",
        risk_authorization_id: "risk-1",
        risk_authorization_token: "opaque-risk-token",
      }),
    );
    expect(screen.getByTestId("code-execute-complete").textContent).toContain("op-9");
  });

  it("surfaces a refused apply instead of implying it worked", async () => {
    previewMock.mockResolvedValue(readyPreview());
    confirmMock.mockRejectedValue(new Error("the code produced a different result"));
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.click(screen.getByTestId("code-execute-preview-button"));
    await screen.findByTestId("code-execute-diff");
    fireEvent.click(screen.getByTestId("code-execute-risk-acknowledgement"));
    fireEvent.click(screen.getByTestId("code-execute-authorize-button"));
    await screen.findByTestId("code-execute-risk-authorized");
    fireEvent.click(screen.getByTestId("code-execute-confirm-button"));

    await waitFor(() => {
      expect(screen.getByTestId("code-execute-fetch-error").textContent).toContain(
        "different result",
      );
    });
    expect(screen.queryByTestId("code-execute-complete")).toBeNull();
  });

  it("passes the chosen output format through to the operation", async () => {
    previewMock.mockResolvedValue(readyPreview({ output_format: "xlsx" }));
    render(<CodeExecuteSection node={node()} />);
    await screen.findByTestId("code-execute-columns");

    fireEvent.change(screen.getByTestId("code-execute-format"), {
      target: { value: "xlsx" },
    });
    fireEvent.click(screen.getByTestId("code-execute-preview-button"));

    await screen.findByTestId("code-execute-diff");
    expect(previewMock).toHaveBeenCalledWith(
      "/tmp/project",
      expect.objectContaining({ output_format: "xlsx" }),
    );
  });
});
