// v1.9.0 — every source module is imported by application code, not only by
// its tests. A module kept alive by its own test is dead code that still costs
// type-checking and review (RunForm and six others, ~2,400 lines, were removed
// when this check was added).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, normalize } from "node:path";
import { expect, test } from "vitest";

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.tsx?$/.test(name)) out.push(path);
  }
  return out;
}

const isTest = (path: string) => /\.test\.tsx?$/.test(path);
const isFixture = (path: string) => /(^|\/)(__fixtures__|fixtures)\//.test(path) || path === "src/apiFixtures.ts";
const ENTRY = new Set(["src/main.tsx", "src/vite-env.d.ts", "src/generated/api-schema.ts"]);

test("every module is imported by application code", () => {
  const files = walk("src");
  const known = new Set(files);
  const used = new Set<string>();
  for (const path of files.filter((p) => !isTest(p) && !isFixture(p))) {
    const text = readFileSync(path, "utf8");
    for (const [, spec] of text.matchAll(/(?:from|import)\s*\(?\s*["'](\.[^"']+)["']/g)) {
      const base = normalize(join(dirname(path), spec));
      for (const candidate of [base, `${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`]) {
        if (known.has(candidate)) used.add(candidate);
      }
    }
  }
  const unreachable = files.filter((p) => !isTest(p) && !isFixture(p) && !ENTRY.has(p) && !used.has(p));
  expect(unreachable).toEqual([]);
});
