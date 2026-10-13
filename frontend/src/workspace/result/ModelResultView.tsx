// v1.9.0 — the result, first (design spec §8.3.1, stage "Result" view).
// For a model step the stage leads with what the researcher came for: the
// key estimate with its interval, every coefficient, fit, and whether the
// result is ready to interpret. Everything else (rerun with changes, compare,
// roles, lineage, script export, info) follows below, unchanged.

import { useEffect, useState } from "react";
import { fetchRunDetail, type RunDetail } from "../../api";
import type { GraphViewNode } from "../../lineage/api/graphViewTypes";
import { formatEstimate, formatPValue } from "../../format/numbers";
import {
  checkSummary,
  coefficientRows,
  fitStats,
  inferenceLine,
  keyCoefficient,
  modelIdOf,
  pendingChoices,
  pickModelResult,
  type CoefficientRow,
} from "./resultModel";
import { IntervalPlot } from "./IntervalPlot";
import "./modelResult.css";
import {ResultSelection} from "./ResultSelection";
import {ResultActions} from "./ResultActions";
import {modelTests} from "./PostEstimationResults";
import {useCompletedOperation} from "../../workbench/agent/useCompletedOperation";

type Load = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; detail: RunDetail };

function useRunDetail(projectRoot: string, runId: string, revision: number): Load {
  const completedOperation = useCompletedOperation();
  const [load, setLoad] = useState<Load>({ status: "loading" });
  useEffect(() => {
    let live = true;
    // A refresh must not unmount an open operation or its completed receipt.
    fetchRunDetail(projectRoot, runId)
      .then((detail) => live && setLoad({ status: "ready", detail }))
      .catch((error: unknown) => live && setLoad({ status: "error", message: error instanceof Error ? error.message : String(error) }));
    return () => {
      live = false;
    };
  }, [projectRoot, runId, revision, completedOperation]);
  return load;
}

const pText = (row: CoefficientRow) => row.pDisplay ?? formatPValue(row.p);

export function ModelResultView({ projectRoot, runId, node, onRefresh }: { projectRoot: string; runId: string; node: GraphViewNode; onRefresh?: () => void }) {
  const [revision, setRevision] = useState(0);
  const load = useRunDetail(projectRoot, runId, revision);
  if (load.status === "loading") return <p className="ws-result__note" aria-live="polite">Loading the result…</p>;
  if (load.status === "error") return <p className="ws-result__note" role="alert">The result could not be loaded: {load.message}</p>;

  const detail = load.detail;
  const result = pickModelResult(detail, modelIdOf(node));
  if (!result) return null;
  const rows = coefficientRows(result, detail.term_labels);
  const key = keyCoefficient(rows, result);
  const slopes = rows.filter((row) => !row.intercept);
  const record = result as unknown as Record<string, unknown>;
  const outcome = typeof record.y_column === "string" ? record.y_column : null;
  const level = Number((record.inference_config as Record<string, unknown> | undefined)?.confidence_level ?? 0.95);
  const levelText = `${Math.round(level * 100)}% CI`;
  const checks = checkSummary(detail);
  const choices = pendingChoices(node.decisions);
  const stats = fitStats(result);
  const inference = inferenceLine(result);

  return (
    <><ResultSelection runId={runId} modelId={modelIdOf(node)!}><article className="ws-result" aria-label="Result" id="ws-result">
      <div className="ws-result__chips">
        {checks && (
          <span className="ws-chip" data-status={checks.status}>
            {checks.label}
          </span>
        )}
        {choices.length > 0 && (
          <button
            type="button"
            className="ws-chip ws-chip--button"
            data-status="caution"
            title="Go to Decisions to confirm or change"
            onClick={(event) => event.currentTarget.closest(".detail-drawer")?.querySelector('[data-testid="decision-section"]')?.scrollIntoView({ behavior: "smooth", block: "start" })}
          >
            Needs your choice: {choices.join(" · ")}
          </button>
        )}
      </div>

      {key && (
        <div className="ws-result__lead">
          <div className="ws-result__number">
            <p className="ws-result__caption">
              {key.intercept ? key.label : `Effect of ${key.label}${outcome ? ` on ${outcome}` : ""}`}
            </p>
            <p className="ws-result__key">{formatEstimate(key.estimate)}</p>
            <p className="ws-result__interval">
              SE {formatEstimate(key.se)} · {levelText} {formatEstimate(key.ciLow)} to {formatEstimate(key.ciHigh)} · p {pText(key)}
            </p>
          </div>
          {slopes.length > 0 && <IntervalPlot rows={slopes} highlight={key.term} levelText={levelText} />}
        </div>
      )}

      {inference && <p className="ws-result__provenance">{inference}</p>}

      <section className="ws-result__section" aria-labelledby="ws-coefficients" id="ws-section-coefficients">
        <h2 id="ws-coefficients" className="ws-result__heading">Coefficients</h2>
        <div className="ws-result__table-scroll">
          <table className="ws-result__table">
            <thead>
              <tr>
                <th scope="col">Term</th>
                <th scope="col">Estimate</th>
                <th scope="col" data-col="se">SE</th>
                <th scope="col">{levelText}</th>
                <th scope="col">p</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.term} aria-current={row.term === key?.term ? "true" : undefined}>
                  <th scope="row" title={row.term !== row.label ? row.term : undefined}>{row.label}</th>
                  <td>{formatEstimate(row.estimate)}</td>
                  <td data-col="se">{formatEstimate(row.se)}</td>
                  <td>{formatEstimate(row.ciLow)} to {formatEstimate(row.ciHigh)}</td>
                  <td>{pText(row)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {stats.length > 0 && (
        <section className="ws-result__section" aria-labelledby="ws-fit" id="ws-section-fit">
          <h2 id="ws-fit" className="ws-result__heading">Fit</h2>
          <dl className="ws-result__stats">
            {stats.map((stat) => (
              <div key={stat.label}>
                <dt>{stat.label}</dt>
                <dd>{stat.label === "n" ? stat.value.toLocaleString("en-US") : formatEstimate(stat.value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {checks && (
        <section className="ws-result__section" aria-labelledby="ws-checks" id="ws-section-checks">
          <h2 id="ws-checks" className="ws-result__heading">Checks</h2>
          {checks.reasons.length > 0 ? (
            <ul className="ws-result__reasons">
              {checks.reasons.map((reason) => (
                <li key={reason} data-status={checks.status}>{reason}</li>
              ))}
            </ul>
          ) : (
            <p className="ws-result__muted">No blocking issues, warnings or cautions were found for this model.</p>
          )}
        </section>
      )}
    </article></ResultSelection><ResultActions projectRoot={projectRoot} runId={runId} modelId={modelIdOf(node)!} label={node.title}
      entries={modelTests(detail.post_estimation_results ?? [], runId, modelIdOf(node)!)}
      onRefresh={() => {setRevision(value => value + 1);onRefresh?.();}}/></>
  );
}
