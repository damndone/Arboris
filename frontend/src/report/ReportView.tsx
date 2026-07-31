// v1.6.11 slice C (+C-3) — the Report view (Graph | Table | Report).
//
// Deterministic part first: the fact table (scope = every node on the active
// head's path) renders before any AI call, so the user sees — and can curate —
// exactly what the model may cite. Curation is OMIT-ONLY (no value editing
// exists anywhere) and every exclusion is disclosed in the provenance line and
// stored in the history record, so leaving out inconvenient facts is always
// visible, never silent. Generated reports persist to a per-project history.
import { useEffect, useMemo, useRef, useState } from "react";
import { useForest } from "../workbench/ForestContext";
import { useWorkbenchOptional } from "../workbench/WorkbenchStateProvider";
import {
  buildFactTable,
  buildFigureFacts,
  buildPostEstimationFacts,
  buildTimeSeriesFacts,
  type CitableFact,
} from "./factTable";
import {
  DEFAULT_REPORT_INSTRUCTION,
  exportReport,
  fetchAiReports,
  generateReport,
  saveAiReport,
  type ReportFigure,
} from "./reportClient";
import { CiteChip, parseCiteSegments } from "./citeMarkup";
import { renderMarkdown } from "./markdown";
import { appendAiActivity, makeActivityId } from "../aiActivity/aiActivityLog";
import {
  deleteReportRecord,
  loadReportHistory,
  makeRecordId,
  saveReportRecord,
  type ReportRecord,
} from "./reportHistory";
import {
  artifactDownloadUrl,
  fetchArtifactJson,
  fetchRunArtifacts,
  fetchRunDetail,
} from "../api";
import type { PostEstimationResult } from "../api";
import { fetchFigureAiContext } from "../workbench/views/figureAi";

const REPORT_TIME_SERIES_ARTIFACT_IDS = new Set([
  "ts.analysis_contract",
  "ts.data_audit",
  "ts.arma_selection",
  "ts.volatility_selection",
  "ts.final_model",
  "ts.parameters",
  "ts.final_diagnostics",
  "ts.forecast_metrics",
  "ts.next_forecast",
]);

function reportsForRun(records: ReportRecord[], runId: string | null): ReportRecord[] {
  if (!runId) return [];
  return records.filter((record) => record.scope.run_id === runId);
}

export function ReportView({ projectRoot }: { projectRoot?: string }) {
  const forest = useForest();
  const wb = useWorkbenchOptional();
  const activeRunId = forest?.activeRunId ?? null;
  // Async generation belongs to the Run whose fact snapshot was submitted.
  // Keep the latest visible Run outside a request closure so a completed Run A
  // cannot replace the report currently being viewed for Run B.
  const activeRunIdRef = useRef(activeRunId);
  activeRunIdRef.current = activeRunId;
  const historyRoot = projectRoot ?? "unknown-project";
  const [instruction, setInstruction] = useState(DEFAULT_REPORT_INSTRUCTION);
  const [current, setCurrent] = useState<ReportRecord | null>(null);
  const [history, setHistory] = useState<ReportRecord[]>([]);
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [generatingRunId, setGeneratingRunId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [reportFigures, setReportFigures] = useState<ReportFigure[]>([]);
  const [timeSeriesArtifacts, setTimeSeriesArtifacts] = useState<Record<string, unknown>>({});
  const [figureContextLoading, setFigureContextLoading] = useState(false);
  const [figureInventoryError, setFigureInventoryError] = useState<string | null>(null);
  const [postEstimation, setPostEstimation] = useState<PostEstimationResult[]>([]);

  // Declared post-estimation results are server-computed scalars with artifact
  // provenance, so they belong in the deterministic fact table. A failure here
  // is not surfaced: the report is still truthful without these facts, and the
  // figure inventory owns the visible error channel.
  useEffect(() => {
    const runId = activeRunId;
    if (!runId || !projectRoot) {
      setPostEstimation([]);
      return;
    }
    let cancelled = false;
    void fetchRunDetail(projectRoot, runId)
      .then((detail) => {
        if (!cancelled) setPostEstimation(detail.post_estimation_results ?? []);
      })
      .catch(() => {
        if (!cancelled) setPostEstimation([]);
      });
    return () => {
      cancelled = true;
    };
  }, [activeRunId, projectRoot]);

  useEffect(() => {
    const stored = loadReportHistory(historyRoot);
    const scoped = reportsForRun(stored, activeRunId);
    setHistory(scoped);
    // The report itself was never lost -- history is persisted -- but the
    // preview lived in local state, so switching tabs blanked the screen and
    // the user had to go dig it out of "Report history" to see it again.
    // Restoring the newest record makes coming back to this view show what
    // was last generated, which is what leaving it showed.
    setCurrent(scoped[0] ?? null);
  }, [activeRunId, historyRoot]);

  useEffect(() => {
    const runId = activeRunId;
    if (!projectRoot || !runId) return;
    let cancelled = false;
    void fetchAiReports({ projectRoot, runId })
      .then((records) => {
        if (cancelled || records.length === 0) return;
        const durable = reportsForRun(records as unknown as ReportRecord[], runId);
        setHistory(durable);
        setCurrent(durable[0] ?? null);
      })
      .catch(() => {
        // Local history is a cache and a sensible offline fallback. The user is
        // told about a new persistence failure at generation time instead.
      });
    return () => { cancelled = true; };
  }, [activeRunId, projectRoot]);

  useEffect(() => {
    const runId = activeRunId;
    if (!runId || !projectRoot) {
      setReportFigures([]);
      setTimeSeriesArtifacts({});
      setFigureContextLoading(false);
      setFigureInventoryError(null);
      return;
    }
    let cancelled = false;
    setFigureContextLoading(true);
    setFigureInventoryError(null);
    void fetchRunArtifacts(projectRoot, runId)
      .then(async (response) => {
        const allItems = response.groups.flatMap((group) => group.items);
        const items = allItems
          .filter((item) => item.artifact_type === "figure");
        const timeSeriesItems = allItems.filter((item) =>
          REPORT_TIME_SERIES_ARTIFACT_IDS.has(item.artifact_id),
        );
        const [resolved, resolvedTimeSeries] = await Promise.all([
          Promise.all(
            items.map(async (item) => {
              try {
                const context = await fetchFigureAiContext(projectRoot, runId, item.artifact_id);
                return {
                  artifact_id: item.artifact_id,
                  chart_type: context.figure.chart_type,
                  path: context.figure.path,
                  source: context.source,
                } satisfies ReportFigure;
              } catch {
                // The figure remains visible/exportable even when its numeric
                // source is unavailable; the report packet records that gap.
                return {
                  artifact_id: item.artifact_id,
                  chart_type: item.artifact_id,
                  source: null,
                } satisfies ReportFigure;
              }
            }),
          ),
          Promise.all(
            timeSeriesItems.map(async (item) => {
              try {
                const value = await fetchArtifactJson(projectRoot, runId, item.artifact_id);
                return [item.artifact_id, value] as const;
              } catch {
                return null;
              }
            }),
          ),
        ]);
        if (!cancelled) {
          setReportFigures(resolved);
          setTimeSeriesArtifacts(
            Object.fromEntries(resolvedTimeSeries.filter((item) => item !== null)),
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setReportFigures([]);
          setTimeSeriesArtifacts({});
          setFigureInventoryError(
            "Unable to load the run figure inventory; report generation is disabled.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setFigureContextLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeRunId, projectRoot]);

  const table = useMemo(() => {
    if (!forest || !forest.activeRunId) return null;
    return buildFactTable(forest.forest, forest.activeRunId);
  }, [forest]);

  const figureFacts = useMemo(
    () => buildFigureFacts(reportFigures, table?.facts.length ?? 0),
    [reportFigures, table?.facts.length],
  );
  const timeSeriesProvenance = useMemo(() => {
    const modelNode = forest?.forest.nodes.find(
      (node) =>
        (node.runs ?? []).includes(forest.activeRunId ?? "")
        && node.opType === "time_series.arma_garch"
        && node.kind === "model",
    );
    return modelNode
      ? { nodeKey: modelNode.nodeKey, nodeLabel: modelNode.title }
      : { nodeKey: "model:arma_garch_1", nodeLabel: "ARMA-GARCH" };
  }, [forest]);
  const timeSeriesFacts = useMemo(
    () => buildTimeSeriesFacts(
      timeSeriesArtifacts,
      (table?.facts.length ?? 0) + figureFacts.length,
      timeSeriesProvenance,
    ),
    [figureFacts.length, table?.facts.length, timeSeriesArtifacts, timeSeriesProvenance],
  );
  const postEstimationFacts = useMemo(
    () => buildPostEstimationFacts(
      postEstimation,
      (table?.facts.length ?? 0) + figureFacts.length + timeSeriesFacts.length,
    ),
    [figureFacts.length, postEstimation, table?.facts.length, timeSeriesFacts.length],
  );
  const allFacts = useMemo(
    () => (table
      ? [...table.facts, ...figureFacts, ...timeSeriesFacts, ...postEstimationFacts]
      : []),
    [figureFacts, postEstimationFacts, table, timeSeriesFacts],
  );

  if (!forest || !forest.activeRunId || !table) {
    return (
      <div style={{ padding: 24, fontSize: 13, color: "var(--label-tertiary)" }}>
        Pick a run (version) on the graph first — the report covers the active run's lineage.
      </div>
    );
  }

  const includedFacts = allFacts.filter((fact) => !excludedIds.has(fact.id));
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
    const runId = table.scope.run_id;
    setGeneratingRunId(runId);
    setError(null);
    try {
      const response = await generateReport({
        facts: includedFacts,
        scope: table.scope,
        fingerprints: table.fingerprints,
        figures: reportFigures,
        instruction,
      });
      const record: ReportRecord = {
        id: makeRecordId(),
        generatedAt: new Date().toISOString(),
        model: response.model,
        instruction,
        text: response.text,
        scope: table.scope,
        facts: allFacts, // FULL snapshot, exclusions included — audit trail
        excluded_fact_ids: [...excludedIds],
        figures: reportFigures,
      };
      if (projectRoot) {
        await saveAiReport({ projectRoot, runId: table.scope.run_id, record });
      }
      if (activeRunIdRef.current === runId) {
        setCurrent(record);
        setHistory(reportsForRun(saveReportRecord(historyRoot, record), runId));
      } else {
        // Still preserve the user-requested Run A report; only defer its view
        // update until the user explicitly returns to Run A.
        saveReportRecord(historyRoot, record);
      }
      appendAiActivity(historyRoot, {
        kind: "report_generate",
        id: makeActivityId(),
        at: record.generatedAt,
        run_id: table.scope.run_id,
        instruction,
        model: response.model,
        fact_count: includedFacts.length,
        excluded_count: excludedIds.size,
        report_record_id: record.id,
      });
    } catch (err) {
      // Leaving the previously restored report on screen next to a failure
      // invites reading it as this attempt's output. It is not lost -- it is
      // still in Report history -- but it must not stand in for a result that
      // was never produced.
      if (activeRunIdRef.current === runId) {
        setCurrent(null);
        setError(err instanceof Error ? err.message : "Report generation failed");
      }
    } finally {
      setGeneratingRunId((currentRunId) => currentRunId === runId ? null : currentRunId);
    }
  }

  async function handleExport(format: "html" | "docx" | "tex" | "pdf-print") {
    if (!current || !projectRoot) return;
    if (format === "pdf-print") {
      window.print();
      return;
    }
    setExporting(true);
    setError(null);
    try {
      const blob = await exportReport({
        projectRoot,
        runId: current.scope.run_id,
        format,
        markdown: current.text,
        figures: current.figures ?? reportFigures,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `workbench-report-${current.scope.run_id}.${format === "tex" ? "zip" : format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report export failed");
    } finally {
      setExporting(false);
    }
  }

  const viewingFactsById = new Map(
    (current?.facts ?? allFacts).map((fact) => [fact.id, fact]),
  );

  return (
    <div
      data-testid="report-view"
      style={{ padding: "12px 20px 20px", overflowY: "auto", flex: 1, minHeight: 0 }}
    >
      {forest.forest.heads.length > 0 && (
        <nav
          data-testid="report-view-run-picker"
          className="wb-run-version-picker"
          aria-label="Report run"
          style={{ margin: "-12px -20px 12px" }}
        >
          <span className="wb-run-version-picker__label">Versions:</span>
          {forest.forest.heads.map((head) => (
            <button
              key={head.runId}
              type="button"
              className="wb-run-version-picker__button"
              aria-pressed={head.runId === activeRunId}
              aria-label={`Show report for run ${head.runId}`}
              title={head.runId}
              onClick={() => forest.setActiveRunId(head.runId)}
            >
              {head.runId.slice(-8)}
            </button>
          ))}
        </nav>
      )}
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
          disabled={
            generatingRunId === activeRunId ||
            figureContextLoading ||
            figureInventoryError !== null ||
            includedFacts.length === 0
          }
        >
          {generatingRunId === activeRunId
            ? "Generating…"
            : figureContextLoading
              ? "Loading figures…"
              : "Generate report"}
        </button>
        {current && (
          <>
            <button type="button" onClick={() => setCurrent(null)}>
              New report
            </button>
            <label style={{ fontSize: 12 }}>
              <span className="sr-only">Download report</span>
              <select
                aria-label="Download report"
                disabled={exporting || !projectRoot}
                defaultValue=""
                onChange={(event) => {
                  const value = event.target.value as "html" | "docx" | "tex" | "pdf-print" | "";
                  if (value) void handleExport(value);
                  event.target.value = "";
                }}
              >
                <option value="">Download…</option>
                <option value="html">HTML</option>
                <option value="docx">Word</option>
                <option value="tex">LaTeX (.zip)</option>
                <option value="pdf-print">Print / PDF</option>
              </select>
            </label>
          </>
        )}
      </div>

      <div
        data-testid="report-provenance"
        style={{ fontSize: 12, color: "var(--label-tertiary)", marginBottom: 12 }}
      >
        Scope: run <code>{table.scope.run_id}</code> · {table.scope.node_count} nodes ·{" "}
        {includedFacts.length} of {allFacts.length} facts included
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

      {figureInventoryError && (
        <div
          role="alert"
          style={{ fontSize: 13, color: "var(--diff-removed, #b35900)", marginBottom: 12 }}
        >
          {figureInventoryError}
        </div>
      )}

      {current ? (
        <ReportBody
          text={current.text}
          factsById={viewingFactsById}
          figures={current.figures ?? reportFigures}
          projectRoot={projectRoot ?? ""}
          runId={current.scope.run_id}
          onJump={jumpToNode}
        />
      ) : (
        <FactTablePreview
          facts={allFacts}
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
          setHistory(reportsForRun(deleteReportRecord(historyRoot, record.id), activeRunId));
          if (current?.id === record.id) setCurrent(null);
        }}
      />
      {figureContextLoading && !current && (
        <div style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
          Loading numeric sources for report figures…
        </div>
      )}
    </div>
  );
}

function ReportBody({
  text,
  factsById,
  figures,
  projectRoot,
  runId,
  onJump,
}: {
  text: string;
  factsById: Map<string, CitableFact>;
  figures: ReportFigure[];
  projectRoot: string;
  runId: string;
  onJump: (nodeKey: string) => void;
}) {
  // v1.6.12 (V5): markdown blocks; [[c:ID]] markers become chips inside every
  // plain-text leaf via the renderTextSpan seam (bold/list content included).
  const figureById = new Map(figures.map((figure) => [figure.artifact_id, figure]));
  const renderCiteSpan = (span: string, key: string) => {
    const parts = span.split(/(\[\[fig:[A-Za-z0-9._-]+\]\])/g);
    return (
      <span key={key}>
        {parts.map((part, index) => {
          const figureMatch = /^\[\[fig:([A-Za-z0-9._-]+)\]\]$/.exec(part);
          if (figureMatch) {
            const figure = figureById.get(figureMatch[1]);
            return figure ? (
              <img
                key={index}
                src={artifactDownloadUrl(projectRoot, runId, figure.artifact_id)}
                alt={`${figure.chart_type} figure`}
                data-testid={`report-figure-${figure.artifact_id}`}
                style={{ display: "block", width: "100%", margin: "10px 0" }}
              />
            ) : (
              <span key={index}>[Figure unavailable: {figureMatch[1]}]</span>
            );
          }
          return (
            <span key={index}>
              {parseCiteSegments(part).map((segment, segmentIndex) =>
                segment.type === "text" ? (
                  <span key={segmentIndex}>{segment.text}</span>
                ) : (
                  <CiteChip key={segmentIndex} id={segment.id} fact={factsById.get(segment.id)} onJump={onJump} />
                ),
              )}
            </span>
          );
        })}
      </span>
    );
  };
  return (
    <div data-testid="report-body" style={{ fontSize: 13, maxWidth: 860 }}>
      {renderMarkdown(text, renderCiteSpan)}
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
