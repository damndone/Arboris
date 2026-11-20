import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { llmModelFixture } from "../../apiFixtures";
import { AgentModelMenu, defaultEffort, limitOptions } from "./AgentModelMenu";

// As detected from the Magpie/WorkBuddy model list (2026-10-22).
const flash = llmModelFixture({ display_name: "DeepSeek V4.1 Flash", request_model: "workbuddy-ai/deepseek-v4.1-flash",
  context_window_tokens: 1_000_000, supports_1m: true, reasoning_efforts: ["none", "low", "high", "max"], reasoning_effort: "low" });
const hy3 = llmModelFixture({ display_name: "Hy3", request_model: "workbuddy-ai/hy3", context_window_tokens: 192_000,
  supports_1m: false, reasoning_efforts: ["low", "high"] });
const plain = llmModelFixture({ display_name: "Plain", request_model: "plain", context_window_tokens: null, supports_1m: false });

describe("AgentModelMenu", () => {
  test("shows the model and its thinking; switching model, saving effort and the limit", () => {
    const onSelect = vi.fn(), onSettings = vi.fn();
    render(<AgentModelMenu model={flash.request_model} options={[flash, hy3]} onSelect={onSelect} onSettings={onSettings} />);
    const button = screen.getByRole("button", { name: "Model: DeepSeek V4.1 Flash" });
    expect(button).toHaveTextContent("Low");
    fireEvent.click(button);
    fireEvent.keyDown(screen.getByRole("slider", { name: "Thinking" }), { key: "End" });
    expect(onSettings).toHaveBeenLastCalledWith(flash.request_model, { reasoning_effort: "max" });
    const context = screen.getByRole("slider", { name: "Context" });
    expect(context).toHaveAttribute("aria-valuetext", "Auto 200K");
    fireEvent.keyDown(context, { key: "ArrowLeft" });
    expect(onSettings).toHaveBeenLastCalledWith(flash.request_model, { context_limit_tokens: 128_000 });
    fireEvent.click(screen.getByRole("radio", { name: "Hy3" }));
    expect(onSelect).toHaveBeenCalledWith(hy3.request_model);
  });

  test("each model offers its own efforts and only the limits below its window", () => {
    render(<AgentModelMenu model={hy3.request_model} options={[flash, hy3]} onSelect={vi.fn()} onSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: Hy3" }));
    const thinking = screen.getByRole("slider", { name: "Thinking" });
    expect(thinking).toHaveAttribute("aria-valuemax", "1");
    expect(limitOptions(hy3).map((option) => option.label)).toEqual(["64K", "128K", "Full 192K"]);
    expect(defaultEffort(["low", "medium"])).toBe("medium");
  });

  test("fills the gap below 1M and persists the new caps without exceeding smaller windows", () => {
    const onSettings = vi.fn();
    render(<AgentModelMenu model={flash.request_model} options={[flash]} onSelect={vi.fn()} onSettings={onSettings} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: DeepSeek V4.1 Flash" }));
    expect(limitOptions(flash).map(({ label }) => label)).toEqual(["64K", "128K", "Auto 200K", "256K", "512K", "768K", "Full 1M"]);
    const context = screen.getByRole("slider", { name: "Context" });
    for (const cap of [256_000, 512_000, 768_000, 1_000_000]) {
      fireEvent.keyDown(context, { key: "ArrowRight" });
      expect(onSettings).toHaveBeenLastCalledWith(flash.request_model, { context_limit_tokens: cap });
    }
    expect(limitOptions({ ...flash, context_window_tokens: 262_144 }).map(({ label }) => label))
      .toEqual(["64K", "128K", "Auto 200K", "256K", "Full 262K"]);
    expect(limitOptions({ ...flash, context_window_tokens: 65_536 }).map(({ label }) => label))
      .toEqual(["64K", "Full 66K"]);
  });

  test("a model with no efforts and no known window shows neither control", () => {
    render(<AgentModelMenu model="plain" options={[plain]} onSelect={vi.fn()} onSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: Plain" }));
    expect(screen.queryByRole("slider", { name: "Thinking" })).not.toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Context limit" })).not.toBeInTheDocument();
  });

  test("Escape closes the menu", () => {
    render(<AgentModelMenu model={flash.request_model} options={[flash]} onSelect={vi.fn()} onSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: DeepSeek V4.1 Flash" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
