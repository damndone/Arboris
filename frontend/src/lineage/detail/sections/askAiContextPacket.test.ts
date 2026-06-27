import { describe, expect, it } from "vitest";
import {
  makeOwnerResolutionSeedFixture,
  resolveNodeOperationContext,
  type NodeOperationContextV1,
} from "../../api/nodeOperationContext";
import { buildAskAIContextPacket } from "./askAiContextPacket";

function successfulContext(): NodeOperationContextV1 {
  const seed = makeOwnerResolutionSeedFixture();
  const result = resolveNodeOperationContext({
    forest: seed.forest,
    selected_forest_node_key: seed.sharedNodeKey,
    active_head_run_id: seed.activeHeadRunId,
  });
  expect(result.ok).toBe(true);
  if (!result.ok) throw new Error(result.reason);
  return result.context;
}

function collectKeys(value: unknown, keys = new Set<string>()): Set<string> {
  if (!value || typeof value !== "object") return keys;
  if (Array.isArray(value)) {
    for (const item of value) collectKeys(item, keys);
    return keys;
  }
  for (const [key, child] of Object.entries(value)) {
    keys.add(key);
    collectKeys(child, keys);
  }
  return keys;
}

describe("buildAskAIContextPacket", () => {
  it("builds packet only from successful NodeOperationContext", () => {
    const packet = buildAskAIContextPacket(successfulContext());
    expect(packet.packet_scope.scope_type).toBe("selected_node");
    expect(packet.source_context_version).toBe("node-operation-context/v1");
    expect(packet.context_fingerprint).toMatch(/^nocv1:/);
    expect(packet.context_visibility_notice.full_datasets_included).toBe(false);
    expect(packet.response_guardrails.executable_actions_allowed).toBe(false);
  });

  it("declares that full datasets, reports, and binaries are not included", () => {
    const packet = buildAskAIContextPacket(successfulContext());
    expect(packet.context_visibility_notice).toMatchObject({
      artifact_policy: "metadata_and_safe_preview_only",
      full_datasets_included: false,
      full_reports_included: false,
      binary_artifacts_included: false,
    });
  });

  it("disallows executable actions, graph mutations, and backend payload execution", () => {
    const packet = buildAskAIContextPacket(successfulContext());
    expect(packet.response_guardrails).toMatchObject({
      advisory_text_only: true,
      executable_actions_allowed: false,
      graph_mutations_allowed: false,
      backend_payloads_allowed: false,
      file_reads_allowed: false,
      must_disclose_visibility_limits: true,
    });
  });

  it("marks every generated artifact entry with ai_visibility", () => {
    const context = successfulContext();
    const packet = buildAskAIContextPacket({
      ...context,
      node_payload: {
        ...context.node_payload,
        artifacts: [
          {
            name: "model-summary.json",
            mime: "application/json",
            sizeBytes: 128,
            ai_visibility: "metadata_only",
          },
          {
            name: "report.pdf",
            mime: "application/pdf",
            sizeBytes: 2048,
            ai_visibility: "metadata_only",
          },
        ],
      },
    });
    expect(packet.artifacts).toHaveLength(2);
    expect(packet.artifacts.every((artifact) => artifact.ai_visibility)).toBe(true);
  });

  it("does not include raw forest or run graph payload keys", () => {
    const packet = buildAskAIContextPacket(successfulContext());
    const keys = collectKeys(packet);
    expect(keys.has("forest")).toBe(false);
    expect(keys.has("nodes")).toBe(false);
    expect(keys.has("edges")).toBe(false);
    expect(keys.has("heads")).toBe(false);
    expect(keys.has("raw")).toBe(false);
  });
});
