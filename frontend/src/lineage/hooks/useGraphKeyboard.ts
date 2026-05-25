// frontend/src/lineage/hooks/useGraphKeyboard.ts
//
// V1.5.0 lineage keyboard bindings (Step 5, T5.3).
//
// Wires the three shortcuts that ship in V1.5.0 (spec §12):
//   - ⌘J / Ctrl+J → onToggleRawJson()
//   - Escape       → onEscape()
//   - ⌘K / Ctrl+K → onCmdK()  (forwarded to parent search palette)
//
// EXPLICITLY NOT BOUND in V1.5.0 (spec §12, plan §8 T5.3):
//   - ⌘R, ⇧⌘R, ⌘/  — these are reserved for V1.5.2 / V1.6 features; we
//     register no listener for them so they continue to fall through to
//     browser defaults / future feature work. No console messages, no
//     UI affordances. Wiring belongs to the version that ships the feature.

import { useEffect } from "react";

export interface UseGraphKeyboardOptions {
  /** Called when ⌘J or Ctrl+J is pressed. */
  onToggleRawJson: () => void;
  /** Called when Escape is pressed. */
  onEscape: () => void;
  /** Called when ⌘K or Ctrl+K is pressed (forwarded to parent search palette). */
  onCmdK: () => void;
  /** Allows the hook to be disabled (e.g. when a modal is open). Default: true. */
  enabled?: boolean;
}

/**
 * Attaches a single window-level keydown listener for the three V1.5.0
 * lineage shortcuts. All other modifier+key combinations pass through.
 */
export function useGraphKeyboard(opts: UseGraphKeyboardOptions): void {
  const { onToggleRawJson, onEscape, onCmdK, enabled = true } = opts;

  useEffect(() => {
    if (!enabled) return undefined;

    const onKey = (e: KeyboardEvent): void => {
      const cmd = e.metaKey || e.ctrlKey;
      const key = e.key.toLowerCase();

      if (cmd && key === "j") {
        e.preventDefault();
        onToggleRawJson();
        return;
      }
      if (cmd && key === "k") {
        e.preventDefault();
        onCmdK();
        return;
      }
      if (key === "escape") {
        // Don't preventDefault on Escape — other components (modals,
        // dropdowns) may also listen and we don't want to swallow their
        // legitimate dismissal handling. We just notify our caller.
        onEscape();
        return;
      }
      // Everything else (⌘R, ⌘/, ⇧⌘R, plain letters, etc.) is intentionally
      // ignored. Do not add bindings here without updating spec §12.
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onToggleRawJson, onEscape, onCmdK, enabled]);
}
