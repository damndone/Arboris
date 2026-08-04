import { useEffect, useRef, useState } from "react";
import { useForest } from "../workbench/ForestContext";
import { useWorkbenchOptional } from "../workbench/WorkbenchStateProvider";
import {
  displayEvidenceLabel,
  groupFactIds,
  groupFacts,
} from "./reportEvidence";
import {
  REPORT_PROMPT_PLACEHOLDER,
} from "./reportClient";
import { ReportFigureSelection } from "./ReportFigureSelection";
import { ReportComposer } from "./ReportComposer";
import { PredictionResearchReportSections } from "./PredictionResearchReportSections";
import {
  buildRegressionTablePacket,
  RegressionTable,
} from "./RegressionTable";
import {
  FamilyEvidence,
  type FamilyModelResult,
} from "./FamilyEvidence";
import {
  ReportWorkspaceProvider,
  useReportWorkspaceOptional,
  useReportWorkspace,
} from "./ReportWorkspaceContext";
import type { CitableFact } from "./factTable";
import type { ReportRecord } from "./reportHistory";
import "./report.css";

export function ReportView({ projectRoot, focusRequest = 0 }: { projectRoot?: string; focusRequest?: number }) {
  const workspace = useReportWorkspaceOptional();
  if (workspace) return <ReportViewContent focusRequest={focusRequest} />;
  return (
    <ReportWorkspaceProvider projectRoot={projectRoot}>
      <ReportViewContent focusRequest={focusRequest} />
    </ReportWorkspaceProvider>
  );
}

/** Center-column report writing surface. Review prose is rendered by ReportReviewPanel. */
export function ReportViewContent({ focusRequest = 0 }: { focusRequest?: number } = {}) {
  const forest = useForest();
  const wb = useWorkbenchOptional();
  const workspace = useReportWorkspace();
  const table = workspace.table;
  const activeRunId = workspace.activeRunId;
  const excludedIds = new Set(workspace.excludedFactIds);
  const excludedFigureIds = new Set(workspace.excludedFigureIds);

  if (!forest || !forest.activeRunId || !table) {
    return (
      <div style={{ padding: 24, fontSize: 13, color: "var(--label-tertiary)" }}>
        Pick a run (version) on the graph first — the report covers the active run's lineage.
      </div>
    );
  }

  const jumpToNode = (nodeKey: string) => {
    if (!wb) return;
    wb.dispatch.setView("graph");
    wb.dispatch.selectByCanvasClick(nodeKey);
  };
  const regressionTable = buildRegressionTablePacket(workspace.modelResults);
  const resultFamilies = [...new Set(
    workspace.modelResults.map((result) => result.model_type?.trim() || "unknown model"),
  )];
  const hasCurrentReport = workspace.current !== null;
  const promptValue = hasCurrentReport ? workspace.revisionInstruction : workspace.instruction;
  const promptChange = hasCurrentReport
    ? workspace.onRevisionInstructionChange
    : workspace.onInstructionChange;
  const promptSubmit = hasCurrentReport
    ? () => void workspace.reviseReport()
    : () => void workspace.generateReport();

  return (
    <div
      data-testid="report-view"
      className="report-page"
      style={{
        boxSizing: "border-box",
        width: "100%",
        minWidth: 0,
        padding: "12px 20px 20px",
        overflowY: "auto",
        flex: 1,
        minHeight: 0,
      }}
    >
      <style>{`@media print {
        body * { visibility: hidden !important; }
        [data-testid="report-body"], [data-testid="report-body"] * { visibility: visible !important; }
        [data-testid="report-body"] { position: absolute !important; left: 0 !important; top: 0 !important; max-width: none !important; width: 100% !important; }
      }`}</style>
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

      <ReportComposer
        value={promptValue}
        onChange={promptChange}
        onSubmit={promptSubmit}
        submitLabel={hasCurrentReport ? "Revise draft" : "Generate report"}
        placeholder={REPORT_PROMPT_PLACEHOLDER}
        ariaLabel={hasCurrentReport ? "Report revision instruction" : "Report instruction"}
        contextLines={workspace.reportContextLines}
        contextDetails={workspace.reportContextDetails}
        contextUsedTokens={workspace.reportContextUsedTokens}
        focusRequest={focusRequest}
        allowEmptySubmit={!hasCurrentReport}
        busy={workspace.generating}
        disabled={
          workspace.figureContextLoading
          || workspace.figureInventoryError !== null
          || workspace.includedFacts.length === 0
        }
      />

      <ReportActionBar />

      <section data-testid="report-scope-summary" className="report-scope-summary">
        <div className="report-scope-summary__heading">
          <div>
            <strong>Scope</strong>
            <span>What this report covers</span>
          </div>
          <span className="report-scope-summary__hint">
            Defines the run and lineage boundary; it does not change Workbench data.
          </span>
        </div>
        <div
          data-testid="report-provenance"
          className="report-scope-summary__facts"
        >
          <div>
            Run <code>{table.scope.run_id}</code> · {table.scope.node_count} lineage nodes
          </div>
          <div>
            Evidence inventory: {workspace.allFacts.length} facts in provenance · next writer packet: {workspace.includedFacts.length} of {workspace.allFacts.length} selected
            {excludedIds.size > 0 && (
              <strong className="report-scope-summary__warning">
                {" "}({excludedIds.size} excluded by user — disclosed &amp; recorded)
              </strong>
            )}
          </div>
          <div>
            Figure inventory: {workspace.reportFigures.length} figures in provenance · next writer packet: {workspace.includedFigures.length} of {workspace.reportFigures.length} selected
            {excludedFigureIds.size > 0 && (
              <strong className="report-scope-summary__warning">
                {" "}({excludedFigureIds.size} figure{excludedFigureIds.size === 1 ? "" : "s"} omitted from the writer packet)
              </strong>
            )}
          </div>
          {workspace.current?.model && (
            <div>
              Model <code>{workspace.current.model}</code> · generated {workspace.current.generatedAt}
              {workspace.current.excluded_fact_ids.length > 0 && (
                <strong className="report-scope-summary__warning">
                  {" "}· {workspace.current.excluded_fact_ids.length} facts were excluded when this report was generated
                </strong>
              )}
            </div>
          )}
          {workspace.current && (workspace.current.report_standard || workspace.currentQualityStatus) && (
            <div data-testid="report-quality-status">
              Standard <code>{workspace.current.report_standard ?? "legacy"}</code> · quality{" "}
              <code>{workspace.currentQualityStatus ?? "unknown"}</code>
            </div>
          )}
          {workspace.currentIsStale && (
            <strong data-testid="report-stale" className="report-scope-summary__warning">
              Source evidence changed; this revision is stale.
            </strong>
          )}
        </div>
      </section>

      <div data-testid="report-scope-divider" className="report-scope-divider">
        <span className="report-scope-divider__title">Regression evidence</span>
        <span>Source output from this run; it remains in provenance and is not automatically sent to the writer.</span>
      </div>

      {workspace.current && workspace.currentQualityStatus && workspace.currentQualityStatus !== "exportable" && (
        <div
          data-testid="report-quality-issues"
          style={{ fontSize: 12, color: "var(--diff-removed, #b35900)", marginBottom: 12 }}
        >
          This revision needs attention before formal export: {workspace.current.report_quality?.violations?.map((item) => typeof item === "string" ? item : item.message).join("; ") || workspace.currentQualityStatus}.
        </div>
      )}

      {workspace.error && (
        <div role="alert" style={{ fontSize: 13, color: "var(--diff-removed, #b35900)", marginBottom: 12 }}>
          {workspace.error}
        </div>
      )}

      {workspace.figureInventoryError && (
        <div role="alert" style={{ fontSize: 13, color: "var(--diff-removed, #b35900)", marginBottom: 12 }}>
          {workspace.figureInventoryError}
        </div>
      )}

      <PredictionResearchReportSections evidence={workspace.predictionEvidence} />
      <RegressionTable packet={regressionTable} />
      <FamilyEvidence
        modelResults={workspace.modelResults as unknown as FamilyModelResult[]}
        artifacts={workspace.familyEvidenceArtifacts}
      />

      <div data-testid="report-evidence-divider" className="report-evidence-divider">
        <span className="report-evidence-divider__title">
          Report evidence (what the AI may reference)
        </span>
        <span className="report-evidence-divider__note">
          Regression evidence above is source output; this section is the citable report context.
        </span>
      </div>
      <FactTablePreview
        facts={workspace.allFacts}
        excludedIds={excludedIds}
        onToggle={workspace.toggleFact}
        onJump={jumpToNode}
        showHeading={false}
      />
      <ReportFigureSelection
        figures={workspace.reportFigures}
        excludedFigureIds={excludedFigureIds}
        onToggle={workspace.toggleFigure}
        onUseRecommended={workspace.useRecommendedFigures}
        onIncludeAll={workspace.includeAllFigures}
      />

      <HistoryList
        history={workspace.history}
        currentId={workspace.current?.id ?? null}
        onOpen={workspace.openReport}
        onDelete={workspace.deleteReport}
      />
      {workspace.figureContextLoading && !workspace.current && (
        <div style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
          Loading numeric sources for report figures…
        </div>
      )}

      <span aria-hidden="true" data-report-result-families={resultFamilies.join(",")} hidden />
    </div>
  );
}

function ReportActionBar() {
  const workspace = useReportWorkspace();
  const [moreFormatsOpen, setMoreFormatsOpen] = useState(false);
  const moreFormatsRef = useRef<HTMLDivElement>(null);
  const hasReport = workspace.current !== null;

  useEffect(() => {
    if (!moreFormatsOpen) return undefined;
    const closeOnOutsidePress = (event: MouseEvent) => {
      const target = event.target;
      if (target instanceof Node && moreFormatsRef.current?.contains(target)) return;
      setMoreFormatsOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMoreFormatsOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsidePress);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsidePress);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [moreFormatsOpen]);

  const exportFormat = (format: "html" | "docx" | "tex") => {
    setMoreFormatsOpen(false);
    void workspace.exportReport(format);
  };

  return (
    <div className="report-action-bar" data-testid="report-action-bar">
      <button type="button" aria-label="New report" onClick={workspace.startNewReport}>
        New
      </button>
      <button
        type="button"
        aria-label="Edit report"
        onClick={workspace.beginEditing}
        disabled={!hasReport || workspace.editing}
      >
        Edit
      </button>
      <button
        type="button"
        aria-label="Export report"
        title="Download the current report"
        onClick={() => void workspace.exportReport("pdf-print")}
        disabled={workspace.exporting || !workspace.projectRoot || !workspace.reportExportAllowed || !hasReport}
      >
        Export
      </button>
      <button
        type="button"
        aria-label="Export result table"
        title="Download the authoritative result table as XLSX"
        onClick={() => void workspace.exportResultTable()}
        disabled={workspace.resultTableExporting || !workspace.projectRoot || !hasReport}
      >
        Result table
      </button>
      <div className="report-action-bar__more" ref={moreFormatsRef}>
        <button
          type="button"
          aria-label="More formats"
          aria-expanded={moreFormatsOpen}
          onClick={() => setMoreFormatsOpen((open) => !open)}
        >
          More formats <span aria-hidden="true">▾</span>
        </button>
        {moreFormatsOpen && (
          <div className="report-action-bar__menu" role="menu" aria-label="More report formats">
            <button type="button" role="menuitem" onClick={() => exportFormat("html")} disabled={!hasReport || !workspace.reportExportAllowed}>
              HTML
            </button>
            <button type="button" role="menuitem" onClick={() => exportFormat("docx")} disabled={!hasReport || !workspace.reportExportAllowed}>
              Word
            </button>
            <button type="button" role="menuitem" onClick={() => exportFormat("tex")} disabled={!hasReport || !workspace.reportExportAllowed}>
              LaTeX (.zip)
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function FactTablePreview({
  facts,
  excludedIds,
  onToggle,
  onJump,
  showHeading = true,
}: {
  facts: CitableFact[];
  excludedIds: ReadonlySet<string>;
  onToggle: (factId: string) => void;
  onJump: (nodeKey: string) => void;
  showHeading?: boolean;
}) {
  if (facts.length === 0) {
    return (
      <div style={{ fontSize: 13, color: "var(--label-tertiary)" }}>
        No citable facts on this run's lineage yet.
      </div>
    );
  }
  return (
    <div data-testid="report-fact-preview" className="report-fact-preview">
      {showHeading && (
        <div className="ln-section-label" style={{ marginBottom: 2 }}>
          Report evidence (what the AI may reference)
        </div>
      )}
      <div className="report-fact-preview__description" style={{ fontSize: 11, color: "var(--label-tertiary)" }}>
        Inventory is the full provenance snapshot. Only rows in the next writer packet
        are sent on the next generation; Workbench values are read-only and exclusions
        are disclosed in report provenance and history.
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {groupFacts(facts).map((group) => {
          const ids = groupFactIds(group);
          const includedCount = ids.filter((id) => !excludedIds.has(id)).length;
          const setGroupIncluded = (included: boolean) => {
            ids.forEach((id) => {
              const currentlyIncluded = !excludedIds.has(id);
              if (currentlyIncluded !== included) onToggle(id);
            });
          };
          return (
            <details key={group.id}>
              <summary
                style={{
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: 600,
                  padding: "5px 0",
                  listStylePosition: "outside",
                }}
              >
                {group.label} <span style={{ color: "var(--label-tertiary)", fontWeight: 400 }}>
                  Next writer packet: {includedCount}/{group.facts.length} selected
                </span>
              </summary>
              <div style={{ display: "flex", gap: 6, margin: "0 0 4px 14px" }}>
                <button type="button" onClick={() => setGroupIncluded(true)} style={{ fontSize: 11, minHeight: 0, padding: "2px 6px" }}>
                  Include all
                </button>
                <button type="button" onClick={() => setGroupIncluded(false)} style={{ fontSize: 11, minHeight: 0, padding: "2px 6px" }}>
                  Exclude all
                </button>
              </div>
              <table style={{ fontSize: 12, borderCollapse: "collapse", marginLeft: 14 }}>
                <thead>
                  <tr>
                    {["use", "evidence", "source", "value", "details"].map((header) => (
                      <th key={header} style={{ textAlign: "left", padding: "2px 10px 2px 0" }}>{header}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {group.facts.map((fact) => {
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
                        <td style={{ padding: "2px 10px 2px 0" }}>{displayEvidenceLabel(fact)}</td>
                        <td style={{ padding: "2px 10px 2px 0" }}>
                          <button
                            type="button"
                            onClick={() => onJump(fact.node_key)}
                            style={{ background: "none", border: "none", padding: 0, cursor: "pointer", textDecoration: "underline", fontSize: 12, color: "var(--tint)", minHeight: 0, fontWeight: 400 }}
                          >
                            {fact.node_label}
                          </button>
                        </td>
                        <td style={{ padding: "2px 10px 2px 0", fontFamily: "ui-monospace, monospace" }}>{String(fact.value)}</td>
                        <td style={{ padding: "2px 10px 2px 0" }}>
                          <details>
                            <summary style={{ cursor: "pointer", color: "var(--tint)", fontSize: 11 }}>
                              Evidence details for fact {fact.id}
                            </summary>
                            <div style={{ fontSize: 11, color: "var(--label-tertiary)", paddingTop: 3 }}>
                              <div>id: {fact.id}</div>
                              <div>field: {fact.field}</div>
                              <div>node: {fact.node_key}</div>
                            </div>
                          </details>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </details>
          );
        })}
      </div>
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
  if (history.length === 0) {
    return (
      <div data-testid="report-history-empty" style={{ marginTop: 24 }}>
        <div className="ln-section-label" style={{ marginBottom: 6 }}>Report history</div>
        <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
          No reports yet — every generated report is saved here (survives reload).
        </div>
      </div>
    );
  }
  return (
    <div data-testid="report-history" style={{ marginTop: 24 }}>
      <div className="ln-section-label" style={{ marginBottom: 6 }}>Report history ({history.length})</div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {history.map((record) => (
          <li key={record.id} style={{ display: "flex", gap: 10, alignItems: "baseline", padding: "3px 0", fontSize: 12 }}>
            <button
              type="button"
              onClick={() => onOpen(record)}
              style={{ background: "none", border: "none", padding: 0, cursor: "pointer", textDecoration: "underline", fontSize: 12, fontWeight: record.id === currentId ? 600 : 400, color: "var(--tint)", minHeight: 0 }}
            >
              {record.generatedAt}
            </button>
            <span style={{ color: "var(--label-tertiary)" }}>
              {record.model ?? "?"} · {record.facts.length - record.excluded_fact_ids.length}/{record.facts.length} facts
              {record.figures && <> · {record.figures.length - (record.excluded_figure_ids?.length ?? 0)}/{record.figures.length} figures</>}
              {(record.excluded_fact_ids.length > 0 || (record.excluded_figure_ids?.length ?? 0) > 0) && " (curated)"}
            </span>
            <span style={{ color: "var(--label-tertiary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 320 }}>
              {record.instruction}
            </span>
            <button type="button" onClick={() => onDelete(record)} aria-label={`Delete report ${record.id}`}>✕</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
