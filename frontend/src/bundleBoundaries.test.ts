// v1.9.0 — what the first screen loads. A static import of any of these
// pulls it back into the chunk every visit parses (measured at 1.65 MB
// minified before the split; launcher entry plus React is now ~205 kB).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(path);
  }
  return out;
}

const sources = walk("src").map((path) => ({ path, text: readFileSync(path, "utf8") }));

// Module -> the only files allowed to import it statically.
const ON_DEMAND: Record<string, string[]> = {
  xlsx: [],
  // runDetail is itself a lazy route, so its import stays out of the entry.
  "./workbench/WorkbenchRouteContainer": ["src/runDetail.tsx"],
  "./runDetail": [],
  "./pipelineDrafts/DraftGraphRoute": [],
  "dataView/DataView": [],
  "report/ReportView": [],
  "notebook/NotebookRouteView": [],
  "views/TableView": [],
  "views/PipelineView": [],
};

test.each(Object.entries(ON_DEMAND))("%s is loaded on demand", (module, allowed) => {
  const tail = module.replace(/^\.\//, "");
  const pattern = new RegExp(`^import (?!type)[^;]*from "(?:[./]*/)?${tail.replace(/[/.]/g, "\\$&")}";`, "m");
  const offenders = sources.filter(({ path, text }) => pattern.test(text) && !allowed.includes(path)).map(({ path }) => path);
  expect(offenders).toEqual([]);
});
