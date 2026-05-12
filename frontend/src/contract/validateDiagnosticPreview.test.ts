import { describe, it, expect } from "vitest";
import { validateDiagnosticPreview } from "./validateDiagnosticPreview";

const validPreview = {
  available: true,
  preview_contract_version: "1.0",
  source_schema_version: "diagnostic_summary.v1",
  preview_status: "complete",
  contract_warnings: [],
  run_lifecycle_status: "completed",
  trust_label: "ready_to_interpret",
  primary_reasons: [],
  trust_counts: { blockers: 0, warnings: 0, cautions: 0, info: 0 },
};

describe("validateDiagnosticPreview", () => {
  it("accepts a minimally-valid payload", () => {
    const result = validateDiagnosticPreview(validPreview);
    expect(result.valid).toBe(true);
    if (result.valid) {
      expect(result.data.available).toBe(true);
    }
  });

  it("rejects null", () => {
    const result = validateDiagnosticPreview(null);
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.length).toBeGreaterThan(0);
      expect(result.errors[0].path).toBe("");
    }
  });

  it("rejects missing required field", () => {
    const { preview_status, ...partial } = validPreview;
    const result = validateDiagnosticPreview(partial);
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => e.path === "preview_status")).toBe(true);
    }
  });

  it("rejects wrong type on contract_warnings", () => {
    const result = validateDiagnosticPreview({ ...validPreview, contract_warnings: "not an array" });
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => e.path === "contract_warnings")).toBe(true);
    }
  });

  it("rejects negative trust count", () => {
    const result = validateDiagnosticPreview({
      ...validPreview,
      trust_counts: { blockers: -1, warnings: 0, cautions: 0, info: 0 },
    });
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => e.path === "trust_counts.blockers")).toBe(true);
    }
  });

  it("rejects non-array primary_reasons", () => {
    const result = validateDiagnosticPreview({ ...validPreview, primary_reasons: {} });
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => e.path === "primary_reasons")).toBe(true);
    }
  });

  it("accepts legacy unavailable preview shape", () => {
    const legacy = {
      available: false,
      preview_contract_version: "1.0",
      source_schema_version: "diagnostic_summary.v1",
      preview_status: "unavailable",
      contract_warnings: ["diagnostic_summary.json is missing; using legacy/debug fallback."],
      run_lifecycle_status: "completed",
      trust_label: "legacy_unavailable",
      primary_reasons: [],
    };
    const result = validateDiagnosticPreview(legacy);
    expect(result.valid).toBe(true);
  });

  it("rejects invalid trust_label enum value", () => {
    const result = validateDiagnosticPreview({ ...validPreview, trust_label: "totally_made_up" });
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => e.path === "trust_label")).toBe(true);
    }
  });

  it("reports multiple errors at once", () => {
    const result = validateDiagnosticPreview({ ...validPreview, preview_status: 42, contract_warnings: null });
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.length).toBeGreaterThanOrEqual(2);
    }
  });
});
