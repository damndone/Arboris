/**
 * Loader for the canonical v1.8.1 contract mocks.
 *
 * `tests/fixtures/contracts/v181/` is the UI lane's only data source for the
 * three locked packets (work order C, `read_only_contracts`). The files live
 * outside `frontend/`, and this repo's tsconfig does not enable
 * `resolveJsonModule` — and tsconfig.json is not a file this lane owns — so the
 * fixtures are read from disk rather than imported. That keeps the assertion
 * honest in a second way: the tests fail if the canonical mock changes shape,
 * instead of testing a hand-copied duplicate that has drifted.
 *
 * Test support only. No production module imports this file.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  parseEtsResult,
  parseNotebookOptionRevision,
  parseOptionExecution,
  type EtsResult,
  type NotebookOptionRevision,
  type OptionExecution,
} from "../contracts";

const FIXTURE_DIR = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../tests/fixtures/contracts/v181",
);

export type CanonicalFixtureName =
  | "notebook_option_revision"
  | "option_execution"
  | "ets_result";

export function readCanonicalFixture(
  name: CanonicalFixtureName,
): Record<string, unknown> {
  const text = readFileSync(resolve(FIXTURE_DIR, `${name}.json`), "utf8");
  return JSON.parse(text) as Record<string, unknown>;
}

export function canonicalOptionRevision(): NotebookOptionRevision {
  return parseNotebookOptionRevision(readCanonicalFixture("notebook_option_revision"));
}

export function canonicalOptionExecution(): OptionExecution {
  return parseOptionExecution(readCanonicalFixture("option_execution"));
}

export function canonicalEtsResult(): EtsResult {
  return parseEtsResult(readCanonicalFixture("ets_result"));
}
