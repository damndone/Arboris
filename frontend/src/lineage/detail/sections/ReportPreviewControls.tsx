import { useState } from "react";
import type { Schema } from "../../../apiTypes";
import type { ReportPreviewSelection } from "../../api/reportPreviewSelection";
import "../../tokens/lineage.css";

export type { ReportPreviewSelection } from "../../api/reportPreviewSelection";

type Report = Schema<"GraphReportPreview">;
type Interval = Schema<"GraphReportInterval">;
const LEVELS = [0.9, 0.95, 0.99];

export function resolveReportPreviewSelection(report: Report, selection?: ReportPreviewSelection) {
  const choice = selection ?? { term: report.default_term, level: null };
  const coefficient = report.coefficients.find((entry) => entry.term === choice.term);
  const saved = coefficient?.saved_interval ?? null;
  const usesSaved = choice.level === null || choice.level === saved?.level;
  const interval = usesSaved ? saved : coefficient?.intervals.find((entry) => entry.level === choice.level) ?? null;
  return { choice, coefficient, interval, usesSaved };
}

export function formatReportPreviewInterval(interval: Interval, digits?: number): string {
  const format = (value: number) => String(digits === undefined ? value : Number(value.toPrecision(digits)));
  const label = interval.level === null ? "CI" : `${formatPercent(interval.level)} CI`;
  return `${label} [${format(interval.lower)}, ${format(interval.upper)}]`;
}

function formatPercent(level: number): string {
  return `${Number((level * 100).toPrecision(8))}%`;
}

export function ReportPreviewControls({ report, selection, onSelectionChange }: {
  report: Report;
  selection?: ReportPreviewSelection;
  onSelectionChange?: (next: ReportPreviewSelection) => void;
}) {
  const [local, setLocal] = useState<ReportPreviewSelection>();
  const { choice, coefficient, interval, usesSaved } = resolveReportPreviewSelection(report, selection ?? local);
  const change = onSelectionChange ?? setLocal;
  const saved = coefficient?.saved_interval;
  const reference = report.distribution === "t" ? `Student t inference (df ${report.df})` : "normal (z) inference";
  const selectStyle = { maxWidth: "100%", width: "100%", minWidth: 0 };

  return (
    <section aria-label="Report coefficient" className="ln-report-preview-controls">
      <label>
        Coefficient
        <select
          value={coefficient?.term ?? ""}
          onChange={(event) => change({ ...choice, term: event.target.value || null })}
          style={selectStyle}
        >
          <option value="" disabled>Choose a saved coefficient</option>
          {report.coefficients.map((entry) => <option key={entry.term} value={entry.term}>{entry.label}</option>)}
        </select>
      </label>
      <label>
        Confidence level
        <select
          value={usesSaved ? "saved" : String(choice.level)}
          onChange={(event) => change({ ...choice, level: event.target.value === "saved" ? null : Number(event.target.value) })}
          disabled={!coefficient}
          style={selectStyle}
        >
          <option value="saved">{saved?.level != null ? `Saved (${formatPercent(saved.level)})` : "Saved interval"}</option>
          {LEVELS.filter((level) => level !== saved?.level).map((level) => (
            <option key={level} value={level} disabled={!coefficient?.intervals.some((entry) => entry.level === level)}>
              {formatPercent(level)}
            </option>
          ))}
        </select>
      </label>
      {coefficient && (
        <div aria-live="polite" data-testid="report-coefficient-inference">
          <div title={coefficient.estimate?.toString()}>
            Estimate {coefficient.estimate == null ? "unavailable" : Number(coefficient.estimate.toPrecision(6))}
            {" · Saved p "}{coefficient.p_value ?? "unavailable"}
          </div>
          <div title={interval ? formatReportPreviewInterval(interval) : undefined}>
            {interval ? formatReportPreviewInterval(interval, 6) : "Confidence interval unavailable"}
          </div>
          {interval && <div>{usesSaved ? "Saved interval" : `Computed from saved ${reference}`}</div>}
          {!usesSaved && saved && (
            <div title={formatReportPreviewInterval(saved)}>Saved interval <span>{formatReportPreviewInterval(saved, 6)}</span></div>
          )}
          {coefficient.interval_unavailable && <div>{coefficient.interval_unavailable}</div>}
        </div>
      )}
    </section>
  );
}
