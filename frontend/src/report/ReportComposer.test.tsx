import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportComposer } from "./ReportComposer";

const mockAgent = vi.hoisted(() => ({ current: null as unknown }));

vi.mock("../workbench/agent/AgentSurfaceContext", () => ({
  useAgentSurfaceOptional: () => mockAgent.current,
}));

describe("ReportComposer", () => {
  beforeEach(() => {
    mockAgent.current = {
      model: "model-a",
      modelOptions: [
        {
          display_name: "Model A",
          request_model: "model-a",
          context_window_tokens: 128_000,
          supports_1m: false,
        },
        {
          display_name: "Model B",
          request_model: "model-b",
          context_window_tokens: 64_000,
          supports_1m: false,
        },
      ],
      setModel: vi.fn().mockResolvedValue(undefined),
    };
  });

  it("uses a generic empty placeholder instead of pre-filling a report recipe", () => {
    render(
      <ReportComposer
        value=""
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        submitLabel="Generate report"
        placeholder="Tell Workbench what you want this report to explain…"
        contextLines={["Run run-c", "2 facts included"]}
        contextDetails={["c1 · Covariance = HC1"]}
        contextUsedTokens={240}
        contextWindowTokens={128_000}
        allowEmptySubmit
      />,
    );

    const input = screen.getByRole("textbox", { name: "Report instruction" });
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute(
      "placeholder",
      "Tell Workbench what you want this report to explain…",
    );
  });

  it("lets the user switch the report model and inspect read-only context", async () => {
    const onSubmit = vi.fn();
    render(
      <ReportComposer
        value="Explain the robustness checks"
        onChange={vi.fn()}
        onSubmit={onSubmit}
        submitLabel="Generate report"
        placeholder="Tell Workbench what you want this report to explain…"
        contextLines={["Run run-c", "2 of 3 facts included", "Evidence snapshot: abc123"]}
        contextDetails={["c1 · Covariance = HC1"]}
        contextUsedTokens={240}
        contextWindowTokens={128_000}
      />,
    );

    fireEvent.change(screen.getByRole("listbox", { name: "Report model" }), {
      target: { value: "model-b" },
    });
    expect((mockAgent.current as { setModel: ReturnType<typeof vi.fn> }).setModel)
      .toHaveBeenCalledWith("model-b");

    fireEvent.click(screen.getByRole("button", { name: "View report context" }));
    expect(screen.getByTestId("report-context-popover")).toHaveTextContent(
      "Evidence snapshot: abc123",
    );
    expect(screen.getByTestId("report-context-popover")).toHaveTextContent(
      "Source facts are read-only",
    );
    expect(screen.getByTestId("report-context-popover")).toHaveTextContent(
      "c1 · Covariance = HC1",
    );

    fireEvent.mouseDown(document.body);
    await waitFor(() =>
      expect(screen.queryByTestId("report-context-popover")).not.toBeInTheDocument(),
    );
  });

  it("blocks report submission until an active model switch is complete", async () => {
    let resolveModelSwitch: (() => void) | undefined;
    const setModel = vi.fn().mockReturnValue(new Promise<void>((resolve) => {
      resolveModelSwitch = resolve;
    }));
    mockAgent.current = {
      model: "model-a",
      modelOptions: [
        { display_name: "Model A", request_model: "model-a", context_window_tokens: 128_000, supports_1m: false },
        { display_name: "Model B", request_model: "model-b", context_window_tokens: 64_000, supports_1m: false },
      ],
      setModel,
    };
    const onSubmit = vi.fn();
    render(
      <ReportComposer
        value="Explain the robustness checks"
        onChange={vi.fn()}
        onSubmit={onSubmit}
        submitLabel="Generate report"
        placeholder="Tell Workbench what you want this report to explain…"
        contextLines={[]}
        contextUsedTokens={240}
        contextWindowTokens={128_000}
        allowEmptySubmit
      />,
    );

    fireEvent.change(screen.getByRole("listbox", { name: "Report model" }), {
      target: { value: "model-b" },
    });
    expect(screen.getByRole("button", { name: "Generate report" })).toBeDisabled();
    resolveModelSwitch?.();
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate report" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Generate report" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("focuses the composer when an Open Report action requests it", async () => {
    render(
      <ReportComposer
        value=""
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        submitLabel="Generate report"
        placeholder="Tell Workbench what you want this report to explain…"
        contextLines={[]}
        contextUsedTokens={1}
        allowEmptySubmit
        focusRequest={1}
      />,
    );

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Report instruction" })).toHaveFocus(),
    );
  });
});
