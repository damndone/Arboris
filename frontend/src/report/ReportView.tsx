// v1.6.11 slice C — the Report view (Graph | Table | Report).
//
// Deterministic part first: the fact table (scope = every node on the active
// head's path) renders before any AI call, so the user sees exactly what the
// model is allowed to cite. Generate → prose with [[c:ID]] markers rendered as
// clickable chips (verified from the local table; unknown ids marked). The
// provenance line (model · facts · fingerprints) is the typed-operation-record
// seed for v1.7.
import { useMemo, useState } from "react";
import { useForest } from "../workbench/ForestContext";
import { useWorkbenchOptional } from "../workbench/WorkbenchStateProvider";
import { buildFactTable, type CitableFact } from "./factTable";
import { DEFAULT_REPORT_INSTRUCTION, generateReport } from "./reportClient";
import { CiteChip, parseCiteSegments } from "./citeMarkup";

interface GeneratedReport {
  text: string;
  model?: string;
  generatedAt: string;
}

export function ReportView() {
  const forest = useForest();
  const wb = useWorkbenchOptional();
  const [instruction, setInstruction] = useState(DEFAULT_REPORT_INSTRUCTION);
  const [report, setReport] = useState<GeneratedReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const table = useMemo(() => {
    if (!forest || !forest.activeRunId) return null;
    return buildFactTable(forest.forest, forest.activeRunId);
  }, [forest]);

  if (!forest || !forest.activeRunId || !table) {
    return (
      <div style={{ padding: 24, fontSize: 13, color: "var(--label-tertiary)" }}>
        Pick a run (version) on the graph first — the report covers the active run's lineage.
      </div>
    );
  }

  const factsById = new Map(table.facts.map((fact) => [fact.id, fact]));
  const jumpToNode = (nodeKey: string) => {
    if (!wb) return;
    wb.dispatch.setView("graph");
    wb.dispatch.selectByCanvasClick(nodeKey);
  };

  async function handleGenerate() {
    if (!table) return;
    setBusy(true);
    setError(null);
    try {
      const response = await generateReport({
        facts: table.facts,
        scope: table.scope,
        fingerprints: table.fingerprints,
        instruction,
      });
      setReport({
        text: response.text,
        model: response.model,
        generatedAt: new Date().toISOString(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report generation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="report-view"
      style={{ padding: 20, overflowY: "auto", flex: 1, minHeight: 0 }}
    >
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start", marginBottom: 12 }}>
        <textarea
          aria-label="Report instruction"
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          rows={2}
          style={{ flex: 1, fontSize: 13, padding: 8 }}
        />
        <button type="button" onClick={handleGenerate} disabled={busy || table.facts.length === 0}>
          {busy ? "Generating…" : "Generate report"}
        </button>
      </div>

      <div style={{ fontSize: 12, color: "var(--label-tertiary)", marginBottom: 12 }}>
        Scope: run <code>{table.scope.run_id}</code> · {table.scope.node_count} nodes ·{" "}
        {table.facts.length} citable facts
        {report?.model && (
          <>
            {" · "}model <code>{report.model}</code> · generated {report.generatedAt}
          </>
        )}
      </div>

      {error && (
        <div role="alert" style={{ fontSize: 13, color: "var(--diff-removed, #b35900)", marginBottom: 12 }}>
          {error}
        </div>
      )}

      {report ? (
        <ReportBody text={report.text} factsById={factsById} onJump={jumpToNode} />
      ) : (
        <FactTablePreview facts={table.facts} onJump={jumpToNode} />
      )}
    </div>
  );
}

function ReportBody({
  text,
  factsById,
  onJump,
}: {
  text: string;
  factsById: Map<string, CitableFact>;
  onJump: (nodeKey: string) => void;
}) {
  const segments = parseCiteSegments(text);
  return (
    <div
      data-testid="report-body"
      style={{ fontSize: 13, lineHeight: 1.7, whiteSpace: "pre-wrap", maxWidth: 860 }}
    >
      {segments.map((segment, index) =>
        segment.type === "text" ? (
          <span key={index}>{segment.text}</span>
        ) : (
          <CiteChip key={index} id={segment.id} fact={factsById.get(segment.id)} onJump={onJump} />
        ),
      )}
    </div>
  );
}

function FactTablePreview({
  facts,
  onJump,
}: {
  facts: CitableFact[];
  onJump: (nodeKey: string) => void;
}) {
  if (facts.length === 0) {
    return (
      <div style={{ fontSize: 13, color: "var(--label-tertiary)" }}>
        No citable facts on this run's lineage yet.
      </div>
    );
  }
  return (
    <div data-testid="report-fact-preview">
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Citable facts (what the AI may reference)
      </div>
      <table style={{ fontSize: 12, borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {["id", "node", "field", "value"].map((header) => (
              <th key={header} style={{ textAlign: "left", padding: "2px 10px 2px 0" }}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {facts.map((fact) => (
            <tr key={fact.id}>
              <td style={{ padding: "2px 10px 2px 0", color: "var(--label-tertiary)" }}>{fact.id}</td>
              <td style={{ padding: "2px 10px 2px 0" }}>
                <button
                  type="button"
                  onClick={() => onJump(fact.node_key)}
                  style={{ background: "none", border: "none", padding: 0, cursor: "pointer", textDecoration: "underline", fontSize: 12 }}
                >
                  {fact.node_label}
                </button>
              </td>
              <td style={{ padding: "2px 10px 2px 0" }}>{fact.field}</td>
              <td style={{ padding: "2px 10px 2px 0", fontFamily: "ui-monospace, monospace" }}>
                {String(fact.value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
