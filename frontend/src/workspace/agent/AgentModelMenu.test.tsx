import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { llmModelFixture } from "../../apiFixtures";
import { AgentModelMenu } from "./AgentModelMenu";

const flash = llmModelFixture({ display_name: "DeepSeek V4.1 Flash", request_model: "deepseek-flash", context_window_tokens: null,
  supports_1m: true, supports_reasoning_effort: true, reasoning_effort: "low" });
const glm = llmModelFixture({ display_name: "GLM 5.3 Flash", request_model: "glm-5.3", context_window_tokens: null, supports_1m: false });

describe("AgentModelMenu", () => {
  test("shows the model and its thinking; switching model and saving effort and context", () => {
    const onSelect = vi.fn(), onSettings = vi.fn();
    render(<AgentModelMenu model="deepseek-flash" options={[flash, glm]} onSelect={onSelect} onSettings={onSettings} />);
    const button = screen.getByRole("button", { name: "Model: DeepSeek V4.1 Flash" });
    expect(button).toHaveTextContent("Low");
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("radio", { name: "Max" }));
    expect(onSettings).toHaveBeenLastCalledWith("deepseek-flash", { reasoning_effort: "max" });
    expect(screen.getByRole("radio", { name: "128K" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("radio", { name: "1M" }));
    expect(onSettings).toHaveBeenLastCalledWith("deepseek-flash", { context_window_tokens: 1_000_000 });
    fireEvent.click(screen.getByRole("radio", { name: "GLM 5.3 Flash" }));
    expect(onSelect).toHaveBeenCalledWith("glm-5.3");
  });

  test("a model without thinking or 1M shows neither control", () => {
    render(<AgentModelMenu model="glm-5.3" options={[flash, glm]} onSelect={vi.fn()} onSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: GLM 5.3 Flash" }));
    expect(screen.queryByRole("radiogroup", { name: "Thinking" })).not.toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Context" })).not.toBeInTheDocument();
  });

  test("Escape closes the menu", () => {
    render(<AgentModelMenu model="deepseek-flash" options={[flash]} onSelect={vi.fn()} onSettings={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Model: DeepSeek V4.1 Flash" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
