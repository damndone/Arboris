import { afterEach, describe, expect, it, vi } from "vitest";
import {
  compileAgentCutover,
  compileNotebookCutover,
  confirmCutover,
  executeCutover,
  getCutoverIdentity,
  isRetryableCutoverError,
  type CutoverBindingV1,
  type CutoverConfirmationV1,
  type CutoverIdentityV1,
} from "./cutoverApi";

const identity: CutoverIdentityV1 = {
  schema_version: "agent-notebook-cutover-identity.v1",
  actor_ref: "principal:local:backend",
  session_ref: "session:local:backend",
  project_ref: "project:local:test",
};

const preview = {
  schema_version: "cutover-compilation-preview.v1",
  entrypoint: "agent",
  operation_id: "cutover-operation:1",
  compilation_record_id: "compilation:1",
  record_digest: "a".repeat(64),
  semantic_plan_hash: "b".repeat(64),
  server_execution_identity: "compiler:local:1",
  preview_fingerprint: "c".repeat(64),
  plan_diff: { effect: "read" },
  clarifications: [],
};

const binding: CutoverBindingV1 = {
  schema_version: "server-proposal-binding.v1",
  proposal_id: "cutover-proposal:1",
  proposal_revision: 1,
  proposal_fingerprint: "d".repeat(64),
  semantic_plan_hash: preview.semantic_plan_hash,
  actor_ref: identity.actor_ref,
  session_ref: identity.session_ref,
  project_ref: identity.project_ref,
  confirmation_id: "confirmation:1",
  compilation_record_id: preview.compilation_record_id,
};

const confirmation: CutoverConfirmationV1 = {
  schema_version: "server-confirmation-receipt.v1",
  confirmation_id: binding.confirmation_id,
  confirmation_digest: "e".repeat(64),
  compilation_record_id: binding.compilation_record_id,
  proposal_id: binding.proposal_id,
  proposal_revision: binding.proposal_revision,
  proposal_fingerprint: binding.proposal_fingerprint,
  semantic_plan_hash: binding.semantic_plan_hash,
  actor_ref: identity.actor_ref,
  session_ref: identity.session_ref,
  project_ref: identity.project_ref,
};

const result = {
  schema_version: "cutover-execution-result.v1",
  operation_id: preview.operation_id,
  compilation_record_id: binding.compilation_record_id,
  execution_instance_hash: "f".repeat(64),
  status: "completed",
  result: { evidence_ref: "evidence:1" },
  evidence_refs: ["evidence:1"],
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("shared Agent/Notebook cutover API", () => {
  it("uses one validated compile/confirm/execute transport for Agent and Notebook", async () => {
    const notebookPreview = { ...preview, entrypoint: "notebook" };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }))
      .mockResolvedValueOnce(json({ preview: notebookPreview, binding }))
      .mockResolvedValueOnce(json({ confirmation }))
      .mockResolvedValueOnce(json({ result }));

    expect(await getCutoverIdentity("/tmp/project")).toEqual(identity);
    await compileAgentCutover("检查数据", identity);
    await compileNotebookCutover("/tmp/project", "nb_1", "检查数据", identity);
    await confirmCutover(binding, identity);
    await executeCutover(binding, identity, confirmation, {
      expected_operation_id: preview.operation_id,
    });

    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      "/api/agent/cutover/identity?project_root=%2Ftmp%2Fproject",
      "/api/agent/cutover/compile",
      "/api/notebooks/nb_1/cutover/compile?project_root=%2Ftmp%2Fproject",
      "/api/agent/cutover/compilation%3A1/confirm",
      "/api/agent/cutover/compilation%3A1/execute",
    ]);
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({
      actor_ref: identity.actor_ref,
      session_ref: identity.session_ref,
      project_ref: identity.project_ref,
      entrypoint: "agent",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[4][1]?.body))).toMatchObject({
      confirmation_id: confirmation.confirmation_id,
    });
  });

  it("returns UNSUPPORTED_VERSION before exposing an unknown identity contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({
      ...identity,
      schema_version: "agent-notebook-cutover-identity.v0",
    }));

    await expect(getCutoverIdentity("/tmp/project")).rejects.toMatchObject({
      code: "UNSUPPORTED_VERSION",
    });
  });

  it("fails closed when preview and binding identify different compilations", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({
      preview,
      binding: { ...binding, compilation_record_id: "compilation:forged" },
    }));

    await expect(compileAgentCutover("检查数据", identity)).rejects.toMatchObject({
      code: "CUTOVER_CONTRACT_INVALID",
    });
  });

  it("fails closed when an executable preview has no server binding", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ preview }));

    await expect(compileAgentCutover("检查数据", identity)).rejects.toMatchObject({
      code: "CUTOVER_CONTRACT_INVALID",
    });
  });

  it("fails closed when a clarification does not satisfy the v1 contract", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({
      preview: {
        ...preview,
        operation_id: null,
        compilation_record_id: null,
        record_digest: null,
        semantic_plan_hash: null,
        server_execution_identity: null,
        preview_fingerprint: null,
        clarifications: [{ field: 42 }],
      },
    }));

    await expect(compileAgentCutover("检查数据", identity)).rejects.toMatchObject({
      code: "CUTOVER_CONTRACT_INVALID",
    });
  });

  it("rejects an executable binding that also claims clarification is required", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({
      preview: {
        ...preview,
        clarifications: [{
          code: "missing_required_information",
          field: "target_ref",
          message: "Choose a server-verifiable target.",
          allowed_values: [],
        }],
      },
      binding,
    }));

    await expect(compileAgentCutover("检查数据", identity)).rejects.toMatchObject({
      code: "CUTOVER_CONTRACT_INVALID",
    });
  });

  it("rejects a confirmation that is not bound to the displayed proposal", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({
      confirmation: { ...confirmation, semantic_plan_hash: "0".repeat(64) },
    }));

    await expect(confirmCutover(binding, identity)).rejects.toMatchObject({
      code: "CUTOVER_CONTRACT_INVALID",
    });
  });

  it("rejects a result for another operation or compilation record", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({
      result: { ...result, operation_id: "cutover-operation:forged" },
    }));

    await expect(executeCutover(binding, identity, confirmation, {
      expected_operation_id: preview.operation_id,
    })).rejects.toMatchObject({ code: "CUTOVER_CONTRACT_INVALID" });
  });

  it("rejects a non-terminal result or a completed result without evidence", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({
        result: { ...result, status: "pending", evidence_refs: [] },
      }))
      .mockResolvedValueOnce(json({
        result: { ...result, evidence_refs: [] },
      }));

    await expect(executeCutover(binding, identity, confirmation, {
      expected_operation_id: preview.operation_id,
    })).rejects.toMatchObject({ code: "CUTOVER_CONTRACT_INVALID" });
    await expect(executeCutover(binding, identity, confirmation, {
      expected_operation_id: preview.operation_id,
    })).rejects.toMatchObject({ code: "CUTOVER_CONTRACT_INVALID" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("classifies only bounded transient failures as retryable", () => {
    expect(isRetryableCutoverError(new TypeError("Failed to fetch"))).toBe(true);
    expect(isRetryableCutoverError(Object.assign(new Error("upstream"), { status: 503 }))).toBe(true);
    expect(isRetryableCutoverError(Object.assign(new Error("state"), {
      status: 409,
      code: "OPERATION_EXECUTION_STATE_INVALID",
    }))).toBe(false);
    expect(isRetryableCutoverError(Object.assign(new Error("schema"), {
      code: "UNSUPPORTED_VERSION",
    }))).toBe(false);
    expect(isRetryableCutoverError(new SyntaxError("malformed JSON"))).toBe(false);
    expect(isRetryableCutoverError(new Error("application failure"))).toBe(false);
  });
});
