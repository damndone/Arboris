// frontend/src/lineage/modals/RawJsonModal.test.tsx
//
// Spec §9.3 — 6 required tests for the V1.5.0 Raw JSON modal. Subsumes
// V1.4.1 LineageTab.test.tsx::"opens and closes Raw JSON with the global
// Cmd+J shortcut" (see equivalence map in T5.8 commit body).

import "@testing-library/jest-dom/vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RAW_JSON_TITLE_ID, RawJsonModal } from "./RawJsonModal";
import { useGraphKeyboard } from "../hooks/useGraphKeyboard";
import type { GraphViewNode } from "../api/graphViewTypes";

function makeNode(overrides: Partial<GraphViewNode> = {}): GraphViewNode {
  return {
    id: "n1",
    nodeKey: "n1",
    raw: { id: "n1", kind: "model", display_label: "Primary OLS" },
    stage: "model",
    kind: "model",
    title: "Primary OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    createdAt: "2026-05-22T00:00:00Z",
    ...overrides,
  };
}

const writeText = vi.fn();
let _origClipboard: PropertyDescriptor | undefined;
beforeEach(() => {
  writeText.mockReset().mockResolvedValue(undefined);
  _origClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
});

afterEach(() => {
  // REV-3 S2: restore clipboard so other test files don't inherit our mock.
  if (_origClipboard) {
    Object.defineProperty(navigator, "clipboard", _origClipboard);
  } else {
    delete (navigator as { clipboard?: unknown }).clipboard;
  }
  vi.useRealTimers();
});

/**
 * Wiring harness that combines useGraphKeyboard + RawJsonModal — same
 * shape GraphWorkbench will use in T6.11. Lets us assert the spec §9.3
 * "opens via ⌘J / closes via ⌘J toggle" contract end-to-end.
 */
function Harness({ node }: { node: GraphViewNode }) {
  const [open, setOpen] = useState(false);
  useGraphKeyboard({
    onToggleRawJson: () => setOpen((v) => !v),
    onEscape: () => {
      /* parent would clear selection — modal handles its own Escape */
    },
    onCmdK: () => {},
  });
  return (
    <RawJsonModal open={open} onClose={() => setOpen(false)} node={node} />
  );
}

describe("RawJsonModal (spec §9.3 — 6 required tests)", () => {
  it("1. Opens via ⌘J when a node is selected", async () => {
    render(<Harness node={makeNode()} />);
    expect(screen.queryByTestId("raw-json-modal")).toBeNull();
    fireEvent.keyDown(window, { key: "j", metaKey: true });
    await waitFor(() =>
      expect(screen.getByTestId("raw-json-modal")).toBeInTheDocument(),
    );
  });

  it("2. Closes via ⌘J again (toggle)", async () => {
    render(<Harness node={makeNode()} />);
    fireEvent.keyDown(window, { key: "j", metaKey: true }); // open
    await waitFor(() =>
      expect(screen.getByTestId("raw-json-modal")).toBeInTheDocument(),
    );
    fireEvent.keyDown(window, { key: "j", metaKey: true }); // close
    await waitFor(() => expect(screen.queryByTestId("raw-json-modal")).toBeNull());
  });

  it("3. Closes via Escape", async () => {
    const onClose = vi.fn();
    render(<RawJsonModal open={true} onClose={onClose} node={makeNode()} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("4. Closes via close button", () => {
    const onClose = vi.fn();
    render(<RawJsonModal open={true} onClose={onClose} node={makeNode()} />);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("5. Copy button writes pretty-printed JSON to clipboard", async () => {
    render(<RawJsonModal open={true} onClose={vi.fn()} node={makeNode()} />);
    fireEvent.click(screen.getByRole("button", { name: /copy raw json/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const written = writeText.mock.calls[0][0] as string;
    expect(written).toContain('"id": "n1"');
    expect(written).toContain('"display_label": "Primary OLS"');
    // Pretty-printed → newlines present (2-space indent → at least one newline)
    expect(written).toContain("\n");
  });

  it("6. Does not render dangerouslySetInnerHTML highlighter (anti-regression)", () => {
    const { container } = render(
      <RawJsonModal open={true} onClose={vi.fn()} node={makeNode()} />,
    );
    // The prototype hand-rolled JSON highlighter injected specific class
    // names: json-key, json-string, json-number, json-bool. V1.5.0 modal
    // uses plain <pre>{string}</pre>, so none of those markers should
    // appear. Tighter than `<span class=` per REV-2 #10 — that pattern
    // could false-pass on unrelated future styling.
    expect(container.outerHTML).not.toContain("json-key");
    expect(container.outerHTML).not.toContain("json-string");
    expect(container.outerHTML).not.toContain("json-number");
    expect(container.outerHTML).not.toContain("json-bool");
  });

  // Supplementary tests beyond spec §9.3, kept lightweight:

  it("aria-labelledby points at RAW_JSON_TITLE_ID + heading element exists", () => {
    render(<RawJsonModal open={true} onClose={vi.fn()} node={makeNode()} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-labelledby")).toBe(RAW_JSON_TITLE_ID);
    expect(document.getElementById(RAW_JSON_TITLE_ID)).not.toBeNull();
  });

  it("open=false → renders null", () => {
    const { container } = render(
      <RawJsonModal open={false} onClose={vi.fn()} node={makeNode()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("open=true + node=null → renders null (defensive)", () => {
    const { container } = render(
      <RawJsonModal open={true} onClose={vi.fn()} node={null} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("backdrop click closes; card click does not", () => {
    const onClose = vi.fn();
    render(<RawJsonModal open={true} onClose={onClose} node={makeNode()} />);
    const dialog = screen.getByRole("dialog");
    // Click the backdrop (dialog element itself)
    fireEvent.click(dialog);
    expect(onClose).toHaveBeenCalledTimes(1);
    // Click inside the card body should NOT close
    fireEvent.click(screen.getByTestId("raw-json-body"));
    expect(onClose).toHaveBeenCalledTimes(1); // unchanged
  });
});
