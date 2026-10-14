// v1.9.0 — every class a stylesheet styles is named somewhere in the code.
// A rule for a class nothing renders is dead weight in the bundle (26 such
// classes, ~270 lines, were removed when this check was added).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { expect, test } from "vitest";

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) {
      if (name !== "generated") walk(path, out);
    } else out.push(path);
  }
  return out;
}

// Classes rendered by a library rather than by our components.
const LIBRARY = /^react-flow__/;

test("every styled class is used by a component", () => {
  const files = walk("src");
  const code = files.filter((path) => /\.tsx?$/.test(path)).map((path) => readFileSync(path, "utf8")).join("\n");
  const names = new Set(code.match(/[A-Za-z_][\w-]*/g));
  // Class names completed at runtime: `prefix-${value}` or "prefix-" + value.
  const prefixes = [...code.matchAll(/([A-Za-z_][\w-]*-)(?:\$\{|["']\s*\+)/g)].map((match) => match[1]);
  const unused: string[] = [];
  for (const path of files.filter((p) => p.endsWith(".css"))) {
    const css = readFileSync(path, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\{[^{}]*\}/g, "{}");
    for (const [, name] of css.matchAll(/\.([A-Za-z_][\w-]*)/g)) {
      if (names.has(name) || LIBRARY.test(name) || prefixes.some((prefix) => name.startsWith(prefix))) continue;
      unused.push(`${relative("src", path)} .${name}`);
    }
  }
  expect([...new Set(unused)]).toEqual([]);
});
