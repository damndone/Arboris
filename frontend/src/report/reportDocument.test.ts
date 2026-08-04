import { describe, expect, it } from "vitest";
import type { CitableFact, ReportScope } from "./factTable";
import type { ReportFigure } from "./reportClient";
import type { ReportRecord } from "./reportHistory";
import {
  createReportDocument,
  createReportRevision,
  editReportRevision,
  parseReportDocument,
  serializeReportDocument,
  validateReportDocument,
} from "./reportDocument";

const scope: ReportScope = {
  run_id: "run-42",
  node_count: 2,
  node_keys: ["data:input", "model:ols"],
};

const facts: CitableFact[] = [
  {
    id: "c1",
    node_key: "model:ols",
    node_label: "OLS",
    field: "coef:age",
    label: "Age coefficient",
    value: 1.25,
  },
  {
    id: "c2",
    node_key: "model:ols",
    node_label: "OLS",
    field: "coef_p:age",
    label: "Age p-value",
    value: 0.04,
  },
];

const figures: ReportFigure[] = [
  {
    artifact_id: "figure:coef",
    chart_type: "coefficient plot",
    path: "figures/coef.png",
    source: { preview_json: '{"estimate":1.25}' },
  },
];

function record(overrides: Partial<ReportRecord> = {}): ReportRecord {
  return {
    id: "report-42",
    generatedAt: "2026-08-03T12:00:00.000Z",
    model: "gpt-test",
    instruction: "Write a report",
    text: "# Results\nThe estimate is 1.25 [[c:c1]].",
    scope: { ...scope, node_keys: [...scope.node_keys] },
    facts: facts.map((fact) => ({ ...fact })),
    excluded_fact_ids: ["c2"],
    figures: figures.map((figure) => ({
      ...figure,
      source: figure.source ? { ...figure.source } : figure.source,
    })),
    ...overrides,
  };
}

describe("report document and immutable revisions", () => {
  it("creates a versioned document from a legacy ReportRecord", () => {
    const document = createReportDocument(record());

    expect(document.schema_version).toBe("workbench.report.document/v1");
    expect(document.document_id).toBe("report-doc:report-42");
    expect(document.source).toMatchObject({
      source_record_id: "report-42",
      source_run_id: "run-42",
      scope,
      facts,
      figures,
      excluded_fact_ids: ["c2"],
    });
    expect(document.revisions).toHaveLength(1);
    expect(document.revisions[0].markdown).toBe(record().text);
    expect(document.current_revision_id).toBe(document.revisions[0].revision_id);
  });

  it("keeps source run, scope, facts, and figures as a frozen snapshot", () => {
    const sourceRecord = record();
    const document = createReportDocument(sourceRecord);

    expect(Object.isFrozen(document.source)).toBe(true);
    expect(Object.isFrozen(document.source.scope)).toBe(true);
    expect(Object.isFrozen(document.source.scope.node_keys)).toBe(true);
    expect(Object.isFrozen(document.source.facts)).toBe(true);
    expect(Object.isFrozen(document.source.facts[0])).toBe(true);
    expect(Object.isFrozen(document.source.figures)).toBe(true);

    sourceRecord.scope.node_keys[0] = "data:changed";
    sourceRecord.facts[0].value = 999;
    sourceRecord.figures![0].artifact_id = "figure:changed";

    expect(document.source.source_run_id).toBe("run-42");
    expect(document.source.scope.node_keys[0]).toBe("data:input");
    expect(document.source.facts[0].value).toBe(1.25);
    expect(document.source.figures[0].artifact_id).toBe("figure:coef");
  });

  it("creates an immutable revision whose edit surface is markdown only", () => {
    const initial = createReportRevision(record(), {
      document_id: "doc-custom",
      revision_id: "rev-custom-1",
    });
    const edited = editReportRevision(initial, "# Revised\nAuthor prose only.");

    expect(edited.revision_id).toBe("doc-custom:revision:2");
    expect(edited.revision_number).toBe(2);
    expect(edited.parent_revision_id).toBe("rev-custom-1");
    expect(edited.markdown).toBe("# Revised\nAuthor prose only.");
    expect(edited.source).toEqual(initial.source);
    expect(edited.source).not.toBe(initial.source);
    expect(Object.isFrozen(edited.source)).toBe(true);
    expect(() => editReportRevision(initial, { markdown: "not text" } as never)).toThrow(
      /markdown must be a string/,
    );

    const mutableRevision = JSON.parse(JSON.stringify(initial)) as typeof initial;
    const editedMutableRevision = editReportRevision(mutableRevision, "Another prose draft.");
    expect(Object.isFrozen(mutableRevision.source)).toBe(false);
    expect(Object.isFrozen(editedMutableRevision.source)).toBe(true);
  });

  it("keeps old ReportRecord objects valid without a revision field", () => {
    const legacy = record();
    expect(legacy.revision).toBeUndefined();
    expect(createReportDocument(legacy).source.source_record_id).toBe(legacy.id);
  });

  it("rejects missing source identifiers and malformed source facts", () => {
    const valid = createReportDocument(record());
    const missingIdentifiers = JSON.parse(serializeReportDocument(valid)) as Record<string, unknown>;
    const source = missingIdentifiers.source as Record<string, unknown>;
    delete source.source_record_id;
    delete source.source_run_id;

    const identifierResult = validateReportDocument(missingIdentifiers);
    expect(identifierResult.valid).toBe(false);
    if (!identifierResult.valid) {
      expect(identifierResult.errors).toEqual(expect.arrayContaining([
        "source.source_record_id is required",
        "source.source_run_id is required",
      ]));
    }

    const brokenFacts = JSON.parse(serializeReportDocument(valid)) as Record<string, unknown>;
    const brokenSource = brokenFacts.source as Record<string, unknown>;
    const sourceFacts = brokenSource.facts as Array<Record<string, unknown>>;
    delete sourceFacts[0].field;

    const factsResult = validateReportDocument(brokenFacts);
    expect(factsResult.valid).toBe(false);
    if (!factsResult.valid) {
      expect(factsResult.errors).toContain("source.facts[0].field is required");
    }
    expect(() => serializeReportDocument(brokenFacts as never)).toThrow(/source\.facts\[0\]\.field/);
  });

  it("round-trips only validated documents and freezes parsed evidence", () => {
    const original = createReportDocument(record());
    const parsed = parseReportDocument(serializeReportDocument(original));

    expect(parsed).toEqual(original);
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(Object.isFrozen(parsed.source.facts[0])).toBe(true);
    expect(() => parseReportDocument("{}"))
      .toThrow(/Invalid report document/);
  });
});
