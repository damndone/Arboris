// v1.6.11 slice C (+C-3) — the Report view (Graph | Table | Report).
//
// Deterministic part first: the fact table (scope = every node on the active
// head's path) renders before any AI call, so the user sees — and can curate —
// exactly what the model may cite. Curation is OMIT-ONLY (no value editing
// exists anywhere) and every exclusion is disclosed in the provenance line and
// stored in the history record, so leaving out inconvenient facts is always
// visible, never silent. Generated reports persist to a per-project history.
import { useEffect, useMemo, useState } from "react";
import { useForest } from "../workbench/ForestContext";
import { useWorkbenchOptional } from "../workbench/WorkbenchStateProvider";
import { buildFactTable, type CitableFact } from "./factTable";
import { DEFAULT_REPORT_INSTRUCTION, generateReport } from "./reportClient";
import { CiteChip, parseCiteSegments } from "./citeMarkup";
import {
  deleteReportRecord,
  loadReportHistory,
  makeRecordId,
  saveReportRecord,
  type ReportRecord,
} from "./reportHistory";

export function ReportView({ projectRoot }: { projectRoot?: string }) {
  const forest = useForest();
  const wb = useWorkbenchOptional();
  const historyRoot = projectRoot ?? "unknown-project";
  const [instruction, setInstruction] = useState(DEFAULT_REPORT_INSTRUCTION);
  const [current, setCurrent] = useState<ReportRecord | null>(null);
  const [history, setHistory] = useState<ReportRecord[]>([]);
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setHistory(loadReportHistory(historyRoot));
  }, [historyRoot]);

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

  const includedFacts = table.facts.filter((fact) => !excludedIds.has(fact.id));
  const jumpToNode = (nodeKey: string) => {
    if (!wb) return;
    wb.dispatch.setView("graph");
    wb.dispatch.selectByCanvasClick(nodeKey);
  };
  const toggleFact = (factId: string) => {
    setExcludedIds((prev) => {
      const next = new Set(prev);
      if (next.has(factId)) next.delete(factId);
      else next.add(factId);
      return next;
    });
  };

  async function handleGenerate() {
    if (!table) return;
    setBusy(true);
    setError(null);
    try {
      const response = await generateReport({
        facts: includedFacts,
        scope: table.scope,
        fingerprints: table.fingerprints,
        instruction,
      });
      const record: ReportRecord = {
        id: makeRecordId(),
        generatedAt: new Date().toISOString(),
        model: response.model,
        instruction,
        text: response.text,
        scope: table.scope,
        facts: table.facts, // FULL snapshot, exclusions included — audit trail
        excluded_fact_ids: [...excludedIds],
      };
      setCurrent(record);
      setHistory(saveReportRecord(historyRoot, record));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report generation failed");
    } finally {
      setBusy(false);
    }
  }

  const viewingFactsById = new Map(
    (current?.facts ?? table.facts).map((fact) => [fact.id, fact]),
  );

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
        <button
          type="button"
          onClick={handleGenerate}
          disabled={busy || includedFacts.length === 0}
        >
          {busy ? "Generating…" : "Generate report"}
        </button>
        {current && (
          <button type="button" onClick={() => setCurrent(null)}>
            New report
          </button>
        )}
      </div>

      <div
        data-testid="report-provenance"
        style={{ fontSize: 12, color: "var(--label-tertiary)", marginBottom: 12 }}
      >
        Scope: run <code>{table.scope.run_id}</code> · {table.scope.node_count} nodes ·{" "}
        {includedFacts.length} of {table.facts.length} facts included
        {excludedIds.size > 0 && (
          <strong style={{ color: "var(--diff-removed, #b35900)" }}>
            {" "}
            ({excludedIds.size} excluded by user — disclosed &amp; recorded)
          </strong>
        )}
        {current?.model && (
          <>
            {" · "}model <code>{current.model}</code> · generated {current.generatedAt}
            {current.excluded_fact_ids.length > 0 && (
              <strong style={{ color: "var(--diff-removed, #b35900)" }}>
                {" "}
                · {current.excluded_fact_ids.length} facts were excluded when this
                report was generated
              </strong>
            )}
          </>
        )}
      </div>

      {error && (
        <div
          role="alert"
          style={{ fontSize: 13, color: "var(--diff-removed, #b35900)", marginBottom: 12 }}
        >
          {error}
        </div>
      )}

      {current ? (
        <ReportBody text={current.text} factsById={viewingFactsById} onJump={jumpToNode} />
      ) : (
        <FactTablePreview
          facts={table.facts}
          excludedIds={excludedIds}
          onToggle={toggleFact}
          onJump={jumpToNode}
        />
      )}

      <HistoryList
        history={history}
        currentId={current?.id ?? null}
        onOpen={(record) => setCurrent(record)}
        onDelete={(record) => {
          setHistory(deleteReportRecord(historyRoot, record.id));
          if (current?.id === record.id) setCurrent(null);
        }}
      />
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
  excludedIds,
  onToggle,
  onJump,
}: {
  facts: CitableFact[];
  excludedIds: Set<string>;
  onToggle: (factId: string) => void;
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
      <div className="ln-section-label" style={{ marginBottom: 2 }}>
        Citable facts (what the AI may reference)
      </div>
      <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 6 }}>
        Untick a fact to leave it out of the report. Values cannot be edited;
        every exclusion is disclosed in the report's provenance and kept in its
        history record.
      </div>
      <table style={{ fontSize: 12, borderCollapse: "collapse" }}>
        <thead>
          <tr>
            {["use", "id", "node", "field", "value"].map((header) => (
              <th key={header} style={{ textAlign: "left", padding: "2px 10px 2px 0" }}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {facts.map((fact) => {
            const excluded = excludedIds.has(fact.id);
            return (
              <tr key={fact.id} style={{ opacity: excluded ? 0.45 : 1 }}>
                <td style={{ padding: "2px 10px 2px 0" }}>
                  <input
                    type="checkbox"
                    aria-label={`Include fact ${fact.id}`}
                    checked={!excluded}
                    onChange={() => onToggle(fact.id)}
                  />
                </td>
                <td style={{ padding: "2px 10px 2px 0", color: "var(--label-tertiary)" }}>
                  {fact.id}
                </td>
                <td style={{ padding: "2px 10px 2px 0" }}>
                  <button
                    type="button"
                    onClick={() => onJump(fact.node_key)}
                    style={{
                      background: "none",
                      border: "none",
                      padding: 0,
                      cursor: "pointer",
                      textDecoration: "underline",
                      fontSize: 12,
                      // global `button` is tint-bg + WHITE text; a link-style
                      // button must restore a readable label color.
                      color: "var(--tint)",
                      minHeight: 0,
                      fontWeight: 400,
                    }}
                  >
                    {fact.node_label}
                  </button>
                </td>
                <td style={{ padding: "2px 10px 2px 0" }}>{fact.field}</td>
                <td style={{ padding: "2px 10px 2px 0", fontFamily: "ui-monospace, monospace" }}>
                  {String(fact.value)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HistoryList({
  history,
  currentId,
  onOpen,
  onDelete,
}: {
  history: ReportRecord[];
  currentId: string | null;
  onOpen: (record: ReportRecord) => void;
  onDelete: (record: ReportRecord) => void;
}) {
  // Always render the section (empty state included) — an invisible feature
  // is an undiscoverable feature (user report 2026-07-12).
  if (history.length === 0) {
    return (
      <div data-testid="report-history-empty" style={{ marginTop: 24 }}>
        <div className="ln-section-label" style={{ marginBottom: 6 }}>
          Report history
        </div>
        <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
          No reports yet — every generated report is saved here (survives reload).
        </div>
      </div>
    );
  }
  return (
    <div data-testid="report-history" style={{ marginTop: 24 }}>
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Report history ({history.length})
      </div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {history.map((record) => (
          <li
            key={record.id}
            style={{ display: "flex", gap: 10, alignItems: "baseline", padding: "3px 0", fontSize: 12 }}
          >
            <button
              type="button"
              onClick={() => onOpen(record)}
              style={{
                background: "none",
                border: "none",
                padding: 0,
                cursor: "pointer",
                textDecoration: "underline",
                fontSize: 12,
                fontWeight: record.id === currentId ? 600 : 400,
                // global `button` paints WHITE text — restore a readable color.
                color: "var(--tint)",
                minHeight: 0,
              }}
            >
              {record.generatedAt}
            </button>
            <span style={{ color: "var(--label-tertiary)" }}>
              {record.model ?? "?"} · {record.facts.length - record.excluded_fact_ids.length}/
              {record.facts.length} facts
              {record.excluded_fact_ids.length > 0 && " (curated)"}
            </span>
            <span style={{ color: "var(--label-tertiary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 320 }}>
              {record.instruction}
            </span>
            <button type="button" onClick={() => onDelete(record)} aria-label={`Delete report ${record.id}`}>
              ✕
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
