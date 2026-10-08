// v1.9.0 step 1 — design tokens are the only place colours are written.
//
// Measurement (recorded in devline v1-9-0 before any reduction was reported):
//   colour literal = #rgb[a] / #rrggbb[aa], rgb[a](<digit>…), hsl[a](<digit>…), oklch(<digit>…)
//   CSS:  counted outside custom-property definitions and outside comments;
//   TS:   counted inside string literals of non-test source files.
//   inline style = occurrences of `style={{` in non-test .tsx files.
// Baseline at tag v1.8.12: CSS 176, TS 96 (52 in the unused lineage/tokens/tokens.ts), inline 934.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, test } from "vitest";

const SRC = "src";
const TOKENS = "src/theme/tokens.css";
const INLINE_STYLE_CEILING = 934;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== "generated") walk(path, out);
    } else out.push(path);
  }
  return out;
}

const files = walk(SRC);
const isTest = (path: string) => /\.test\.tsx?$/.test(path);
const COLOUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(\s*\d|\bhsla?\(\s*\d|\boklch\(\s*\d/g;
const KEYWORD_COLOUR = /\b(?:white|black)\b(?!-)/g;

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ""));
}

function cssColourLiterals(): string[] {
  const hits: string[] = [];
  for (const path of files.filter((p) => p.endsWith(".css") && p !== TOKENS)) {
    stripComments(readFileSync(path, "utf8")).split("\n").forEach((line, index) => {
      if (/^\s*--[\w-]+\s*:/.test(line)) return;
      for (const match of line.match(COLOUR) ?? []) hits.push(`${relative(SRC, path)}:${index + 1} ${match}`);
      for (const decl of line.matchAll(/:\s*([^;{}]*)/g)) {
        for (const match of decl[1].match(KEYWORD_COLOUR) ?? []) hits.push(`${relative(SRC, path)}:${index + 1} ${match}`);
      }
    });
  }
  return hits;
}

function tsColourLiterals(): string[] {
  const hits: string[] = [];
  const stringLiteral = /(["'`])((?:\\.|(?!\1)[^\\])*)\1/g;
  for (const path of files.filter((p) => /\.tsx?$/.test(p) && !isTest(p))) {
    readFileSync(path, "utf8").split("\n").forEach((line, index) => {
      for (const literal of line.matchAll(stringLiteral)) {
        for (const match of literal[2].match(COLOUR) ?? []) hits.push(`${relative(SRC, path)}:${index + 1} ${match}`);
        if (/^(white|black)$|\s(white|black)$/.test(literal[2])) hits.push(`${relative(SRC, path)}:${index + 1} ${literal[2]}`);
      }
    });
  }
  return hits;
}

// Custom properties a component sets at runtime (positions, per-node colour)
// rather than reading from the theme; a trailing "-" is a prefix completed in code.
const RUNTIME_VARS = [
  "--node-panel-left", "--node-panel-top",
  "--report-preview-left", "--report-preview-top",
  "--report-review-left", "--report-review-top",
  "--role-color", "--node-color", "--agent-ring-progress",
  "--ws-map", "--ws-agent",
  "--role-", "--stage-",
];

function undefinedVars(defined: Set<string>): string[] {
  const hits: string[] = [];
  for (const path of files.filter((p) => /\.(css|tsx?)$/.test(p) && !isTest(p))) {
    const text = readFileSync(path, "utf8");
    // A stylesheet may define its own component-local variables (e.g. a depth).
    const local = new Set(path.endsWith(".css") ? [...text.matchAll(/(?:^|[;{\s])(--[\w-]+)\s*:/g)].map((m) => m[1]) : []);
    text.split("\n").forEach((line, index) => {
      for (const match of line.matchAll(/var\(\s*(--[\w-]+)/g)) {
        const name = match[1];
        if (defined.has(name) || local.has(name) || RUNTIME_VARS.includes(name)) continue;
        hits.push(`${relative(SRC, path)}:${index + 1} ${name}`);
      }
    });
  }
  return hits;
}

function inlineStyleCount(): number {
  return files
    .filter((p) => p.endsWith(".tsx") && !isTest(p))
    .reduce((sum, path) => sum + (readFileSync(path, "utf8").match(/style=\{\{/g)?.length ?? 0), 0);
}

// ---------------------------------------------------------------------------
// Token blocks

type Theme = "light" | "dark";
const tokensCss = stripComments(readFileSync(TOKENS, "utf8"));

function block(selector: RegExp): Map<string, string> {
  const body = tokensCss.match(selector)?.[1];
  if (!body) throw new Error(`token block not found: ${selector}`);
  const map = new Map<string, string>();
  for (const decl of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) map.set(decl[1], decl[2].trim());
  return map;
}

const shared = block(/^:root \{([\s\S]*?)^\}/m);
const themes: Record<Theme, Map<string, string>> = {
  light: block(/^:root,\s*:root\[data-theme="light"\] \{([\s\S]*?)^\}/m),
  dark: block(/^:root\[data-theme="dark"\] \{([\s\S]*?)^\}/m),
};

function resolve(theme: Theme, name: string, depth = 0): string {
  const value = themes[theme].get(name) ?? shared.get(name);
  if (value === undefined) throw new Error(`${theme}: ${name} is not defined`);
  const alias = value.match(/^var\((--[\w-]+)\)$/);
  if (alias && depth < 8) return resolve(theme, alias[1], depth + 1);
  return value;
}

// OKLCH → linear sRGB (Björn Ottosson's reference matrices), clipped to gamut.
function oklchToLinearSrgb(l: number, c: number, hue: number): number[] {
  const h = (hue * Math.PI) / 180;
  const a = c * Math.cos(h);
  const b = c * Math.sin(h);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
    -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
    -0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_,
  ].map((v) => Math.min(1, Math.max(0, v)));
}

function luminance(value: string): number {
  const oklch = value.match(/^oklch\(([\d.]+) ([\d.]+) ([\d.]+)\)$/);
  if (oklch) {
    const [r, g, b] = oklchToLinearSrgb(Number(oklch[1]), Number(oklch[2]), Number(oklch[3]));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }
  const match = value.match(/^#([0-9a-fA-F]{6})$/);
  if (!match) throw new Error(`expected #rrggbb or oklch(l c h), got ${value}`);
  const channel = (offset: number) => {
    const c = parseInt(match[1].slice(offset, offset + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4);
}

function contrast(theme: Theme, fg: string, bg: string): number {
  const a = luminance(resolve(theme, fg));
  const b = luminance(resolve(theme, bg));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const SURFACES = ["--bg-canvas", "--bg-card", "--bg-card-2", "--bg-elev"];
const TEXT = ["--label", "--label-secondary", "--label-tertiary", "--tint"];
const PAIRS: Array<[string, string]> = [
  ...TEXT.flatMap((fg) => SURFACES.map((bg): [string, string] => [fg, bg])),
  ["--on-tint", "--tint-fill"],
  ["--on-tint", "--blocker"],
  ["--tint-label", "--tint-bg"],
  ["--status-holds-fg", "--status-holds-bg"],
  ["--status-caution-fg", "--status-caution-bg"],
  ["--status-fails-fg", "--status-fails-bg"],
  ["--status-argued-fg", "--status-argued-bg"],
  ["--badge-ok-fg", "--badge-ok-bg"],
  ["--badge-warn-fg", "--badge-warn-bg"],
  ["--badge-neutral-fg", "--badge-neutral-bg"],
  ["--panel-error-fg", "--panel-error-bg"],
  ["--hint-warn-fg", "--hint-warn-bg"],
  ["--field-error-fg", "--field-bg"],
  ["--label", "--field-bg"],
  ["--label", "--panel-bg"],
  ...[...themes.light.keys()].filter((name) => name.startsWith("--role-")).map((role): [string, string] => ["--on-role", role]),
];

describe("design tokens", () => {
  test("light and dark define the same tokens", () => {
    expect([...themes.dark.keys()].sort()).toEqual([...themes.light.keys()].sort());
  });

  test.each(["light", "dark"] as const)("%s: text on its surfaces reaches 4.5:1", (theme) => {
    const failing = PAIRS.map(([fg, bg]) => ({ fg, bg, ratio: contrast(theme, fg, bg) }))
      .filter((pair) => pair.ratio < 4.5)
      .map((pair) => `${pair.fg} on ${pair.bg}: ${pair.ratio.toFixed(2)}`);
    expect(failing).toEqual([]);
  });

  test("focus ring is visible against every surface (3:1)", () => {
    for (const theme of ["light", "dark"] as const) {
      for (const bg of SURFACES) expect(contrast(theme, "--focus-ring", bg)).toBeGreaterThanOrEqual(3);
    }
  });

  test("reduced motion and reduced transparency are honoured", () => {
    expect(tokensCss).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(tokensCss).toMatch(/@media \(prefers-reduced-transparency: reduce\)/);
  });
});

describe("colour and inline-style ratchets", () => {
  test("no colour literals in stylesheets outside tokens.css", () => {
    expect(cssColourLiterals()).toEqual([]);
  });

  test("no colour literals in TypeScript", () => {
    expect(tsColourLiterals()).toEqual([]);
  });

  test("every var() reads a token defined in tokens.css", () => {
    const defined = new Set([...shared.keys(), ...themes.light.keys(), ...themes.dark.keys()]);
    expect(undefinedVars(defined)).toEqual([]);
  });

  test("inline styles only go down", () => {
    expect(inlineStyleCount()).toBeLessThanOrEqual(INLINE_STYLE_CEILING);
  });
});
