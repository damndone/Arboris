// frontend/src/lineage/hooks/useGraphKeyboard.test.tsx
import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useGraphKeyboard } from "./useGraphKeyboard";

interface HarnessProps {
  onToggleRawJson: () => void;
  onEscape: () => void;
  onCmdK: () => void;
  enabled?: boolean;
}

function Harness(props: HarnessProps) {
  useGraphKeyboard(props);
  return null;
}

function dispatch(key: string, opts: KeyboardEventInit = {}): void {
  fireEvent.keyDown(window, { key, ...opts });
}

describe("useGraphKeyboard", () => {
  it("⌘J fires onToggleRawJson", () => {
    const toggle = vi.fn();
    render(
      <Harness
        onToggleRawJson={toggle}
        onEscape={vi.fn()}
        onCmdK={vi.fn()}
      />,
    );
    dispatch("j", { metaKey: true });
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it("Ctrl+J fires onToggleRawJson (cross-platform)", () => {
    const toggle = vi.fn();
    render(
      <Harness
        onToggleRawJson={toggle}
        onEscape={vi.fn()}
        onCmdK={vi.fn()}
      />,
    );
    dispatch("j", { ctrlKey: true });
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it("⌘K fires onCmdK", () => {
    const cmdK = vi.fn();
    render(
      <Harness
        onToggleRawJson={vi.fn()}
        onEscape={vi.fn()}
        onCmdK={cmdK}
      />,
    );
    dispatch("k", { metaKey: true });
    expect(cmdK).toHaveBeenCalledTimes(1);
  });

  it("Escape fires onEscape", () => {
    const esc = vi.fn();
    render(
      <Harness
        onToggleRawJson={vi.fn()}
        onEscape={esc}
        onCmdK={vi.fn()}
      />,
    );
    dispatch("Escape");
    expect(esc).toHaveBeenCalledTimes(1);
  });

  it("plain 'j' (no modifier) fires NOTHING", () => {
    const toggle = vi.fn();
    render(
      <Harness
        onToggleRawJson={toggle}
        onEscape={vi.fn()}
        onCmdK={vi.fn()}
      />,
    );
    dispatch("j");
    expect(toggle).not.toHaveBeenCalled();
  });

  it.each([
    ["r", { metaKey: true }],          // ⌘R — reserved for V1.5.2
    ["r", { metaKey: true, shiftKey: true }], // ⇧⌘R — reserved for V1.6
    ["/", { metaKey: true }],          // ⌘/ — reserved
  ] as const)(
    "reserved shortcut %p fires nothing (spec §12)",
    (key, mods) => {
      const handlers = {
        onToggleRawJson: vi.fn(),
        onEscape: vi.fn(),
        onCmdK: vi.fn(),
      };
      render(<Harness {...handlers} />);
      dispatch(key, mods);
      expect(handlers.onToggleRawJson).not.toHaveBeenCalled();
      expect(handlers.onEscape).not.toHaveBeenCalled();
      expect(handlers.onCmdK).not.toHaveBeenCalled();
    },
  );

  it("enabled=false detaches listener (no callbacks fire)", () => {
    const toggle = vi.fn();
    render(
      <Harness
        onToggleRawJson={toggle}
        onEscape={vi.fn()}
        onCmdK={vi.fn()}
        enabled={false}
      />,
    );
    dispatch("j", { metaKey: true });
    dispatch("Escape");
    expect(toggle).not.toHaveBeenCalled();
  });

  it("unmount removes the keydown listener", () => {
    const toggle = vi.fn();
    const { unmount } = render(
      <Harness
        onToggleRawJson={toggle}
        onEscape={vi.fn()}
        onCmdK={vi.fn()}
      />,
    );
    dispatch("j", { metaKey: true });
    expect(toggle).toHaveBeenCalledTimes(1);
    unmount();
    dispatch("j", { metaKey: true });
    expect(toggle).toHaveBeenCalledTimes(1); // no second call
  });
});
