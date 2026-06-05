// frontend/src/workbench/keyboard.test.ts
//
// V1.5.3 F4 — isEditableTarget unit coverage.

import { describe, expect, it } from "vitest";
import { isEditableTarget } from "./keyboard";

function input(type?: string): HTMLInputElement {
  const el = document.createElement("input");
  if (type) el.type = type;
  return el;
}

describe("isEditableTarget", () => {
  it("returns false for null / non-Element", () => {
    expect(isEditableTarget(null)).toBe(false);
    expect(isEditableTarget({} as unknown as EventTarget)).toBe(false);
  });

  it("returns true for textarea and select", () => {
    expect(isEditableTarget(document.createElement("textarea"))).toBe(true);
    expect(isEditableTarget(document.createElement("select"))).toBe(true);
  });

  it("returns true for text-like inputs", () => {
    expect(isEditableTarget(input())).toBe(true); // default type=text
    expect(isEditableTarget(input("text"))).toBe(true);
    expect(isEditableTarget(input("search"))).toBe(true);
    expect(isEditableTarget(input("email"))).toBe(true);
    expect(isEditableTarget(input("number"))).toBe(true);
    expect(isEditableTarget(input("password"))).toBe(true);
  });

  it("returns false for non-text input types", () => {
    expect(isEditableTarget(input("checkbox"))).toBe(false);
    expect(isEditableTarget(input("radio"))).toBe(false);
    expect(isEditableTarget(input("button"))).toBe(false);
    expect(isEditableTarget(input("submit"))).toBe(false);
    expect(isEditableTarget(input("range"))).toBe(false);
    expect(isEditableTarget(input("file"))).toBe(false);
  });

  it("returns true for contenteditable elements and their children", () => {
    const div = document.createElement("div");
    div.setAttribute("contenteditable", "true");
    const child = document.createElement("span");
    div.appendChild(child);
    expect(isEditableTarget(div)).toBe(true);
    // A node nested inside the editable region also counts.
    expect(isEditableTarget(child)).toBe(true);
  });

  it("returns false for contenteditable=false", () => {
    const div = document.createElement("div");
    div.setAttribute("contenteditable", "false");
    expect(isEditableTarget(div)).toBe(false);
  });

  it("returns false for ordinary non-editable elements", () => {
    expect(isEditableTarget(document.createElement("div"))).toBe(false);
    expect(isEditableTarget(document.createElement("button"))).toBe(false);
    expect(isEditableTarget(document.createElement("span"))).toBe(false);
  });
});
