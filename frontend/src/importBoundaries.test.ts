// @vitest-environment node
/**
 * The cross-layer import boundaries in eslint.config.js (RESTRICTED_IMPORTS) hold, and each one
 * catches every import form with a message that names the public interface to use instead.
 * `npm run lint` and the gate run the same configuration over the whole tree.
 */
import path from "node:path";
import { ESLint } from "eslint";
import { describe, expect, test } from "vitest";

const FRONTEND = path.resolve(__dirname, "..");
const eslint = new ESLint({ cwd: FRONTEND });

async function lint(filePath: string, text: string): Promise<string[]> {
  const [result] = await eslint.lintText(text, { filePath: path.join(FRONTEND, filePath) });
  return result.messages.map((message) => `${message.ruleId ?? "eslint"}: ${message.message}`);
}

test("the source tree has no lint errors or warnings", async () => {
  const results = await eslint.lintFiles(["src"]);
  const found = results.flatMap((result) => result.messages.map((message) =>
    `${path.relative(FRONTEND, result.filePath)}:${message.line}: ${message.message}`));
  expect(found).toEqual([]);
}, 60_000);

describe("generated/api-schema stays behind src/apiTypes.ts", () => {
  test.each([
    ["static type import", "src/report/A.tsx", 'import type { components } from "../generated/api-schema";\n'],
    ["static .js import", "src/report/A.tsx", 'import type { components } from "../generated/api-schema.js";\n'],
    ["static .ts import", "src/report/A.tsx", 'import type { components } from "../generated/api-schema.ts";\n'],
    ["value import", "src/report/B.ts", 'import { paths } from "../generated/api-schema";\n'],
    ["re-export", "src/report/C.ts", 'export type { paths } from "../generated/api-schema";\n'],
    ["star re-export", "src/report/D.ts", 'export * from "../generated/api-schema";\n'],
    ["dynamic import", "src/report/E.ts", 'export const load = () => import("../generated/api-schema");\n'],
    ["dynamic template import", "src/report/E.ts", 'export const load = () => import(`../generated/api-schema`);\n'],
    ["dynamic template .js import", "src/report/E.ts", 'export const load = () => import(`../generated/api-schema.js`);\n'],
    ["type query", "src/report/F.ts", 'export type P = import("../generated/api-schema").paths;\n'],
    ["type query with .js extension", "src/report/F.ts", 'export type P = import("../generated/api-schema.js").paths;\n'],
  ])("a %s is flagged and the message says what to use", async (_form, filePath, text) => {
    const messages = await lint(filePath, text);
    expect(messages).toHaveLength(1);
    expect(messages[0]).toContain("src/apiTypes.ts");
  });

  test("apiTypes.ts itself, tests and look-alike names are not flagged", async () => {
    expect(await lint("src/apiTypes.ts", 'import type { components } from "./generated/api-schema";\n')).toEqual([]);
    expect(await lint("src/report/A.test.ts", 'import type { components } from "../generated/api-schema";\n')).toEqual([]);
    expect(await lint("src/report/A.ts", 'export const load = () => import("../generated/api-schema-v2");\n')).toEqual([]);
    expect(await lint("src/report/A.ts", 'export const load = () => import(`../generated/api-schema-v2.js`);\n')).toEqual([]);
    expect(await lint("src/report/A.ts", 'import type { Schema } from "../apiTypes.js";\n')).toEqual([]);
  });

  test("an inline disable comment does not waive a boundary", async () => {
    const messages = await lint("src/report/A.ts",
      '// eslint-disable-next-line\nimport type { components } from "../generated/api-schema";\n');
    expect(messages.some((message) => message.includes("src/apiTypes.ts"))).toBe(true);
  });
});

describe("HTTP transport modules stay behind src/api.ts", () => {
  test.each([
    'import { uploadDataset } from "../apiGraph";\n',
    'export { exportDataset } from "../apiExports.js";\n',
    'export const load = () => import(`../apiGraph.ts`);\n',
    'export type Result = import("../apiExports").DatasetExportResult;\n',
  ])("flags a direct transport import with the public entry point", async (text) => {
    expect(await lint("src/report/Review.ts", text)).toEqual([
      expect.stringContaining("from src/api.ts"),
    ]);
  });

  test("the facade can load its transport modules and still uses public schema types", async () => {
    expect(await lint("src/api.ts", 'export * from "./apiGraph";\n')).toEqual([]);
    expect(await lint("src/api.ts", 'import type { paths } from "./generated/api-schema";\n')).toEqual([
      expect.stringContaining("src/apiTypes.ts"),
    ]);
    expect(await lint("src/report/Review.ts", 'import { uploadDataset } from "../api";\n')).toEqual([]);
    expect(await lint("src/report/Review.ts", 'import type { paths } from "../generated/api-schema";\n')).toEqual([
      expect.stringContaining("src/apiTypes.ts"),
    ]);
  });
});

test("every boundary names where it came from and what to use instead", async () => {
  const configPath = path.join(FRONTEND, "eslint.config.js");
  const { RESTRICTED_IMPORTS } = (await import(/* @vite-ignore */ configPath)) as {
    RESTRICTED_IMPORTS: { origin: string; patterns: { message: string }[] }[];
  };
  expect(RESTRICTED_IMPORTS.length).toBeGreaterThan(0);
  for (const boundary of RESTRICTED_IMPORTS) {
    expect(boundary.origin.trim()).not.toBe("");
    for (const pattern of boundary.patterns) expect(pattern.message).toMatch(/\b(from|use)\b/i);
  }
});
