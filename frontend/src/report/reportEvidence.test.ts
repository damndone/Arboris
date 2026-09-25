import { describe, expect, it } from "vitest";
import type { CitableFact } from "./factTable";
import {
  groupFacts,
  reportCapabilitiesForFacts,
  reportCapabilityManifestForFacts,
  readReportEvidence,
  readPersistedEvidenceProjection,
} from "./reportEvidence";

function fact(overrides: Partial<CitableFact>): CitableFact {
  return {
    id: "c1",
    node_key: "node:1",
    node_label: "Model",
    field: "metric:r_squared",
    label: "R squared",
    value: 0.86,
    ...overrides,
  };
}

describe("report evidence grouping", () => {
  it("groups current providers in a stable reader-facing order", () => {
    const groups = groupFacts([
      fact({ id: "c1", field: "param:covariance" }),
      fact({ id: "c2", field: "coef:age" }),
      fact({ id: "c3", field: "coef_p:age" }),
      fact({ id: "c4", field: "ts:forecast:rmse" }),
      fact({ id: "c5", field: "figure:plot:source.y" }),
      fact({ id: "c6", field: "post_estimation:step:joint_f" }),
      fact({ id: "c7", field: "future_provider:metric" }),
    ]);

    expect(groups.map((group) => group.id)).toEqual([
      "model-estimation",
      "diagnostics-robustness",
      "time-series",
      "figures",
      "post-estimation",
      "other",
    ]);
    expect(groups.find((group) => group.id === "other")?.facts[0].id).toBe("c7");
  });

  it("keeps human labels in the primary row while retaining raw field metadata", () => {
    const [group] = groupFacts([
      fact({ id: "c1", field: "metric:r_squared", label: "Model fit (R²)" }),
    ]);

    expect(group.facts[0]).toMatchObject({
      id: "c1",
      label: "Model fit (R²)",
      field: "metric:r_squared",
    });
  });

  it("does not mutate fact values while grouping", () => {
    const facts = [fact({ value: 0.86 })];
    const grouped = groupFacts(facts);

    expect(grouped[0].facts[0].value).toBe(0.86);
    expect(facts[0].value).toBe(0.86);
  });

  it("derives stable capability modules from provider groups", () => {
    const facts = [
      fact({ field: "sample:n", label: "N" }),
      fact({ id: "c2", field: "param:x", label: "X" }),
      fact({ id: "c3", field: "diagnostic:normality", label: "Normality" }),
      fact({ id: "c4", field: "ts:forecast:rmse", label: "RMSE" }),
      fact({ id: "c5", field: "post_estimation:joint_f", label: "Joint F" }),
      fact({ id: "c6", field: "figure:coef", label: "Coefficient plot" }),
    ];

    expect(reportCapabilitiesForFacts(facts)).toEqual([
      "data",
      "model.estimation",
      "diagnostics.robustness",
      "time_series",
      "post_estimation",
    ]);
  });

  it("emits a provider manifest without coupling the view to model names", () => {
    const manifest = reportCapabilityManifestForFacts([
      fact({ field: "coef:age" }),
      fact({ id: "c2", field: "diagnostic:normality" }),
    ]);

    expect(manifest).toEqual([
      expect.objectContaining({
        capability_id: "model.estimation",
        provider_id: "evidence.estimation.v1",
        availability: "available",
        report_modules: ["model-estimation"],
      }),
      expect.objectContaining({
        capability_id: "diagnostics.robustness",
        provider_id: "evidence.diagnostics.v1",
        report_modules: ["diagnostics-robustness"],
      }),
    ]);
  });

  it("does not collapse mixed post-estimation providers into the first fact", () => {
    const manifest = reportCapabilityManifestForFacts([
      fact({ field: "post_estimation:legacy:value" }),
      fact({
        id: "c2",
        field: "post_estimation:p7:value",
        provider_id: "evidence.workflow.p7.v1",
      }),
      fact({
        id: "c3",
        field: "post_estimation:generic:value",
        provider_id: "evidence.workflow.capability.v1",
      }),
    ]);

    expect(manifest).toEqual([
      expect.objectContaining({
        capability_id: "post_estimation",
        provider_id: "evidence.post_estimation.aggregate.v1",
        limitations: [
          "Facts include multiple registered evidence providers; inspect fact-level provider_id metadata.",
        ],
      }),
    ]);
  });
});

// Pinned to the frozen Python result_sections_declaration(), not a parser export.
const sectionDigest = "9ac17e068d3d718e6cb09a938e2d373db3c43d49b11ca6b7ac6df76897732ab6";
function structuredProjection() {
  return {
    projectionId: "projection:report:1", consumerId: "report", consumerVersion: "1.0",
    artifactRef: "artifact:1", envelopeRef: "envelope:1", envelopeDigest: "a".repeat(64),
    rendererKey: "workbench.consumer_projection.report", projectionDigest: "b".repeat(64),
    status: "available", executionStatus: "completed", availability: "available",
    completenessStatus: "complete", validationStatus: "met", validationSummary: {},
    facts: [{ factId: "p:x", statisticId: "p_value", value: 1.25e-24 }], sections: [],
    structuredResults: { schema_version: 1, contract_digest: sectionDigest, sections: [{
      section_id: "test:partition:1", section_type: "statistical_tests", schema_version: 1,
      status: "available", reason_codes: [], fact_refs: ["p:x"], dependency_refs: ["model:x"],
      content: { kind: "object", fields: { results: { kind: "list", items: [{
        kind: "object", fields: {
          p_value: { kind: "fact", fact_id: "p:x", representation: "number" },
          label: { kind: "text", value: "<script>label</script>" },
        },
      }] } } },
    }] },
    resolvedSections: [{ sectionId: "test:partition:1", sectionType: "statistical_tests",
      status: "available", reasonCodes: [], content: { results: [{ p_value: 1.25e-24, label: "<script>label</script>" }] } }],
  };
}

function replaceAt(value: unknown, path: string, replacement: unknown) {
  const parts = path.split(".");
  let target = value as Record<string, unknown>;
  for (const part of parts.slice(0, -1)) target = target[part] as Record<string, unknown>;
  target[parts[parts.length - 1]] = replacement;
}

type ArmaNode = { kind: string; [key: string]: unknown };
const armaText = (value: string): ArmaNode => ({ kind: "text", value });
const armaObject = (fields: Record<string, unknown>): ArmaNode => ({ kind: "object", fields });
const armaList = (...items: unknown[]): ArmaNode => ({ kind: "list", items });
const armaNumber: ArmaNode = { kind: "fact", fact_id: "p:x", representation: "number" };
const armaMissing: ArmaNode = { kind: "missing", status: "unavailable", reason: "SOURCE_MISSING" };

function armaReport() {
  return armaObject({
    contract: armaObject({ dataset_ref: armaText("dataset:1"), transform: armaText("none") }),
    sample: armaObject({ source_n: armaNumber, selection_data_role: armaText("training") }),
    metrics: armaObject({ rmse: armaNumber, coverage_uncertainty: armaObject({ method: armaText("exact"), lower: armaNumber }) }),
    parameters: armaObject({ final_fit: armaObject({ "ar.L1": armaNumber }) }),
    diagnostics: armaObject({ adf: armaObject({ p_value: armaNumber }), ljung_box: armaList(armaObject({ used_lag: armaNumber })),
      normality: armaObject({ shapiro_wilk: armaObject({ statistic: armaNumber }) }), warnings: armaList(armaText("caution")) }),
    selection: armaObject({ mean: armaObject({ selection_basis: armaText("AIC") }) }),
    next_forecast: armaObject({ conditional_mean: armaNumber, forecast_origin: armaObject({ row_id: armaText("last") }) }),
    forecast_limitations: armaObject({ horizon: armaNumber, parameter_uncertainty_included: { kind: "boolean", value: false } }),
    warnings: armaList(armaText("末行🧪")), artifact_ids: armaList(armaText("model:x")),
    chart_artifacts: armaList(armaText("model:x")),
  });
}

// Rebuild resolved values and exact refs after each mutation: failures must be
// schema/dependency failures, not an accidentally stale paired display tree.
function armaProjection(report: unknown = armaReport(), family = "time_series.arma_garch") {
  const wire = structuredProjection();
  const refs = new Set<string>();
  function resolve(value: unknown): unknown {
    const node = value as ArmaNode;
    if (node.kind === "object") return Object.fromEntries(Object.entries(node.fields as Record<string, unknown>).map(([key, child]) => [key, resolve(child)]));
    if (node.kind === "list") return (node.items as unknown[]).map(resolve);
    if (node.kind === "fact") { refs.add(node.fact_id as string); return 1.25e-24; }
    if (node.kind === "missing") return { status: node.status, reason: node.reason };
    return node.kind === "null" ? null : node.value ?? value;
  }
  const content = armaObject({ model_family: armaText(family), results: armaObject({ "model:x": armaObject({ report }) }) });
  replaceAt(wire, "structuredResults.sections.0.section_type", "model_family_evidence");
  replaceAt(wire, "structuredResults.sections.0.content", content);
  replaceAt(wire, "resolvedSections.0.sectionType", "model_family_evidence");
  replaceAt(wire, "resolvedSections.0.content", resolve(content));
  replaceAt(wire, "structuredResults.sections.0.fact_refs", [...refs]);
  return wire;
}

describe("ARMA report declaration", () => {
  it("accepts declared typed records, exact tiny facts and Unicode", () => {
    const wire = armaProjection();
    expect(readReportEvidence(wire)).toMatchObject({ resolvedSections: wire.resolvedSections });
  });
  it.each([
    ["fields.unknown", armaText("hidden")],
    ["fields.contract.fields.unknown", armaText("hidden")],
    ["fields.sample.fields.source_n", armaText("123")],
    ["fields.metrics.fields.rmse", 0.5],
    ["fields.metrics.fields.rmse", { kind: "number", value: 0.5 }],
    ["fields.metrics.fields.coverage_uncertainty", armaList()],
    ["fields.parameters.fields.final_fit.fields.ar.L1", armaText("bad")],
    ["fields.diagnostics.fields.ljung_box", armaObject({})],
    ["fields.diagnostics.fields.normality.fields.shapiro_wilk.fields.statistic", armaText("0.05")],
    ["fields.selection.fields.mean.fields.selection_basis", { kind: "boolean", value: true }],
    ["fields.next_forecast.fields.forecast_origin.fields.row_id", armaNumber],
    ["fields.forecast_limitations.fields.parameter_uncertainty_included", armaText("false")],
    ["fields.warnings", armaList(armaNumber)],
    ["fields.artifact_ids", armaList(armaText("forged:artifact"))],
    ["fields.chart_artifacts", armaList(armaText("forged:chart"))],
    ["fields.artifact_ids", armaList(armaMissing)],
    ["fields.chart_artifacts", armaList(armaNumber)],
    ["", armaList()],
  ])("rejects a real schema mutation at %s: %j", (path, replacement) => {
    const report = armaReport();
    expect(readReportEvidence(armaProjection(report))).not.toBeNull();
    const before = JSON.stringify(report);
    // Parameter keys are opaque (including dots), not paths.
    if (path === "fields.parameters.fields.final_fit.fields.ar.L1") {
      replaceAt(report, "fields.parameters.fields.final_fit.fields", { "ar.L1": replacement });
    } else if (path) replaceAt(report, path, replacement);
    const mutated = path ? report : replacement;
    expect(JSON.stringify(mutated)).not.toBe(before);
    expect(readReportEvidence(armaProjection(mutated))).toBeNull();
  });
  it.each(["", "fields.metrics", "fields.metrics.fields.rmse", "fields.parameters.fields.final_fit",
    "fields.warnings", "fields.artifact_ids", "fields.chart_artifacts"])("accepts explicit missing at %s", (path) => {
    const report = armaReport();
    if (path) replaceAt(report, path, armaMissing);
    const wire = armaProjection(path ? report : armaMissing);
    expect(readReportEvidence(wire)).toMatchObject({ resolvedSections: wire.resolvedSections });
  });
  it("keeps ordinary family trees outside the ARMA-specific declaration", () => {
    const wire = armaProjection(armaObject({ custom: armaText("ordinary") }), "regression.ols");
    expect(readReportEvidence(wire)).not.toBeNull();
  });
});

describe("closed structured evidence extension", () => {
  it("accepts the current server correction_scope contract as exact text", () => {
    const wire = structuredProjection();
    wire.structuredResults.contract_digest = sectionDigest;
    replaceAt(wire, "structuredResults.sections.0.content.fields.correction_scope", {
      kind: "text", value: "Within each declared outcome family",
    });
    replaceAt(wire, "resolvedSections.0.content.correction_scope", "Within each declared outcome family");
    expect(readReportEvidence(wire)).toMatchObject({ resolvedSections: wire.resolvedSections });
    replaceAt(wire, "structuredResults.sections.0.content.fields.correction_scope", { kind: "boolean", value: true });
    replaceAt(wire, "resolvedSections.0.content.correction_scope", true);
    expect(readReportEvidence(wire)).toBeNull();
    replaceAt(wire, "structuredResults.sections.0.content.fields.correction_scope", { kind: "list", items: [] });
    replaceAt(wire, "resolvedSections.0.content.correction_scope", []);
    expect(readReportEvidence(wire)).toBeNull();
  });

  it("preserves tiny facts and exact resolved values in a defensive copy", () => {
    const wire = structuredProjection();
    const parsed = readReportEvidence(wire);
    expect(parsed).toMatchObject({ structuredResults: wire.structuredResults, resolvedSections: wire.resolvedSections });
    wire.resolvedSections[0].content.results[0].p_value = 0.5;
    wire.structuredResults.sections[0].content.fields.results.items[0].fields.label.value = "tamper";
    expect(parsed?.resolvedSections?.[0].content).toEqual({ results: [{ p_value: 1.25e-24, label: "<script>label</script>" }] });
    expect(readReportEvidence(parsed)).toEqual(parsed);
  });

  it("retains old numeric-only projections and the shared notebook parser", () => {
    const wire = structuredProjection();
    const { structuredResults: _s, resolvedSections: _r, ...legacy } = wire;
    expect(readReportEvidence(legacy)).not.toBeNull();
    expect(readPersistedEvidenceProjection({ ...wire, consumerId: "notebook", rendererKey: "workbench.consumer_projection.notebook" }))
      .toMatchObject({ resolvedSections: wire.resolvedSections });
  });

  it.each([
    ["structuredResults.schema_version", 2], ["structuredResults.schema_version", true],
    ["structuredResults.contract_digest", "a".repeat(64)], ["structuredResults.extra", true],
    ["structuredResults.contract_digest", "5011c6e10d1fb50353a55ac96c7e82169414c1e1dae7ba6f3e64555c59b20e72"],
    ["structuredResults.sections.0.schema_version", 2], ["structuredResults.sections.0.section_type", "raw_statistics"],
    ["structuredResults.sections.0.fact_refs", []], ["structuredResults.sections.0.fact_refs", ["p:x", "p:x"]],
    ["structuredResults.sections.0.dependency_refs", []], ["structuredResults.sections.0.dependency_refs", ["bad\0ref"]],
    ["structuredResults.sections.0.dependency_refs", ["model:x", "model:x"]],
    ["structuredResults.sections.0.content.fields.results.items.0.fields.p_value.fact_id", "missing"],
    ["structuredResults.sections.0.content.fields.results.items.0.fields.p_value.representation", "integer"],
    ["structuredResults.sections.0.content.fields.results.items.0.fields.p_value", { kind: "number", value: 0.05 }],
    ["structuredResults.sections.0.content.fields.results.items.0.fields.label.extra", "hidden"],
    ["resolvedSections.0.content.results.0.p_value", 0.05],
    ["resolvedSections.0.content.results.0.label", "mutated"], ["resolvedSections.0.content.extra", 77],
    ["resolvedSections.0.sectionId", "foreign"], ["resolvedSections.0.sectionType", "regression_table"],
    ["resolvedSections.0.status", "blocked"], ["resolvedSections.0.reasonCodes", ["MISSING"]],
    ["resolvedSections.0.extra", 1], ["resolvedSections", []],
    ["facts.0.value", Infinity], ["facts.0.value", Number.MAX_SAFE_INTEGER + 1], ["facts.0.value", "1.25e-24"],
    ["structuredResults", undefined], ["resolvedSections", undefined],
    ["structuredResults", null], ["resolvedSections", null],
  ])("rejects the entire projection on mutation of %s", (path, value) => {
    const wire = structuredProjection();
    replaceAt(wire, path, value);
    expect(readReportEvidence(wire)).toBeNull();
  });

  it("rejects duplicate facts and section IDs rather than choosing a winner", () => {
    const wire = structuredProjection();
    wire.facts.push({ ...wire.facts[0] });
    expect(readReportEvidence(wire)).toBeNull();
    wire.facts.pop(); wire.structuredResults.sections.push(wire.structuredResults.sections[0]);
    wire.resolvedSections.push(wire.resolvedSections[0]);
    expect(readReportEvidence(wire)).toBeNull();
  });

  it.each(["depth", "nodes", "text", "utf8", "bytes", "resolved-depth", "resolved-text", "sections", "unicode-collision"])(
    "preflights %s without copying or overflowing the stack", (attack) => {
      const wire = structuredProjection();
      let node: unknown = { kind: "null" };
      if (attack === "depth") {
        for (let i = 0; i < 10000; i++) node = { kind: "list", items: [node] };
        replaceAt(wire, "structuredResults.sections.0.content", node);
      } else if (attack === "nodes") {
        replaceAt(wire, "structuredResults.sections.0.content.fields.results.items", Array(16385).fill(node));
      } else if (attack === "text" || attack === "utf8") {
        replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields.label.value", attack === "text" ? "x".repeat(8 * 1024 * 1024) : "汉".repeat(2000));
      } else if (attack === "bytes") {
        replaceAt(wire, "structuredResults.sections.0.content.fields.warnings", { kind: "list", items: Array(300).fill({ kind: "text", value: "x".repeat(4096) }) });
      } else if (attack === "resolved-depth") {
        for (let i = 0; i < 10000; i++) node = [node];
        replaceAt(wire, "resolvedSections.0.content", node);
      } else if (attack === "resolved-text") {
        replaceAt(wire, "resolvedSections.0.content", "x".repeat(8 * 1024 * 1024));
      } else if (attack === "sections") {
        replaceAt(wire, "structuredResults.sections", Array(129).fill(wire.structuredResults.sections[0]));
      } else {
        replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields", { "é": node, "e\u0301": node });
      }
      expect(() => readReportEvidence(wire)).not.toThrow();
      expect(readReportEvidence(wire)).toBeNull();
    },
  );

  it.each([
    ["model_identity", ["models"]], ["regression_table", ["models", "rows"]],
    ["descriptive_statistics", ["rows"]], ["statistical_tests", ["results"]],
    ["survey_design", ["design", "provenance"]], ["marginal_effects", ["rows", "method"]],
    ["model_family_evidence", ["model_family", "results"]], ["diagnostics", ["blockers", "warnings", "cautions", "info"]],
    ["interpretation_constraints", ["constraints", "required_mentions", "forbidden_claims"]],
    ["variable_importance", ["rows", "method"]], ["workflow_status", ["workflow_id", "status", "steps", "artifact_ids"]],
  ])("retains all partitions of declared %s sections", (type, required) => {
    const wire = structuredProjection();
    const fields = Object.fromEntries((required as string[]).map((key) => [key, { kind: "missing", status: "unavailable", reason: "NOT_DECLARED" }]));
    const content = Object.fromEntries((required as string[]).map((key) => [key, { status: "unavailable", reason: "NOT_DECLARED" }]));
    replaceAt(wire, "structuredResults.sections", [1, 2].map((i) => ({ ...wire.structuredResults.sections[0],
      section_id: `partition:${i}`, section_type: type, fact_refs: [], content: { kind: "object", fields } })));
    replaceAt(wire, "resolvedSections", [1, 2].map((i) => ({ ...wire.resolvedSections[0], sectionId: `partition:${i}`, sectionType: type, content })));
    expect(readReportEvidence(wire)).toMatchObject({ resolvedSections: wire.resolvedSections });
    replaceAt(wire, "structuredResults.sections.0.content.fields", {});
    expect(readReportEvidence(wire)).toBeNull();
  });

  it.each(["unavailable", "not_applicable", "blocked"])("retains %s reasons without hidden content", (status) => {
    const wire = structuredProjection();
    replaceAt(wire, "structuredResults.sections.0", { ...wire.structuredResults.sections[0], status, reason_codes: ["SOURCE_MISSING"], fact_refs: [], dependency_refs: [], content: { kind: "null" } });
    replaceAt(wire, "resolvedSections.0", { ...wire.resolvedSections[0], status, reasonCodes: ["SOURCE_MISSING"], content: null });
    expect(readReportEvidence(wire)).toMatchObject({ resolvedSections: wire.resolvedSections });
    replaceAt(wire, "resolvedSections.0.content", { hidden: 42 });
    expect(readReportEvidence(wire)).toBeNull();
  });

  it("preserves negative zero rather than changing it while copying", () => {
    const wire = structuredProjection(); wire.facts[0].value = -0; wire.resolvedSections[0].content.results[0].p_value = -0;
    const parsed = readReportEvidence(wire);
    expect(parsed).not.toBeNull();
    expect(Object.is((parsed?.resolvedSections?.[0].content as { results: { p_value: number }[] }).results[0].p_value, -0)).toBe(true);
  });

  it.each([[0, -0], [-0, 0]])("rejects a number zero-sign mutation (%s -> %s)", (source, resolved) => {
    const wire = structuredProjection();
    wire.facts[0].value = source;
    wire.resolvedSections[0].content.results[0].p_value = resolved;
    expect(readReportEvidence(wire)).toBeNull();
  });

  it("matches server integer normalization of negative zero", () => {
    const wire = structuredProjection(); wire.facts[0].value = -0;
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields.p_value.representation", "integer");
    wire.resolvedSections[0].content.results[0].p_value = 0;
    expect(readReportEvidence(wire)).not.toBeNull();
    wire.resolvedSections[0].content.results[0].p_value = -0;
    expect(readReportEvidence(wire)).toBeNull();
  });

  it("accepts finite safe integer facts without converting or rounding", () => {
    const wire = structuredProjection(); wire.facts[0].value = Number.MAX_SAFE_INTEGER;
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields", {
      nobs: { kind: "fact", fact_id: "p:x", representation: "integer" },
    });
    replaceAt(wire, "resolvedSections.0.content.results.0", { nobs: Number.MAX_SAFE_INTEGER });
    expect(readReportEvidence(wire)).toMatchObject({ resolvedSections: wire.resolvedSections });
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields.nobs.representation", "number");
    expect(readReportEvidence(wire)).toBeNull();
  });

  it.each(["p_value", "confidence_level", "nobs"])("validates declared numerical role %s, not label names", (name) => {
    const wire = structuredProjection(); wire.facts[0].value = -1;
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields", { [name]: { kind: "fact", fact_id: "p:x", representation: "integer" } });
    replaceAt(wire, "resolvedSections.0.content.results.0", { [name]: -1 });
    expect(readReportEvidence(wire)).toBeNull();
    wire.facts[0].value = 0.5;
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields", { [name]: { kind: "text", value: "0.5" } });
    replaceAt(wire, "structuredResults.sections.0.fact_refs", []);
    replaceAt(wire, "resolvedSections.0.content.results.0", { [name]: "0.5" });
    expect(readReportEvidence(wire)).toBeNull();
  });

  it("accepts 16-deep content but rejects the next level", () => {
    const wire = structuredProjection();
    let node: unknown = { kind: "text", value: "deep label" }; let decoded: unknown = "deep label";
    for (let i = 0; i < 15; i++) { node = { kind: "list", items: [node] }; decoded = [decoded]; }
    replaceAt(wire, "structuredResults.sections.0.content.fields.warnings", node);
    replaceAt(wire, "resolvedSections.0.content.warnings", decoded);
    expect(readReportEvidence(wire)).not.toBeNull();
    replaceAt(wire, "structuredResults.sections.0.content.fields.warnings", { kind: "list", items: [node] });
    replaceAt(wire, "resolvedSections.0.content.warnings", [decoded]);
    expect(readReportEvidence(wire)).toBeNull();
  });

  it("allows display keys named path, source_ref and __proto__ as inert own keys", () => {
    const wire = structuredProjection();
    const fields = JSON.parse('{"path":{"kind":"text","value":"label"},"source_ref":{"kind":"text","value":"label"},"__proto__":{"kind":"text","value":"label"}}');
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields.label", { kind: "object", fields });
    replaceAt(wire, "resolvedSections.0.content.results.0.label", JSON.parse('{"path":"label","source_ref":"label","__proto__":"label"}'));
    expect(readReportEvidence(wire)).toMatchObject({ resolvedSections: wire.resolvedSections });
    expect(Object.getPrototypeOf(readReportEvidence(wire))).toBe(Object.prototype);
  });

  it.each([true, false, null, "😀".repeat(1024)])("preserves bounded scalar %s", (value) => {
    const wire = structuredProjection();
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields.label", value === null ? { kind: "null" } : { kind: typeof value === "boolean" ? "boolean" : "text", value });
    replaceAt(wire, "resolvedSections.0.content.results.0.label", value);
    expect(readReportEvidence(wire)).toMatchObject({ resolvedSections: wire.resolvedSections });
  });

  it.each(["\ud800", "\udc00", "\0"])("rejects non-UTF8 or NUL text", (value) => {
    const wire = structuredProjection();
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields.label.value", value);
    replaceAt(wire, "resolvedSections.0.content.results.0.label", value);
    expect(readReportEvidence(wire)).toBeNull();
  });

  it.each(["model_results.linear_mixed_effects_1", "source.with.dots", "../secret"])("accepts server dependency IDs as identifiers, not file locators: %s", (ref) => {
    const wire = structuredProjection();
    wire.structuredResults.sections[0].dependency_refs = [ref];
    expect(readReportEvidence(wire)).not.toBeNull();
  });

  it.each([1e20, -1e20, Number.MAX_VALUE, Number.MAX_SAFE_INTEGER + 1])("preserves finite number representation %s but rejects its integer/count representation", (value) => {
    const wire = structuredProjection();
    wire.facts[0].value = value;
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields", {
      statistic: { kind: "fact", fact_id: "p:x", representation: "number" },
    });
    replaceAt(wire, "resolvedSections.0.content.results.0", { statistic: value });
    expect(readReportEvidence(wire)).toMatchObject({ resolvedSections: wire.resolvedSections });
    replaceAt(wire, "resolvedSections.0.content.results.0.statistic", value / 2);
    expect(readReportEvidence(wire)).toBeNull();
    replaceAt(wire, "resolvedSections.0.content.results.0.statistic", value);
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields.statistic.representation", "integer");
    expect(readReportEvidence(wire)).toBeNull();
    replaceAt(wire, "structuredResults.sections.0.content.fields.results.items.0.fields", {
      nobs: { kind: "fact", fact_id: "p:x", representation: "integer" },
    });
    replaceAt(wire, "resolvedSections.0.content.results.0", { nobs: value });
    expect(readReportEvidence(wire)).toBeNull();
  });

  it("accepts finite float facts outside the selected tree without inferring integer representation", () => {
    const wire = structuredProjection();
    wire.facts.push({ factId: "other", statisticId: "estimate", value: 1e20 });
    expect(readReportEvidence(wire)).not.toBeNull();
  });

  it("enforces the aggregate byte ceiling across otherwise valid partitions", () => {
    const wire = structuredProjection();
    const warnings = Array(130).fill("x".repeat(4096));
    replaceAt(wire, "structuredResults.sections.0.content.fields.warnings", { kind: "list", items: warnings.map((value) => ({ kind: "text", value })) });
    replaceAt(wire, "resolvedSections.0.content.warnings", warnings);
    expect(readReportEvidence(wire)).not.toBeNull();
    wire.structuredResults.sections.push({ ...wire.structuredResults.sections[0], section_id: "partition:2" });
    wire.resolvedSections.push({ ...wire.resolvedSections[0], sectionId: "partition:2" });
    expect(readReportEvidence(wire)).toBeNull();
  });

  it("counts tree nodes across nested lists, not just each list's length", () => {
    const wire = structuredProjection();
    const nodes = Array(16378).fill({ kind: "null" });
    const values = Array(16378).fill(null);
    // Five original nodes + warnings list + 16378 leaves = 16384.
    replaceAt(wire, "structuredResults.sections.0.content.fields.warnings", { kind: "list", items: nodes });
    replaceAt(wire, "resolvedSections.0.content.warnings", values);
    expect(readReportEvidence(wire)).not.toBeNull();
    nodes.push({ kind: "null" }); values.push(null);
    expect(readReportEvidence(wire)).toBeNull();
  });
});
