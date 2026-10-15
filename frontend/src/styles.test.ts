import { readFileSync } from "node:fs";
import { expect, test } from "vitest";

const stylesheet = readFileSync("src/styles.css", "utf8");
const lineageStylesheet = readFileSync("src/lineage/tokens/lineage.css", "utf8");
const panelHostStylesheet = readFileSync("src/workbench/panelHost.css", "utf8");

test("checkboxes do not inherit text-field dimensions from the global input rule", () => {
  expect(stylesheet).toMatch(
    /input:not\(\[type="checkbox"\]\):not\(\[type="radio"\]\),\s*select\s*\{[\s\S]*?min-height: 36px;[\s\S]*?width: 100%;/,
  );
  expect(stylesheet).toContain(
    ':where(input[type="checkbox"], input[type="radio"])',
  );
});

test("right panel tabs match the existing version-row separator without styling the version row", () => {
  expect(lineageStylesheet).not.toContain(".workbench-shell .wb-run-version-picker");
  expect(stylesheet).toMatch(
    /\.wb-run-version-picker \{[^\n]*flex-wrap: wrap;[^\n]*padding: 6px 12px;/,
  );
  const panelStrip = lineageStylesheet.match(
    /\.panel-host-tabs \.detail-tabs__strip--compact \{([\s\S]*?)\n\}/,
  )?.[1] ?? "";
  expect(panelStrip).toContain("align-items: center;");
  expect(panelStrip).toContain("block-size: 48px;");
  expect(panelStrip).toContain("box-sizing: content-box;");
  expect(panelStrip).toContain("min-block-size: 48px;");
  expect(panelStrip).toContain("max-block-size: 48px;");
  expect(panelStrip).toContain("padding: 0 6px;");
});

test("floating node controls use the Report review header baseline", () => {
  const floatingDrawer = panelHostStylesheet.match(
    /\.node-panel-floating \.detail-drawer \{([\s\S]*?)\n\}/,
  )?.[1] ?? "";
  const floatingToolbar = panelHostStylesheet.match(
    /\.node-panel-floating \.detail-header-toolbar \{([\s\S]*?)\n\}/,
  )?.[1] ?? "";

  expect(floatingDrawer).toContain("padding-top: 12px !important;");
  expect(floatingToolbar).toContain("align-items: flex-start !important;");
});

test("scrollbars share one treatment and stay hidden until something scrolls", () => {
  const tokens = readFileSync("src/theme/tokens.css", "utf8");
  const scrollbars = readFileSync("src/theme/scrollbars.css", "utf8");
  expect(tokens).toMatch(/--scrollbar-thumb: #C9C8C3;/);
  expect(tokens).toMatch(/--scrollbar-thumb: rgba\(196, 200, 206, 0\.72\);/);
  expect(scrollbars).toContain("scrollbar-color: transparent transparent;");
  expect(scrollbars).toContain("[data-scrolling] {");
  expect(scrollbars).toContain("scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);");
  // No second, always-visible treatment left behind.
  expect(lineageStylesheet).not.toContain("scrollbar-color");
});

test("floating node chrome uses compact square controls and four resize corners", () => {
  expect(panelHostStylesheet).toContain("resize: none;");
  expect(panelHostStylesheet).toContain(".node-action-menu__trigger");
  expect(panelHostStylesheet).toContain("min-width: 27px;");
  expect(panelHostStylesheet).toContain("min-height: 27px;");
  expect(panelHostStylesheet).toContain(".node-panel-floating .panel-window-drag-handle");
  for (const corner of ["top-left", "top-right", "bottom-left", "bottom-right"]) {
    expect(panelHostStylesheet).toContain(
      `.node-panel-floating__resize-handle--${corner}`,
    );
  }
});
