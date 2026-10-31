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
    const thinking = screen.getByRole("slider", { name: "Thinking" });
    fireEvent.change(thinking, { target: { value: thinking.getAttribute("max") } });
    expect(onSettings).toHaveBeenLastCalledWith(flash.request_model, { reasoning_effort: "max" });
    const context = screen.getByRole("slider", { name: "Context" });
    expect(context).toHaveAttribute("aria-valuetext", "Full 1M");
    fireEvent.change(context, { target: { value: "1" } });
    expect(onSettings).toHaveBeenLastCalledWith(flash.request_model, { context_limit_tokens: 128_000 });
    fireEvent.click(screen.getByRole("radio", { name: "Hy3" }));
    expect(onSelect).toHaveBeenCalledWith(hy3.request_model);
  });

  test("each model offers its own efforts and only the limits below its window", () => {
    render(<AgentModelMenu model={hy3.request_model} options={[flash, hy3]} onSelect={vi.fn()} onSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: Hy3" }));
    const thinking = screen.getByRole("slider", { name: "Thinking" });
    expect(thinking).toHaveAttribute("max", "1");
    expect(limitOptions(hy3).map((option) => option.label)).toEqual(["Full 192K", "128K", "64K"]);
    expect(defaultEffort(["low", "medium"])).toBe("medium");
  });

  test("fills the gap below 1M and persists the new caps without exceeding smaller windows", () => {
    const onSettings = vi.fn();
    render(<AgentModelMenu model={flash.request_model} options={[flash]} onSelect={vi.fn()} onSettings={onSettings} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: DeepSeek V4.1 Flash" }));
    expect(limitOptions(flash).map(({ label }) => label)).toEqual(["Full 1M", "768K", "512K", "256K", "128K", "64K"]);
    const context = screen.getByRole("slider", { name: "Context" });
    for (const [step, cap] of [["4", 768_000], ["3", 512_000]] as const) {
      fireEvent.change(context, { target: { value: step } });
      expect(onSettings).toHaveBeenLastCalledWith(flash.request_model, { context_limit_tokens: cap });
    }
    fireEvent.change(context, { target: { value: "5" } });
    expect(onSettings).toHaveBeenLastCalledWith(flash.request_model, { context_limit_tokens: null });
    expect(limitOptions({ ...flash, context_window_tokens: 262_144 }).map(({ label }) => label))
      .toEqual(["Full 262K", "256K", "128K", "64K"]);
    expect(limitOptions({ ...flash, context_window_tokens: 65_536 }).map(({ label }) => label))
      .toEqual(["Full 66K", "64K"]);
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
