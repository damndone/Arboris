import type { CitableFact, ReportScope } from "./factTable";
import type { ReportFigure } from "./reportClient";
import type { ReportRecord } from "./reportHistory";
import type { ReportCapabilityManifestEntry } from "./reportEvidence";

/**
 * Report text is the only editable part of a report revision.  Run, scope,
 * fact, and figure values live in the source snapshot below and are never
 * accepted as an edit input.
 */
export const REPORT_DOCUMENT_SCHEMA_VERSION = "workbench.report.document/v1" as const;
export const REPORT_REVISION_SCHEMA_VERSION = "workbench.report.revision/v1" as const;

/** Recursive readonly view used for evidence snapshots. */
export type DeepReadonly<T> = T extends (...args: never[]) => unknown
  ? T
  : T extends readonly (infer Item)[]
    ? readonly DeepReadonly<Item>[]
    : T extends object
      ? { readonly [Key in keyof T]: DeepReadonly<T[Key]> }
      : T;

/**
 * Immutable evidence copied from one generated ReportRecord.
 *
 * This is intentionally a separate object from the editable Markdown.  It
 * is the provenance boundary: custom editing can create a new revision, but
 * cannot rewrite the Workbench Run, Artifact, scope, facts, or figures.
 */
export interface ReportEvidenceSnapshot {
  readonly source_record_id: string;
  readonly source_report_id: string;
  readonly source_run_id: string;
  readonly context_fingerprints: readonly string[];
  readonly capability_manifest: readonly DeepReadonly<ReportCapabilityManifestEntry>[];
  readonly scope: DeepReadonly<ReportScope>;
  readonly facts: readonly DeepReadonly<CitableFact>[];
  readonly figures: readonly DeepReadonly<ReportFigure>[];
  readonly excluded_fact_ids: readonly string[];
  readonly excluded_figure_ids: readonly string[];
}

export interface ReportRevision {
  readonly schema_version: typeof REPORT_REVISION_SCHEMA_VERSION;
  readonly revision_id: string;
  readonly document_id: string;
  readonly revision_number: number;
  readonly parent_revision_id?: string;
  readonly created_at: string;
  readonly markdown: string;
  readonly source: ReportEvidenceSnapshot;
}

export interface ReportDocument {
  readonly schema_version: typeof REPORT_DOCUMENT_SCHEMA_VERSION;
  readonly document_id: string;
  readonly source: ReportEvidenceSnapshot;
  readonly revisions: readonly ReportRevision[];
  readonly current_revision_id: string;
}

export interface CreateReportRevisionOptions {
  document_id?: string;
  revision_id?: string;
  revision_number?: number;
  created_at?: string;
  parent_revision_id?: string;
}

export interface CreateReportDocumentOptions {
  document_id?: string;
  revision_id?: string;
  created_at?: string;
}

export type ReportDocumentValidation =
  | { valid: true; document: ReportDocument; errors: readonly [] }
  | { valid: false; errors: readonly string[] };

export type ReportRevisionValidation =
  | { valid: true; revision: ReportRevision; errors: readonly [] }
  | { valid: false; errors: readonly string[] };

/**
 * Make a detached clone before freezing so the caller's ReportRecord is not
 * frozen or otherwise changed by document creation.
 */
function clone<T>(value: T): T {
  const structuredClone = (globalThis as typeof globalThis & {
    structuredClone?: <Value>(input: Value) => Value;
  }).structuredClone;
  if (structuredClone) return structuredClone(value);
  return JSON.parse(JSON.stringify(value)) as T;
}

function deepFreeze<T>(value: T, seen = new WeakSet<object>()): T {
  if (!value || typeof value !== "object") return value;
  const object = value as object;
  if (seen.has(object)) return value;
  seen.add(object);
  for (const child of Object.values(object as Record<string, unknown>)) {
    deepFreeze(child, seen);
  }
  return Object.freeze(value);
}

function detachedFrozen<T>(value: T): T {
  return deepFreeze(clone(value));
}

function sourceFromRecord(record: ReportRecord): ReportEvidenceSnapshot {
  return deepFreeze({
    source_record_id: record.id,
    source_report_id: record.id,
    source_run_id: record.scope.run_id,
    context_fingerprints: clone(record.context_fingerprints ?? []),
    capability_manifest: clone(record.capability_manifest ?? []),
    scope: clone(record.scope),
    facts: clone(record.facts),
    figures: clone(record.figures ?? []),
    excluded_fact_ids: clone(record.excluded_fact_ids),
    excluded_figure_ids: clone(record.excluded_figure_ids ?? []),
  });
}

function defaultDocumentId(record: ReportRecord): string {
  return `report-doc:${record.id}`;
}

/** Create the initial revision from an existing generated ReportRecord. */
export function createReportRevision(
  record: ReportRecord,
  options: CreateReportRevisionOptions = {},
): ReportRevision {
  const documentId = options.document_id ?? defaultDocumentId(record);
  const revisionNumber = options.revision_number ?? 1;
  const revisionId = options.revision_id ?? `${documentId}:revision:${revisionNumber}`;
  const source = sourceFromRecord(record);

  return deepFreeze({
    schema_version: REPORT_REVISION_SCHEMA_VERSION,
    revision_id: revisionId,
    document_id: documentId,
    revision_number: revisionNumber,
    ...(options.parent_revision_id ? { parent_revision_id: options.parent_revision_id } : {}),
    created_at: options.created_at ?? record.generatedAt,
    markdown: record.text,
    source,
  });
}

/** Create a one-revision document while keeping the old ReportRecord format usable. */
export function createReportDocument(
  record: ReportRecord,
  options: CreateReportDocumentOptions = {},
): ReportDocument {
  const documentId = options.document_id ?? defaultDocumentId(record);
  const revision = createReportRevision(record, {
    document_id: documentId,
    revision_id: options.revision_id,
    created_at: options.created_at,
  });

  return deepFreeze({
    schema_version: REPORT_DOCUMENT_SCHEMA_VERSION,
    document_id: documentId,
    source: revision.source,
    revisions: [revision],
    current_revision_id: revision.revision_id,
  });
}

/**
 * Create a new revision from prose/Markdown only.
 *
 * There is deliberately no patch/options object here: facts, scope, figures,
 * source run, and other result fields are carried over from the frozen source
 * snapshot and cannot be supplied or changed by custom editing.
 */
export function editReportRevision(
  revision: ReportRevision,
  markdown: string,
): ReportRevision {
  const revisionValidation = validateReportRevision(revision);
  if (!revisionValidation.valid) {
    throw new Error(`Invalid report revision: ${revisionValidation.errors.join("; ")}`);
  }
  if (typeof markdown !== "string") {
    throw new TypeError("markdown must be a string");
  }

  const revisionNumber = revision.revision_number + 1;
  return deepFreeze({
    ...revision,
    source: detachedFrozen(revision.source),
    revision_id: `${revision.document_id}:revision:${revisionNumber}`,
    revision_number: revisionNumber,
    parent_revision_id: revision.revision_id,
    markdown,
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function requiredString(
  value: Record<string, unknown>,
  key: string,
  path: string,
  errors: string[],
): value is Record<string, unknown> {
  if (typeof value[key] !== "string" || value[key].trim() === "") {
    errors.push(`${path}.${key} is required`);
    return false;
  }
  return true;
}

function isJsonValue(value: unknown, seen = new WeakSet<object>()): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value === "undefined" || typeof value === "function" || typeof value === "symbol") return false;
  if (typeof value !== "object") return false;
  if (seen.has(value)) return false;
  seen.add(value);
  if (Array.isArray(value)) return value.every((item) => isJsonValue(item, seen));
  return Object.values(value as Record<string, unknown>).every((item) => isJsonValue(item, seen));
}

function validateScope(value: unknown, path: string, errors: string[]): void {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }
  requiredString(value, "run_id", path, errors);
  if (!Number.isInteger(value.node_count) || (value.node_count as number) < 0) {
    errors.push(`${path}.node_count must be a non-negative integer`);
  }
  if (!Array.isArray(value.node_keys) || !value.node_keys.every((key) => typeof key === "string")) {
    errors.push(`${path}.node_keys must be an array of strings`);
  }
}

function validateFact(value: unknown, path: string, errors: string[]): void {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }
  for (const key of ["id", "node_key", "node_label", "field", "label"]) {
    requiredString(value, key, path, errors);
  }
  if (!hasOwn(value, "value")) {
    errors.push(`${path}.value is required`);
  } else if (!isJsonValue(value.value)) {
    errors.push(`${path}.value must be JSON-compatible`);
  }
}

function validateFigure(value: unknown, path: string, errors: string[]): void {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }
  requiredString(value, "artifact_id", path, errors);
  requiredString(value, "chart_type", path, errors);
  if (hasOwn(value, "path") && value.path !== undefined && typeof value.path !== "string") {
    errors.push(`${path}.path must be a string`);
  }
  if (hasOwn(value, "source") && value.source !== null && value.source !== undefined && !isRecord(value.source)) {
    errors.push(`${path}.source must be an object or null`);
  }
  if (hasOwn(value, "source") && value.source !== undefined && !isJsonValue(value.source)) {
    errors.push(`${path}.source must be JSON-compatible`);
  }
}

function validateSource(value: unknown, path: string, errors: string[]): void {
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return;
  }
  requiredString(value, "source_record_id", path, errors);
  requiredString(value, "source_run_id", path, errors);
  if (hasOwn(value, "source_report_id") && typeof value.source_report_id !== "string") {
    errors.push(`${path}.source_report_id must be a string`);
  }
  if (
    typeof value.source_report_id === "string"
    && typeof value.source_record_id === "string"
    && value.source_report_id !== value.source_record_id
  ) {
    errors.push(`${path}.source_report_id must equal ${path}.source_record_id`);
  }
  validateScope(value.scope, `${path}.scope`, errors);
  if (typeof value.source_run_id === "string" && isRecord(value.scope) && value.scope.run_id !== value.source_run_id) {
    errors.push(`${path}.scope.run_id must equal ${path}.source_run_id`);
  }
  if (hasOwn(value, "context_fingerprints") && (!Array.isArray(value.context_fingerprints) || !value.context_fingerprints.every((item) => typeof item === "string"))) {
    errors.push(`${path}.context_fingerprints must be an array of strings`);
  }
  if (hasOwn(value, "capability_manifest")) {
    if (!Array.isArray(value.capability_manifest)) {
      errors.push(`${path}.capability_manifest must be an array`);
    } else {
      value.capability_manifest.forEach((entry, index) => {
        if (!isRecord(entry)) {
          errors.push(`${path}.capability_manifest[${index}] must be an object`);
          return;
        }
        for (const key of ["capability_id", "provider_id", "availability", "validation_level"]) {
          requiredString(entry, key, `${path}.capability_manifest[${index}]`, errors);
        }
        if (!Array.isArray(entry.report_modules) || !entry.report_modules.every((item) => typeof item === "string")) {
          errors.push(`${path}.capability_manifest[${index}].report_modules must be an array of strings`);
        }
        if (!Array.isArray(entry.limitations) || !entry.limitations.every((item) => typeof item === "string")) {
          errors.push(`${path}.capability_manifest[${index}].limitations must be an array of strings`);
        }
      });
    }
  }

  if (!Array.isArray(value.facts)) {
    errors.push(`${path}.facts must be an array`);
  } else {
    value.facts.forEach((fact, index) => validateFact(fact, `${path}.facts[${index}]`, errors));
  }
  if (!Array.isArray(value.figures)) {
    errors.push(`${path}.figures must be an array`);
  } else {
    value.figures.forEach((figure, index) => validateFigure(figure, `${path}.figures[${index}]`, errors));
  }
  if (!Array.isArray(value.excluded_fact_ids) || !value.excluded_fact_ids.every((id) => typeof id === "string")) {
    errors.push(`${path}.excluded_fact_ids must be an array of strings`);
  }
  if (
    hasOwn(value, "excluded_figure_ids")
    && (!Array.isArray(value.excluded_figure_ids) || !value.excluded_figure_ids.every((id) => typeof id === "string"))
  ) {
    errors.push(`${path}.excluded_figure_ids must be an array of strings`);
  }
}

function revisionErrors(value: unknown, path: string): string[] {
  const errors: string[] = [];
  if (!isRecord(value)) {
    errors.push(`${path} must be an object`);
    return errors;
  }
  if (value.schema_version !== REPORT_REVISION_SCHEMA_VERSION) {
    errors.push(`${path}.schema_version must be ${REPORT_REVISION_SCHEMA_VERSION}`);
  }
  requiredString(value, "revision_id", path, errors);
  requiredString(value, "document_id", path, errors);
  if (!Number.isInteger(value.revision_number) || (value.revision_number as number) < 1) {
    errors.push(`${path}.revision_number must be a positive integer`);
  }
  if (hasOwn(value, "parent_revision_id") && value.parent_revision_id !== undefined && typeof value.parent_revision_id !== "string") {
    errors.push(`${path}.parent_revision_id must be a string`);
  }
  requiredString(value, "created_at", path, errors);
  if (typeof value.markdown !== "string") {
    errors.push(`${path}.markdown must be a string`);
  }
  validateSource(value.source, `${path}.source`, errors);
  return errors;
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function validateReportRevision(value: unknown): ReportRevisionValidation {
  const errors = revisionErrors(value, "revision");
  if (errors.length > 0) return { valid: false, errors };
  return { valid: true, revision: value as ReportRevision, errors: [] };
}

export function validateReportDocument(value: unknown): ReportDocumentValidation {
  const errors: string[] = [];
  if (!isRecord(value)) {
    return { valid: false, errors: ["document must be an object"] };
  }
  if (value.schema_version !== REPORT_DOCUMENT_SCHEMA_VERSION) {
    errors.push(`schema_version must be ${REPORT_DOCUMENT_SCHEMA_VERSION}`);
  }
  requiredString(value, "document_id", "document", errors);
  requiredString(value, "current_revision_id", "document", errors);
  validateSource(value.source, "source", errors);

  if (!Array.isArray(value.revisions) || value.revisions.length === 0) {
    errors.push("revisions must be a non-empty array");
  } else {
    value.revisions.forEach((revision, index) => {
      const path = `revisions[${index}]`;
      errors.push(...revisionErrors(revision, path));
      if (isRecord(revision) && isRecord(value.source) && isRecord(revision.source)) {
        if (revision.source.source_record_id !== value.source.source_record_id) {
          errors.push(`${path}.source.source_record_id must match source.source_record_id`);
        }
        if (revision.source.source_run_id !== value.source.source_run_id) {
          errors.push(`${path}.source.source_run_id must match source.source_run_id`);
        }
        if (canonicalJson(revision.source) !== canonicalJson(value.source)) {
          errors.push(`${path}.source must match the immutable document source`);
        }
      }
    });
    if (typeof value.current_revision_id === "string" && !value.revisions.some(
      (revision) => isRecord(revision) && revision.revision_id === value.current_revision_id,
    )) {
      errors.push("current_revision_id must identify a revision");
    }
  }

  if (errors.length > 0) return { valid: false, errors };
  return { valid: true, document: value as unknown as ReportDocument, errors: [] };
}

export function isReportDocument(value: unknown): value is ReportDocument {
  return validateReportDocument(value).valid;
}

export function serializeReportDocument(document: ReportDocument): string {
  const validation = validateReportDocument(document);
  if (!validation.valid) {
    throw new Error(`Invalid report document: ${validation.errors.join("; ")}`);
  }
  const serialized = JSON.stringify(document);
  if (typeof serialized !== "string") throw new Error("Report document is not serializable");
  return serialized;
}

export function parseReportDocument(serialized: string): ReportDocument {
  if (typeof serialized !== "string") throw new TypeError("serialized report document must be a string");
  let parsed: unknown;
  try {
    parsed = JSON.parse(serialized) as unknown;
  } catch {
    throw new Error("Invalid report document JSON");
  }
  const validation = validateReportDocument(parsed);
  if (!validation.valid) {
    throw new Error(`Invalid report document: ${validation.errors.join("; ")}`);
  }
  return deepFreeze(parsed as ReportDocument);
}
