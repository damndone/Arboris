import { useState } from "react";
import type { ReportFigure } from "./reportClient";
import { includedReportFigures } from "./reportSelection";

export interface ReportFigureSelectionProps {
  figures: readonly ReportFigure[];
  excludedFigureIds: ReadonlySet<string>;
  onToggle: (artifactId: string) => void;
  onUseRecommended: () => void;
  onIncludeAll: () => void;
}

/**
 * The figure packet is deliberately separate from the fact table.  The user
 * can reduce what the writer sees without deleting or changing any Run
 * artifact; the parent record keeps the complete figure inventory for
 * provenance and export.
 */
export function ReportFigureSelection({
  figures,
  excludedFigureIds,
  onToggle,
  onUseRecommended,
  onIncludeAll,
}: ReportFigureSelectionProps) {
  const [open, setOpen] = useState(false);
  const included = includedReportFigures(figures, [...excludedFigureIds]);

  return (
    <section
      data-testid="report-figure-selection"
      className="report-figure-selection"
      aria-label="Report figure evidence"
    >
      <div className="report-figure-selection__summary">
        <div>
          <strong>Figures for the report writer</strong>
          <span>Inventory: {figures.length} in provenance · Next writer packet: {included.length} selected</span>
        </div>
        <button
          type="button"
          className="report-figure-selection__toggle"
          aria-expanded={open}
          aria-controls="report-figure-selection-list"
          onClick={() => setOpen((value) => !value)}
          disabled={figures.length === 0}
        >
          {open ? "Hide figure choices" : "Choose figures"}
        </button>
      </div>
      <div className="report-figure-selection__note">
        Only selected figures are sent to the writer. Full figure inventory remains in report provenance.
      </div>
      {open && (
        <div
          id="report-figure-selection-list"
          className="report-figure-selection__list"
        >
          {figures.length === 0 ? (
            <div className="report-figure-selection__empty">No figure artifacts are available for this Run.</div>
          ) : (
            figures.map((figure) => {
              const includedFigure = !excludedFigureIds.has(figure.artifact_id);
              return (
                <label key={figure.artifact_id} className="report-figure-selection__item">
                  <input
                    className="report-figure-selection__checkbox"
                    type="checkbox"
                    aria-label={`Include figure ${figure.artifact_id}`}
                    checked={includedFigure}
                    onChange={() => onToggle(figure.artifact_id)}
                  />
                  <span className="report-figure-selection__item-text">
                    <strong>{figure.artifact_id}</strong>
                    <span>{figure.chart_type}</span>
                  </span>
                </label>
              );
            })
          )}
          <div className="report-figure-selection__actions">
            <button type="button" onClick={onUseRecommended} disabled={figures.length === 0}>
              Use recommended
            </button>
            <button type="button" onClick={onIncludeAll} disabled={figures.length === 0}>
              Include all figures
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
