import type { CitableFact } from "./factTable";
import type { ReportFigure } from "./reportClient";
import type { ReportRecord } from "./reportHistory";
import type { KeyboardEvent as ReactKeyboardEvent, PointerEvent as ReactPointerEvent } from "react";
import { artifactDownloadUrl } from "../api";
import { CiteChip, parseCiteSegments } from "./citeMarkup";
import { renderMarkdown } from "./markdown";
import { useReportWorkspace } from "./ReportWorkspaceContext";
import { displayEvidenceLabel, groupFacts } from "./reportEvidence";
import { PanelWindowControls, PanelWindowDragHandle } from "../workbench/PanelWindowControls";
import "./report.css";

export interface ReportReviewPanelProps {
  floating?: boolean;
  pinned?: boolean;
  collapsed?: boolean;
  dragging?: boolean;
  onFloat?: () => void;
  onDock?: () => void;
  onPin?: () => void;
  onUnpin?: () => void;
  onCollapse?: () => void;
  onExpand?: () => void;
  onOpenReport?: () => void;
  onDragPointerDown?: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onDragKeyDown?: (event: ReactKeyboardEvent<HTMLButtonElement>) => void;
}

export function ReportReviewPanel({
  floating = false,
  pinned = false,
  collapsed = false,
  dragging = false,
  onFloat,
  onDock,
  onPin,
  onUnpin,
  onCollapse,
  onExpand,
  onOpenReport,
  onDragPointerDown,
  onDragKeyDown,
}: ReportReviewPanelProps = {}) {
  const workspace = useReportWorkspace();
  const { current } = workspace;
  const currentIncludedFacts = workspace.currentIncludedFacts ?? current?.facts ?? [];
  const currentIncludedFigures = workspace.currentIncludedFigures ?? current?.figures ?? [];

  return (
    <aside
      data-testid="report-review-panel"
      data-floating={floating ? "true" : "false"}
      data-pinned={pinned ? "true" : "false"}
      data-collapsed={collapsed ? "true" : "false"}
      className={`report-review-panel${dragging ? " report-review-panel--dragging" : ""}`}
      aria-label="Report review"
    >
      <header className="report-review-panel__header">
        <PanelWindowDragHandle
          surface="report review"
          floating={floating}
          pinned={pinned}
          dragging={dragging}
          onPointerDown={onDragPointerDown}
          onKeyDown={onDragKeyDown}
        />
        <div className="report-review-panel__heading">
          <h2 className="report-review-panel__title">Report review</h2>
          {current && (
            <div className="report-review-panel__meta">
              Run <code>{current.scope.run_id}</code> · {current.model ?? "unknown model"} · {current.generatedAt}
            </div>
          )}
        </div>
        <PanelWindowControls
          surface="report review"
          floating={floating}
          pinned={pinned}
          collapsed={collapsed}
          onFloat={onFloat}
          onDock={onDock}
          onPin={onPin}
          onUnpin={onUnpin}
          onCollapse={onCollapse}
          onExpand={onExpand}
        />
      </header>

      {!collapsed && (!current ? (
        <div
          data-testid={workspace.reportLoadError ? "report-review-load-error" : "report-review-empty"}
          className="report-review-panel__empty"
          role={workspace.reportLoadError ? "alert" : undefined}
        >
          <strong>{workspace.reportLoadError ? "Report failed to load" : "No report yet"}</strong>
          <p>{workspace.reportLoadError ?? "This run has not produced a report yet; the writing area on the Report tab creates one."}</p>
          {onOpenReport && (
            <button type="button" onClick={onOpenReport}>Open Report</button>
          )}
        </div>
      ) : (
        <>
          {workspace.reportLoadError && (
            <div data-testid="report-review-load-warning" className="report-review-panel__load-warning" role="alert">
              The report could not be loaded from the server; showing the local cache: {workspace.reportLoadError}
            </div>
          )}
          <div className="report-review-panel__status">
            <span data-testid="report-review-provenance-summary">
              Evidence inventory: <code>{current.facts.length}</code> facts · <code>{current.figures?.length ?? 0}</code> figures in provenance
            </span>
            <span>
              Report sent packet: <code>{currentIncludedFacts.length}</code> facts · <code>{currentIncludedFigures.length}</code> figures sent
            </span>
            {workspace.currentQualityStatus && (
              <span data-testid="report-review-quality">
                Quality: <code>{workspace.currentQualityStatus}</code>
              </span>
            )}
            {workspace.currentIsStale && (
              <strong data-testid="report-review-stale">
                Source evidence changed; this revision is stale.
              </strong>
            )}
          </div>

          {workspace.editing ? (
            <div data-testid="report-editor" className="report-review-panel__editor">
              <div className="ln-section-label">
                Edit report prose <span>· source evidence is read-only</span>
              </div>
              <ReadOnlyEvidenceSummary record={current} />
              <textarea
                aria-label="Report editor"
                value={workspace.editorText}
                onChange={(event) => workspace.onEditorTextChange(event.target.value)}
                rows={18}
              />
              <div className="report-review-panel__editor-actions">
                <button type="button" onClick={() => void workspace.saveRevision()}>Save revision</button>
                <button type="button" onClick={workspace.cancelEditing}>Cancel</button>
                <button type="button" onClick={workspace.resetEditor}>Reset to generated draft</button>
              </div>
              <div className="report-review-panel__note">
                Run, facts, figures, model results, and diagnostics are preserved from the source report.
              </div>
            </div>
          ) : (
            <ReportBody
              text={current.text}
              factsById={workspace.currentFactsById}
              figures={current.figures ?? workspace.reportFigures}
              projectRoot={workspace.projectRoot ?? ""}
              runId={current.scope.run_id}
              onJump={workspace.jumpToNode}
            />
          )}

          <div className="report-review-panel__footer">
            <div className="report-review-panel__guardrail">
              Agent may revise prose only. Source facts, results, and lineage remain read-only.
            </div>
          </div>
        </>
      ))}
    </aside>
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
  factsById: ReadonlyMap<string, CitableFact>;
  figures: readonly ReportFigure[];
  projectRoot: string;
  runId: string;
  onJump: (nodeKey: string) => void;
}) {
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
                  <CiteChip
                    key={segmentIndex}
                    id={segment.id}
                    fact={factsById.get(segment.id)}
                    onJump={onJump}
                  />
                ),
              )}
            </span>
          );
        })}
      </span>
    );
  };

  return (
    <div data-testid="report-body" className="report-review-panel__body">
      {renderMarkdown(text, renderCiteSpan)}
    </div>
  );
}

function ReadOnlyEvidenceSummary({ record }: { record: ReportRecord }) {
  return (
    <details data-testid="report-readonly-evidence" className="report-review-panel__evidence">
      <summary>Source evidence snapshot (read-only) · {record.facts.length} facts</summary>
      <div>
        {record.fact_snapshot_hash && <div>fact snapshot: <code>{record.fact_snapshot_hash}</code></div>}
        {record.artifact_ids && record.artifact_ids.length > 0 && (
          <div>artifacts: {record.artifact_ids.map((id) => <code key={id}>{id} </code>)}</div>
        )}
        {groupFacts(record.facts).map((group) => (
          <div key={group.id}>
            <strong>{group.label}</strong>
            {group.facts.map((fact) => (
              <div key={fact.id}>
                {displayEvidenceLabel(fact)}: <code>{String(fact.value)}</code> · {fact.id}
                {record.excluded_fact_ids.includes(fact.id) && " · excluded"}
              </div>
            ))}
          </div>
        ))}
      </div>
    </details>
  );
}
