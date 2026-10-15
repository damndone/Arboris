import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ContextUsageRing } from "./ContextUsageRing";

describe("context ring", () => {
  it("says when the window is assumed and when the conversation will be summarized", () => {
    render(<ContextUsageRing used={30_000} remaining={34_000} total={64_000} assumed compactAt={47_616} />);
    fireEvent.mouseEnter(screen.getByTestId("agent-context-ring"));
    const details = screen.getByTestId("agent-context-tooltip");
    expect(details).toHaveTextContent("64,000 (assumed)");
    expect(details).toHaveTextContent("Summarized at47,616");
    expect(details).toHaveTextContent("The model declares no context window");
    expect(screen.queryByRole("button", { name: "Summarize earlier conversation" })).toBeNull();
  });

  it("pins its details on click, with a summarize-now action", () => {
    const onCompact = vi.fn();
    render(<ContextUsageRing used={10} remaining={90} total={100} onCompact={onCompact} />);
    const ring = screen.getByRole("button", { name: /Context usage: 10%/ });
    fireEvent.click(ring);
    expect(ring).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "Summarize earlier conversation" }));
    expect(onCompact).toHaveBeenCalledOnce();
    expect(ring).toHaveAttribute("aria-expanded", "false");
  });
});
