// frontend/src/workbench/keyboard.ts
//
// V1.5.3 F4 — shared keyboard helpers.
//
// `isEditableTarget` answers "is the user currently typing into an
// editable element?" Global keydown listeners (⌘K search palette in
// F4, the shortcut dispatcher in F6, the command palette in F7) must
// NOT swallow keystrokes while the user is editing text in an input,
// textarea, or contenteditable region — otherwise typing a literal
// "k" in the detail drawer would be hijacked to open search.
//
// Kept dependency-free and DOM-only so every keyboard surface can
// share one definition of "editable".

/**
 * True when the given element (typically `document.activeElement` or
 * an event target) is a text-editing surface that should receive
 * keystrokes uninterrupted.
 *
 * Covers:
 *   - <input> of a text-like type (excludes button/checkbox/radio/…)
 *   - <textarea>
 *   - <select> (arrow/typeahead navigation is the element's own)
 *   - any element inside a contenteditable subtree
 */
export function isEditableTarget(el: EventTarget | Element | null): boolean {
  if (el === null || !(el instanceof Element)) return false;

  const tag = el.tagName;

  if (tag === "TEXTAREA" || tag === "SELECT") return true;

  if (tag === "INPUT") {
    const type = (el as HTMLInputElement).type.toLowerCase();
    // Non-text input types (buttons, checkboxes, etc.) don't capture
    // typed characters, so a global shortcut over them is fine.
    const nonText = new Set([
      "button",
      "submit",
      "reset",
      "checkbox",
      "radio",
      "range",
      "color",
      "file",
      "image",
    ]);
    return !nonText.has(type);
  }

  // contenteditable — check the attribute on the element or any
  // ancestor. We read the attribute rather than `isContentEditable`
  // because jsdom doesn't implement the latter, and the attribute
  // form ("" or "true" means on, "false" means off) is what authors
  // actually set. `closest` handles the nested-child case where the
  // event target is inside an editable region.
  const editable = el.closest("[contenteditable]");
  if (editable !== null) {
    const v = editable.getAttribute("contenteditable");
    if (v === "" || v === "true" || v === "plaintext-only") return true;
  }

  return false;
}
