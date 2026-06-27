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

  it("strips artifact URLs and unknown full-content fields while preserving safe metadata", () => {
    const context = successfulContext();
    const packet = buildAskAIContextPacket({
      ...context,
      node_payload: {
        ...context.node_payload,
        artifacts: [
          {
            name: "training-data.csv",
            mime: "text/csv",
            sizeBytes: 4096,
            sha256: "sha256:abc123",
            url: "https://signed.example/download/training-data.csv",
            ai_visibility: "metadata_only",
            summary: "Rows and columns only",
            preview: {
              kind: "table",
              truncated: true,
              content: [["column"]],
            },
            redactions: ["large_table_truncated"],
            content: "full raw dataset rows",
            rows: [{ secret: "raw value" }],
          } as unknown as NodeOperationContextV1["node_payload"]["artifacts"][number],
        ],
      },
    });

    expect(packet.artifacts).toEqual([
      {
        name: "training-data.csv",
        mime: "text/csv",
        sizeBytes: 4096,
        sha256: "sha256:abc123",
        ai_visibility: "metadata_only",
        summary: "Rows and columns only",
        preview: {
          kind: "table",
          truncated: true,
          content: [["column"]],
        },
        redactions: ["large_table_truncated"],
      },
    ]);
    expect("url" in packet.artifacts[0]).toBe(false);
    expect("content" in packet.artifacts[0]).toBe(false);
    expect("rows" in packet.artifacts[0]).toBe(false);
  });

  it("caps large artifact previews and marks the redaction explicitly", () => {
    const context = successfulContext();
    const packet = buildAskAIContextPacket({
      ...context,
      node_payload: {
        ...context.node_payload,
        artifacts: [
          {
            name: "training-data.csv",
            mime: "text/csv",
            sizeBytes: 100_000,
            ai_visibility: "metadata_only",
            preview: "x".repeat(20_000),
          } as unknown as NodeOperationContextV1["node_payload"]["artifacts"][number],
        ],
      },
    });

    const preview = packet.artifacts[0].preview;
    expect(typeof preview).toBe("string");
    expect(String(preview).length).toBeLessThan(2500);
    expect(packet.artifacts[0].redactions).toContain("ask_ai_preview_truncated");
  });

  it("enforces a global preview budget across artifacts", () => {
    const context = successfulContext();
    const packet = buildAskAIContextPacket({
      ...context,
      node_payload: {
        ...context.node_payload,
        artifacts: Array.from({ length: 6 }, (_, index) => ({
          name: `preview-${index}.txt`,
          mime: "text/plain",
          sizeBytes: 50_000,
          ai_visibility: "metadata_only",
          preview: "x".repeat(2_000),
        })) as NodeOperationContextV1["node_payload"]["artifacts"],
      },
    });

    const totalPreviewChars = packet.artifacts.reduce((total, artifact) => {
      return total + (typeof artifact.preview === "string" ? artifact.preview.length : 0);
    }, 0);
    expect(packet.context_visibility_notice.max_total_preview_chars).toBe(8_000);
    expect(totalPreviewChars).toBeLessThanOrEqual(8_000);
    expect(packet.artifacts[packet.artifacts.length - 1].redactions).toContain(
      "ask_ai_preview_truncated",
    );
  });

  it("caps table previews to ten rows and twenty columns", () => {
    const context = successfulContext();
    const rows = Array.from({ length: 25 }, (_, row) =>
      Array.from({ length: 30 }, (_, column) => `${row}:${column}`),
    );
    const packet = buildAskAIContextPacket({
      ...context,
      node_payload: {
        ...context.node_payload,
        artifacts: [
          {
            name: "wide-table.csv",
            mime: "text/csv",
            sizeBytes: 100_000,
            ai_visibility: "metadata_only",
            preview: {
              kind: "table",
              content: rows,
            },
          } as unknown as NodeOperationContextV1["node_payload"]["artifacts"][number],
        ],
      },
    });

    const preview = packet.artifacts[0].preview as {
      content?: unknown[][];
    };
    expect(packet.context_visibility_notice.max_table_preview_rows).toBe(10);
    expect(packet.context_visibility_notice.max_table_preview_columns).toBe(20);
    expect(preview.content).toHaveLength(10);
    expect(preview.content?.[0]).toHaveLength(20);
    expect(packet.artifacts[0].redactions).toContain("ask_ai_preview_truncated");
  });

  it("omits binary previews even if a future artifact accidentally carries one", () => {
    const context = successfulContext();
    const packet = buildAskAIContextPacket({
      ...context,
      node_payload: {
        ...context.node_payload,
        artifacts: [
          {
            name: "report.pdf",
            mime: "application/pdf",
            sizeBytes: 100_000,
            ai_visibility: "metadata_only",
            preview: "full pdf text should not be sent",
          } as unknown as NodeOperationContextV1["node_payload"]["artifacts"][number],
        ],
      },
    });

    expect("preview" in packet.artifacts[0]).toBe(false);
    expect(packet.artifacts[0].redactions).toContain(
      "ask_ai_preview_omitted_for_mime",
    );
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
