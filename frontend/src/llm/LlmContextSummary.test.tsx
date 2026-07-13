import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LlmContextSummary } from "./LlmContextSummary";

const packet = {
  context_window_tokens: 1_000_000,
  supports_1m: true,
  packet_version: "ask-ai-context/v1",
  context_fingerprint: "fp-123",
  selection: { kind: "model", stage: "model" },
  packet_scope: { includes_upstream_path: true },
  lineage_summary: { upstream_path: [{ key: "data" }, { key: "cleaning" }] },
  context_visibility_notice: {
    max_total_preview_chars: 8_000,
    full_datasets_included: false,
    full_reports_included: false,
    binary_artifacts_included: false,
  },
  artifacts: [
    {
      name: "training-data.csv",
      redactions: ["ask_ai_preview_truncated", "secret_column_redacted"],
      preview: "safe preview only",
      raw_secret: "must never appear in the summary",
    },
    {
      name: "report.pdf",
      redactions: ["ask_ai_preview_omitted_for_mime"],
    },
  ],
} as const;

describe("LlmContextSummary", () => {
  it("shows model capacity separately from packet diagnostics without raw data", () => {
    render(
      <LlmContextSummary
        packet={packet}
      />,
    );

    const summary = screen.getByTestId("llm-context-summary");
    const expectedPacketBytes = new TextEncoder().encode(
      JSON.stringify(packet),
    ).byteLength;

    expect(summary.tagName).toBe("DETAILS");
    expect(summary).not.toHaveAttribute("open");
    expect(summary).toHaveTextContent("Model context capacity: 1,000,000 tokens");
    expect(summary).toHaveTextContent("Supports 1M: Yes");
    expect(summary).toHaveTextContent("Packet version: ask-ai-context/v1");
    expect(summary).toHaveTextContent("Node kind/stage: model / model");
    expect(summary).toHaveTextContent("Context fingerprint: fp-123");
    expect(summary).toHaveTextContent("Upstream path: included (2 nodes)");
    expect(summary).toHaveTextContent("Packet JSON characters:");
    expect(summary).toHaveTextContent(`Packet size: ${expectedPacketBytes} bytes`);
    expect(summary).toHaveTextContent("Preview budget: 8,000 characters");
    expect(summary).toHaveTextContent("Artifacts: 2");
    expect(summary).toHaveTextContent("Visibility/truncation: truncated");
    expect(summary).toHaveTextContent(
      "safe previews only; full datasets, reports, and binaries excluded",
    );
    expect(summary).toHaveTextContent("Redacted artifacts: 2");
    expect(summary).toHaveTextContent("training-data.csv");
    expect(summary).toHaveTextContent("report.pdf");
    expect(summary).not.toHaveTextContent("must never appear in the summary");
  });

  it("renders safe fallbacks for missing packet fields and no artifacts", () => {
    render(<LlmContextSummary packet={{}} />);

    const summary = screen.getByTestId("llm-context-summary");
    expect(summary).toHaveTextContent("Model context capacity: Unavailable");
    expect(summary).toHaveTextContent("Supports 1M: Unknown");
    expect(summary).toHaveTextContent("Packet version: Unavailable");
    expect(summary).toHaveTextContent("Node kind/stage: Unavailable / Unavailable");
    expect(summary).toHaveTextContent("Context fingerprint: Unavailable");
    expect(summary).toHaveTextContent("Upstream path: Unavailable");
    expect(summary).toHaveTextContent("Packet JSON characters:");
    expect(summary).toHaveTextContent("Preview budget: Unavailable");
    expect(summary).toHaveTextContent("Artifacts: 0");
    expect(summary).toHaveTextContent("Visibility/truncation: not reported");
    expect(summary).toHaveTextContent("Visibility notice: Unavailable");
    expect(summary).toHaveTextContent("Redacted artifacts: 0");
    expect(summary).toHaveTextContent("No redacted artifacts reported.");
  });

  it("uses a safe UTF-8 fallback when TextEncoder is unavailable", () => {
    vi.stubGlobal("TextEncoder", undefined);
    try {
      render(<LlmContextSummary packet={{ text: "héllo 🌍" }} />);

      expect(screen.getByTestId("llm-context-summary")).toHaveTextContent(
        "Packet size: 22 bytes",
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("reports unavailable packet size when serialization fails", () => {
    const packet: Record<string, unknown> = {};
    packet.self = packet;

    render(<LlmContextSummary packet={packet} />);

    expect(screen.getByTestId("llm-context-summary")).toHaveTextContent(
      "Packet size: Unavailable",
    );
  });

  it("keeps safe-preview restrictions distinct from explicit truncation", () => {
    render(
      <LlmContextSummary
        packet={{
          context_visibility_notice: {
            artifact_policy: "metadata_and_safe_preview_only",
            full_datasets_included: false,
            full_reports_included: false,
            binary_artifacts_included: false,
          },
          artifacts: [
            {
              name: "report.pdf",
              redactions: ["ask_ai_preview_omitted_for_mime"],
            },
          ],
        }}
      />,
    );

    const summary = screen.getByTestId("llm-context-summary");
    expect(summary).toHaveTextContent(
      "Visibility/truncation: restricted/safe previews",
    );
    expect(summary.textContent).not.toContain(
      "Visibility/truncation: truncated",
    );
    expect(summary).toHaveTextContent("Redacted artifacts: 1");
  });

  it("memoizes packet diagnostics when the packet reference is unchanged", () => {
    const packet = { packet_version: "ask-ai-context/v1", artifacts: [] };
    const stringify = vi.spyOn(JSON, "stringify");
    const { rerender } = render(<LlmContextSummary packet={packet} />);
    const callsAfterInitialRender = stringify.mock.calls.length;

    rerender(<LlmContextSummary packet={packet} />);

    expect(stringify).toHaveBeenCalledTimes(callsAfterInitialRender);
    stringify.mockRestore();
  });
});
