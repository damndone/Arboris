import type { ModelResult, PostEstimationResult, RunDetail } from "../../api";
import { buildRepeatedMeasuresViewModel } from "../repeatedMeasures/repeatedMeasuresViewModel";
import { buildRegressionTablePacket, RegressionTable } from "../../report/RegressionTable";
import type { SignificanceLevels } from "../../report/RegressionTable";
import { formatPValue } from "../../format/numbers";
import { PostEstimationFields } from "../../workspace/result/PostEstimationResults";
import { describeInference, describeSuppressedInference, nobsBasis } from "../../format/inference";
import { fmt, groupLabel, notEstimableGroups, pooledDf, confidenceIntervalText, POST_ESTIMATION_LABELS, EMPTY_VARIABLE_LABELS, STAR_MARKERS, type TableOneRow, type StatisticalEvidencePacket, evidenceTestLabel, evidenceEffectValue, variableLabelsForTable } from "./tableViewData";

export function TableViewEvidenceStatus({
  detail,
  tableOne,
  statisticalEvidence,
}: {
  detail: RunDetail;
  tableOne: readonly TableOneRow[];
  statisticalEvidence: StatisticalEvidencePacket | null;
}) {
  const variableLabels = variableLabelsForTable(detail);
  const tableOneAvailable = tableOne.length > 0;
  const statisticalEvidenceAvailable = statisticalEvidence !== null;

  return (
    <section
      data-testid="table-view-evidence-status"
      aria-label="Additional table evidence status"
      style={{ fontSize: 12, color: "var(--label-secondary)" }}
    >
      <h3 style={{ fontSize: 14, margin: "0 0 6px", color: "var(--label)" }}>
        Additional evidence
      </h3>
      <ul style={{ margin: 0, paddingLeft: 18 }}>
        <li>
          Table 1: {tableOneAvailable
            ? "consumed from RunDetail"
            : "not provided by RunDetail; see Report/export"}
        </li>
        <li>
          Statistical evidence: {statisticalEvidenceAvailable
            ? "consumed from RunDetail or the persisted evidence artifact"
            : "not provided by RunDetail or the evidence artifact; see Report/export"}
        </li>
        <li>
          Variable labels: {Object.keys(variableLabels).length > 0
            ? `consumed (${Object.keys(variableLabels).length} label${Object.keys(variableLabels).length === 1 ? "" : "s"})`
            : "not provided; using variable names (raw column names)"}
        </li>
      </ul>
    </section>
  );
}

export function SignificanceControls({
  levels,
  onChange,
}: {
  levels: SignificanceLevels;
  onChange: (marker: string, value: number) => void;
}) {
  const labels: Record<string, string> = {
    "***": "Three-star cutoff",
    "**": "Two-star cutoff",
    "*": "One-star cutoff",
  };
  return (
    <div
      data-testid="table-view-regression-stars"
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 8,
        alignItems: "center",
        fontSize: 11,
        color: "var(--label-secondary)",
        marginBottom: 8,
      }}
    >
      <span>Significance stars:</span>
      {STAR_MARKERS.map((marker) => (
        <label key={marker} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
          {marker} p &lt;
          <input
            aria-label={labels[marker]}
            type="number"
            min="0"
            max="1"
            step="0.01"
            value={levels[marker] ?? ""}
            onChange={(event) => {
              const next = Number(event.target.value);
              if (Number.isFinite(next) && next >= 0 && next <= 1) onChange(marker, next);
            }}
            style={{ width: 54, fontSize: 11 }}
          />
        </label>
      ))}
    </div>
  );
}

export function TableOnePreview({ rows }: { rows: readonly TableOneRow[] }) {
  if (rows.length === 0) return null;
  return (
    <section data-testid="table-view-table-1">
      <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Table 1</h3>
      <div
        className="wb-result-table-scroll"
        data-testid="table-view-table-1-scroll"
        tabIndex={0}
        aria-label="Table 1 scroll region"
      >
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--label-secondary)" }}>
              <th style={{ padding: "2px 8px" }}>Variable</th>
              <th style={{ padding: "2px 8px" }}>N</th>
              <th style={{ padding: "2px 8px" }}>Missing</th>
              <th style={{ padding: "2px 8px" }}>Mean</th>
              <th style={{ padding: "2px 8px" }}>SD</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.column} style={{ borderTop: "1px solid var(--separator)" }}>
                <td style={{ padding: "2px 8px" }}>{row.label} ({row.column})</td>
                <td style={{ padding: "2px 8px" }}>{row.count ?? "—"}</td>
                <td style={{ padding: "2px 8px" }}>{row.missing ?? "—"}</td>
                <td style={{ padding: "2px 8px" }}>{row.mean == null ? "—" : fmt(row.mean)}</td>
                <td style={{ padding: "2px 8px" }}>{row.std == null ? "—" : fmt(row.std)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function StatisticalEvidenceTable({ packet }: { packet: StatisticalEvidencePacket }) {
  if (packet.results.length === 0) return null;
  return (
    <section data-testid="table-view-statistical-evidence">
      <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>
        Statistical evidence
      </h3>
      <div
        className="wb-result-table-scroll"
        data-testid="table-view-statistical-evidence-scroll"
        tabIndex={0}
        aria-label="Statistical evidence scroll region"
      >
        <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ textAlign: "left", color: "var(--label-secondary)" }}>
              <th style={{ padding: "2px 8px" }}>Test</th>
              <th style={{ padding: "2px 8px" }}>N</th>
              <th style={{ padding: "2px 8px" }}>Statistic</th>
              <th style={{ padding: "2px 8px" }}>p-value</th>
              <th style={{ padding: "2px 8px" }}>Effect</th>
              <th style={{ padding: "2px 8px" }}>Source</th>
            </tr>
          </thead>
          <tbody>
            {packet.results.map((result, index) => (
              <tr key={result.test_id ?? `${result.test_type ?? "test"}-${index}`} style={{ borderTop: "1px solid var(--separator)" }}>
                <td style={{ padding: "2px 8px" }}>{evidenceTestLabel(result.test_type)}</td>
                <td style={{ padding: "2px 8px" }}>{result.nobs ?? "—"}</td>
                <td style={{ padding: "2px 8px" }}>{result.statistic == null ? "—" : fmt(result.statistic)}</td>
                <td style={{ padding: "2px 8px" }}>{result.p_value == null ? "—" : formatPValue(result.p_value)}</td>
                <td style={{ padding: "2px 8px" }}>{evidenceEffectValue(result.effect_size)}</td>
                <td style={{ padding: "2px 8px", whiteSpace: "nowrap" }}>{result.source_id ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function PostEstimationResultTable({ entry }: { entry: PostEstimationResult }) {
  return (
    <div className="wb-table-post-estimation" data-testid={`post-estimation-${entry.artifact_id}`}>
      <div className="wb-table-post-estimation__title">
        {POST_ESTIMATION_LABELS[entry.operation_id] ?? entry.operation_id}
      </div>
      <div className="wb-table-post-estimation__source">
        step {entry.workflow_step_id} · model run {entry.model_run_id}
      </div>
      <PostEstimationFields entry={entry} />
    </div>
  );
}

export function CoefficientTable({
  model,
  termLabels = EMPTY_VARIABLE_LABELS,
}: {
  model: ModelResult;
  termLabels?: Readonly<Record<string, string>>;
}) {
  const repeatedMeasures = buildRepeatedMeasuresViewModel(model);
  const rows = repeatedMeasures.kind === "complete"
    ? [[repeatedMeasures.primaryCoefficient.result_id, repeatedMeasures.primaryCoefficient] as const]
    : Object.entries(model.coefficients ?? {});
  // Pooled multiple-imputation results carry a df and FMI per coefficient.
  const pooled = rows.some(([, c]) => typeof (c as { fmi?: unknown }).fmi === "number");
  const diagnostics = repeatedMeasures.kind === "complete"
    ? repeatedMeasures.diagnostics.map((diagnostic) => diagnostic.code)
    : [];
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label)", marginBottom: 4 }}>
        {model.model_id}
        {model.model_type ? ` · ${model.model_type}` : ""}
        {groupLabel(model) ? ` · ${groupLabel(model)}` : ""}
      </div>
      {notEstimableGroups(model) ? (
        <div data-testid="table-view-not-estimable-groups" role="note" style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 6 }}>
          {notEstimableGroups(model)}
        </div>
      ) : null}
      <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 6 }}>
        {model.nobs !== undefined ? `n=${model.nobs}${nobsBasis(model)}` : null}
        {model.r_squared != null ? ` · R²=${fmt(model.r_squared)}` : null}
        {model.r_squared_adj != null ? ` · adj. R²=${fmt(model.r_squared_adj)}` : null}
      </div>
      {describeInference(model) ? (
        <div data-testid="table-view-inference" style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 6 }}>
          {describeInference(model)}
        </div>
      ) : null}
      {describeSuppressedInference(model) ? (
        <div data-testid="table-view-inference-suppressed" role="note" style={{ fontSize: 12, color: "var(--status-caution-fg)", marginBottom: 6 }}>
          {describeSuppressedInference(model)}
        </div>
      ) : null}
      <div
        className="wb-result-table-scroll"
        data-testid="table-view-coefficient-scroll"
        tabIndex={0}
        aria-label="Coefficient table scroll region"
      >
      <table className="wb-result-table" style={{ borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--label-secondary)" }}>
            <th style={{ padding: "2px 8px" }}>term</th>
            <th style={{ padding: "2px 8px" }}>estimate</th>
            <th style={{ padding: "2px 8px" }}>std. error</th>
            <th style={{ padding: "2px 8px" }}>p-value</th>
            <th style={{ padding: "2px 8px" }}>95% CI</th>
            {pooled ? <th style={{ padding: "2px 8px" }} title="Barnard-Rubin degrees of freedom">df</th> : null}
            {pooled ? <th style={{ padding: "2px 8px" }} title="Fraction of missing information">FMI</th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map(([term, c]) => (
            <tr key={term} style={{ borderTop: "1px solid var(--separator)" }}>
              {termLabels[term] && termLabels[term] !== term ? (
                <td style={{ padding: "2px 8px" }} title={term}>{termLabels[term]}</td>
              ) : (
                <td style={{ padding: "2px 8px", fontFamily: "var(--font-mono, monospace)" }}>{term}</td>
              )}
              <td style={{ padding: "2px 8px" }}>{fmt(c.estimate)}</td>
              <td style={{ padding: "2px 8px" }}>{fmt(c.std_error)}</td>
              <td style={{ padding: "2px 8px" }}>
                {("p_value_display" in c ? c.p_value_display : undefined) ?? formatPValue(c.p_value)}
              </td>
              <td style={{ padding: "2px 8px", whiteSpace: "nowrap" }}>{confidenceIntervalText(c)}</td>
              {pooled ? <td style={{ padding: "2px 8px" }}>{pooledDf(c)}</td> : null}
              {pooled ? <td style={{ padding: "2px 8px" }}>{fmt((c as { fmi?: number | null }).fmi)}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {diagnostics.length > 0 && (
        <div
          data-testid="table-view-lmm-diagnostics"
          style={{ marginTop: 8, fontSize: 11, color: "var(--orange)" }}
        >
          Diagnostic: {diagnostics.join(", ")}
        </div>
      )}
    </div>
  );
}

export function RegressionTablePreview({
  models,
  significanceLevels,
  variableLabels,
}: {
  models: readonly ModelResult[];
  significanceLevels: SignificanceLevels;
  variableLabels: Readonly<Record<string, string>>;
}) {
  const packet = buildRegressionTablePacket(
    models,
    significanceLevels,
    variableLabels,
  );
  if (packet.rows.length === 0) return null;

  return (
    <section data-testid="table-view-regression-table">
      <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>
        Regression table
      </h3>
      <div
        className="wb-result-table-scroll"
        data-testid="table-view-regression-table-scroll"
        tabIndex={0}
        aria-label="Regression table scroll region"
      >
        <RegressionTable packet={packet} />
      </div>
    </section>
  );
}
