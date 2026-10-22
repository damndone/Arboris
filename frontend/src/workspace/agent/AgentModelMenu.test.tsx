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
    expect(screen.getAllByRole("radio").map((radio) => radio.textContent)).toEqual(expect.arrayContaining(["Off", "Low", "High", "Max"]));
    fireEvent.click(screen.getByRole("radio", { name: "Max" }));
    expect(onSettings).toHaveBeenLastCalledWith(flash.request_model, { reasoning_effort: "max" });
    expect(screen.getByRole("radio", { name: "Full 1M" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("radio", { name: "128K" }));
    expect(onSettings).toHaveBeenLastCalledWith(flash.request_model, { context_limit_tokens: 128_000 });
    fireEvent.click(screen.getByRole("radio", { name: "Hy3" }));
    expect(onSelect).toHaveBeenCalledWith(hy3.request_model);
  });

  test("each model offers its own efforts and only the limits below its window", () => {
    render(<AgentModelMenu model={hy3.request_model} options={[flash, hy3]} onSelect={vi.fn()} onSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: Hy3" }));
    const thinking = screen.getByRole("radiogroup", { name: "Thinking" });
    expect(Array.from(thinking.querySelectorAll("[role=radio]")).map((radio) => radio.textContent)).toEqual(["Low", "High"]);
    expect(limitOptions(hy3).map((option) => option.label)).toEqual(["Full 192K", "128K", "64K"]);
    expect(defaultEffort(["low", "medium"])).toBe("medium");
  });

  test("a model with no efforts and no known window shows neither control", () => {
    render(<AgentModelMenu model="plain" options={[plain]} onSelect={vi.fn()} onSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: Plain" }));
    expect(screen.queryByRole("radiogroup", { name: "Thinking" })).not.toBeInTheDocument();
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
