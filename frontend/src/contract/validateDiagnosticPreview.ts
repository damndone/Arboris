import type { DiagnosticSummaryPreview } from "../api";

export type ValidationError = {
  path: string;
  reason: string;
  expected: string;
  actual: string;
};

export type ValidationResult =
  | { valid: true; data: DiagnosticSummaryPreview }
  | { valid: false; errors: ValidationError[] };

const TRUST_LABELS = new Set([
  "ready_to_interpret",
  "interpret_with_caution",
  "not_ready_to_interpret",
  "run_failed",
  "analysis_running",
  "lifecycle_unavailable",
  "legacy_unavailable",
  "contract_unavailable",
]);

const PREVIEW_STATUSES = new Set([
  "complete",
  "partial",
  "pending",
  "unavailable",
  "malformed",
  "lifecycle_unavailable",
]);

export function validateDiagnosticPreview(raw: unknown): ValidationResult {
  const errors: ValidationError[] = [];

  if (raw === null || typeof raw !== "object") {
    return {
      valid: false,
      errors: [
        {
          path: "",
          reason: "root is not an object",
          expected: "object",
          actual: raw === null ? "null" : typeof raw,
        },
      ],
    };
  }

  const obj = raw as Record<string, unknown>;

  requireBoolean(obj, "available", errors);
  requireString(obj, "preview_contract_version", errors);
  requireString(obj, "source_schema_version", errors);
  requireEnum(obj, "preview_status", PREVIEW_STATUSES, errors);
  requireStringArray(obj, "contract_warnings", errors);
  requireString(obj, "run_lifecycle_status", errors);
  requireEnum(obj, "trust_label", TRUST_LABELS, errors);
  requireArray(obj, "primary_reasons", errors);

  if ("trust_counts" in obj && obj.trust_counts !== undefined) {
    validateTrustCounts(obj.trust_counts, errors);
  }
  if ("run_status" in obj && obj.run_status !== undefined) {
    validateRunStatus(obj.run_status, errors);
  }

  if (errors.length > 0) return { valid: false, errors };
  return { valid: true, data: obj as unknown as DiagnosticSummaryPreview };
}

function requireBoolean(obj: Record<string, unknown>, key: string, errors: ValidationError[]): void {
  if (!(key in obj)) {
    errors.push({ path: key, reason: "missing required field", expected: "boolean", actual: "undefined" });
    return;
  }
  if (typeof obj[key] !== "boolean") {
    errors.push({ path: key, reason: "wrong type", expected: "boolean", actual: typeOf(obj[key]) });
  }
}

function requireString(obj: Record<string, unknown>, key: string, errors: ValidationError[]): void {
  if (!(key in obj)) {
    errors.push({ path: key, reason: "missing required field", expected: "string", actual: "undefined" });
    return;
  }
  if (typeof obj[key] !== "string") {
    errors.push({ path: key, reason: "wrong type", expected: "string", actual: typeOf(obj[key]) });
  }
}

function requireEnum(
  obj: Record<string, unknown>,
  key: string,
  allowed: Set<string>,
  errors: ValidationError[],
): void {
  if (!(key in obj)) {
    errors.push({ path: key, reason: "missing required field", expected: `one of [${[...allowed].join(", ")}]`, actual: "undefined" });
    return;
  }
  const value = obj[key];
  if (typeof value !== "string") {
    errors.push({ path: key, reason: "wrong type", expected: "string enum", actual: typeOf(value) });
    return;
  }
  if (!allowed.has(value)) {
    errors.push({ path: key, reason: "value not in enum", expected: `one of [${[...allowed].join(", ")}]`, actual: value });
  }
}

function requireArray(obj: Record<string, unknown>, key: string, errors: ValidationError[]): void {
  if (!(key in obj)) {
    errors.push({ path: key, reason: "missing required field", expected: "array", actual: "undefined" });
    return;
  }
  if (!Array.isArray(obj[key])) {
    errors.push({ path: key, reason: "wrong type", expected: "array", actual: typeOf(obj[key]) });
  }
}

function requireStringArray(obj: Record<string, unknown>, key: string, errors: ValidationError[]): void {
  if (!(key in obj)) {
    errors.push({ path: key, reason: "missing required field", expected: "string[]", actual: "undefined" });
    return;
  }
  const value = obj[key];
  if (!Array.isArray(value)) {
    errors.push({ path: key, reason: "wrong type", expected: "string[]", actual: typeOf(value) });
    return;
  }
  for (let i = 0; i < value.length; i++) {
    if (typeof value[i] !== "string") {
      errors.push({ path: `${key}[${i}]`, reason: "wrong element type", expected: "string", actual: typeOf(value[i]) });
    }
  }
}

function validateTrustCounts(raw: unknown, errors: ValidationError[]): void {
  if (raw === null || typeof raw !== "object") {
    errors.push({ path: "trust_counts", reason: "not an object", expected: "object", actual: typeOf(raw) });
    return;
  }
  const obj = raw as Record<string, unknown>;
  for (const key of ["blockers", "warnings", "cautions", "info"] as const) {
    const value = obj[key];
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
      errors.push({
        path: `trust_counts.${key}`,
        reason: "expected non-negative number",
        expected: "non-negative number",
        actual: typeOf(value),
      });
    }
  }
}

function validateRunStatus(raw: unknown, errors: ValidationError[]): void {
  if (raw === null || typeof raw !== "object") {
    errors.push({ path: "run_status", reason: "not an object", expected: "object", actual: typeOf(raw) });
    return;
  }
  const obj = raw as Record<string, unknown>;

  for (const key of ["status", "status_scope", "safe_to_interpret"] as const) {
    if (typeof obj[key] !== "string") {
      errors.push({ path: `run_status.${key}`, reason: "wrong type", expected: "string", actual: typeOf(obj[key]) });
    }
  }
  for (const key of ["safe_to_generate_report", "has_blockers", "has_warnings", "has_cautions", "model_results_available"] as const) {
    if (typeof obj[key] !== "boolean") {
      errors.push({ path: `run_status.${key}`, reason: "wrong type", expected: "boolean", actual: typeOf(obj[key]) });
    }
  }
}

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}
