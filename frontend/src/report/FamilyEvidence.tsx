import type { ModelResult } from "../api";

type EvidenceRecord = Record<string, unknown>;

/**
 * The HTTP model-result envelope is intentionally additive.  `ModelResult`
 * keeps the old generic coefficient contract, while this local view type
 * reads the family fields that are already persisted in the JSON packet.
 */
export type FamilyModelResult = ModelResult & {
  [key: string]: unknown;
};

export type FamilyEvidenceArtifacts = Readonly<Record<string, unknown>>;

const tableStyle = { fontSize: 12, borderCollapse: "collapse" as const };
const cellStyle = { padding: "2px 10px 2px 0", textAlign: "left" as const };

function asRecord(value: unknown): EvidenceRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as EvidenceRecord
    : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asStringArray(value: unknown): string[] {
  return asArray(value).filter((item): item is string => typeof item === "string");
}

function asRecordEntries(value: unknown): Array<[string, EvidenceRecord]> {
  const record = asRecord(value);
  if (!record) return [];
  return Object.entries(record).flatMap(([key, item]) => {
    const child = asRecord(item);
    return child ? [[key, child] as [string, EvidenceRecord]] : [];
  });
}

function asValueEntries(value: unknown): Array<[string, unknown]> {
  const record = asRecord(value);
  return record ? Object.entries(record) : [];
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—";
  if (typeof value === "string" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "—";
  }
}

function displayInterval(value: unknown): string {
  const record = asRecord(value);
  if (record) {
    return `[${displayValue(record.ci_lower)}, ${displayValue(record.ci_upper)}]`;
  }
  if (Array.isArray(value) && value.length >= 2) {
    return `[${displayValue(value[0])}, ${displayValue(value[1])}]`;
  }
  return "—";
}

function artifactPayload(value: unknown): EvidenceRecord | null {
  const record = asRecord(value);
  if (!record) return null;
  const payload = asRecord(record.payload);
  return payload ?? record;
}

function EvidenceSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} style={{ marginTop: 10 }}>
      <h4 style={{ fontSize: 12, margin: "0 0 5px" }}>{title}</h4>
      {children}
    </section>
  );
}

function Unavailable({ label }: { label: string }) {
  return (
    <p style={{ fontSize: 12, color: "var(--label-tertiary)", margin: 0 }}>
      {label} unavailable; no value was supplied by the typed result packet.
    </p>
  );
}

function KeyValueList({ values }: { values: Readonly<Record<string, unknown>> }) {
  return (
    <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 12px", margin: 0, fontSize: 12 }}>
      {Object.entries(values).map(([key, value]) => (
        <div key={key} style={{ display: "contents" }}>
          <dt>{key}</dt>
          <dd style={{ margin: 0 }}>{displayValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function OrdinalEvidence({
  model,
  artifacts,
}: {
  model: FamilyModelResult;
  artifacts: FamilyEvidenceArtifacts;
}) {
  const oddsRatios = asRecordEntries(model.odds_ratios);
  const marginalEffects = asArray(model.marginal_effects);
  const probabilities = asArray(model.predicted_probabilities);
  const diagnostic = artifactPayload(artifacts.diagnostics_ordinal_logit_1);
  const parallelLines = asRecord(diagnostic?.parallel_lines);
  const outcomeLevels = asStringArray(model.outcome_levels);

  return (
    <>
      <EvidenceSection title="Odds ratios">
        {oddsRatios.length === 0 ? <Unavailable label="Odds ratios" /> : (
          <table style={tableStyle}>
            <thead><tr><th style={cellStyle}>Variable</th><th style={cellStyle}>OR</th><th style={cellStyle}>95% CI</th></tr></thead>
            <tbody>{oddsRatios.map(([term, values]) => (
              <tr key={term}>
                <td style={cellStyle}>{term}</td>
                <td style={cellStyle}>{displayValue(values.odds_ratio)}</td>
                <td style={cellStyle}>{displayInterval(values)}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </EvidenceSection>
      <EvidenceSection title="Marginal effects">
        {marginalEffects.length === 0 ? <Unavailable label="Marginal effects" /> : (
          <table style={tableStyle}>
            <thead><tr><th style={cellStyle}>Variable</th><th style={cellStyle}>Outcome</th><th style={cellStyle}>Effect</th></tr></thead>
            <tbody>{marginalEffects.flatMap((item, index) => {
              const row = asRecord(item);
              const effects = asRecord(row?.average_effect_by_category);
              return effects
                ? Object.entries(effects).map(([category, effect]) => (
                  <tr key={`${index}-${category}`}>
                    <td style={cellStyle}>{displayValue(row?.variable)}</td>
                    <td style={cellStyle}>{category}</td>
                    <td style={cellStyle}>{displayValue(effect)}</td>
                  </tr>
                ))
                : [];
            })}</tbody>
          </table>
        )}
      </EvidenceSection>
      <EvidenceSection title="Predicted probabilities">
        {probabilities.length === 0 ? <Unavailable label="Predicted probabilities" /> : (
          <table style={tableStyle}>
            <thead><tr><th style={cellStyle}>Row</th>{outcomeLevels.map((level) => <th key={level} style={cellStyle}>{level}</th>)}</tr></thead>
            <tbody>{probabilities.map((item, index) => {
              const row = asRecord(item);
              const values = asRecord(row?.probabilities);
              return (
                <tr key={String(row?.row ?? index)}>
                  <td style={cellStyle}>{displayValue(row?.row ?? index)}</td>
                  {outcomeLevels.map((level) => <td key={level} style={cellStyle}>{displayValue(values?.[level])}</td>)}
                </tr>
              );
            })}</tbody>
          </table>
        )}
      </EvidenceSection>
      <EvidenceSection title="Parallel-lines evidence">
        {!parallelLines ? <Unavailable label="Parallel-lines evidence" /> : (
          <>
            <KeyValueList values={{
              status: parallelLines.status,
              method: parallelLines.method,
              comparisons: asArray(parallelLines.comparisons).length,
            }} />
            {asValueEntries(parallelLines.slope_ranges).length > 0 && (
              <table style={tableStyle}>
                <thead><tr><th style={cellStyle}>Variable</th><th style={cellStyle}>Slope range</th></tr></thead>
                <tbody>{asValueEntries(parallelLines.slope_ranges).map(([term, value]) => (
                  <tr key={term}><td style={cellStyle}>{term}</td><td style={cellStyle}>{displayValue(value)}</td></tr>
                ))}</tbody>
              </table>
            )}
          </>
        )}
      </EvidenceSection>
    </>
  );
}

function MultinomialEvidence({ model }: { model: FamilyModelResult }) {
  const rrr = asRecordEntries(model.relative_risk_ratios);
  const probabilities = asValueEntries(model.predicted_probabilities);
  const marginalEffects = asArray(model.marginal_effects);
  const baseCategory = typeof model.base_category === "string" ? model.base_category : null;
  const hasBaseCategory = baseCategory !== null && baseCategory.trim() !== "";
  return (
    <>
      {hasBaseCategory
        ? <p style={{ margin: "4px 0", fontSize: 12 }}>Base category: <strong>{baseCategory}</strong></p>
        : <Unavailable label="Base category" />}
      <EvidenceSection title="Relative risk ratios">
        {rrr.length === 0 ? <Unavailable label="Relative risk ratios" /> : (
          <table style={tableStyle}>
            <thead><tr><th style={cellStyle}>Outcome / term</th><th style={cellStyle}>RRR</th><th style={cellStyle}>95% CI</th></tr></thead>
            <tbody>{rrr.map(([term, values]) => (
              <tr key={term}><td style={cellStyle}>{term}</td><td style={cellStyle}>{displayValue(values.relative_risk_ratio)}</td><td style={cellStyle}>{displayInterval(values)}</td></tr>
            ))}</tbody>
          </table>
        )}
      </EvidenceSection>
      <EvidenceSection title="Predicted probabilities">
        {probabilities.length === 0 ? <Unavailable label="Predicted probabilities" /> : (
          <table style={tableStyle}>
            <thead><tr><th style={cellStyle}>Outcome</th><th style={cellStyle}>Row</th><th style={cellStyle}>Probability</th></tr></thead>
            <tbody>{probabilities.flatMap(([category, values]) => (
              asArray(values).map((value, index) => (
                <tr key={`${category}-${index}`}><td style={cellStyle}>{category}</td><td style={cellStyle}>{index}</td><td style={cellStyle}>{displayValue(value)}</td></tr>
              ))
            ))}</tbody>
          </table>
        )}
      </EvidenceSection>
      <EvidenceSection title="Marginal effects">
        {marginalEffects.length === 0 ? <Unavailable label="Marginal effects" /> : (
          <table style={tableStyle}>
            <thead><tr><th style={cellStyle}>Variable</th><th style={cellStyle}>Term</th><th style={cellStyle}>Effect</th></tr></thead>
            <tbody>{marginalEffects.flatMap((item, index) => {
              const row = asRecord(item);
              return asValueEntries(row)
                .filter(([key]) => key !== "variable")
                .map(([key, value]) => (
                  <tr key={`${index}-${key}`}><td style={cellStyle}>{displayValue(row?.variable)}</td><td style={cellStyle}>{key}</td><td style={cellStyle}>{displayValue(value)}</td></tr>
                ));
            })}</tbody>
          </table>
        )}
      </EvidenceSection>
    </>
  );
}

function SurvivalEvidence({
  model,
  artifacts,
}: {
  model: FamilyModelResult;
  artifacts: FamilyEvidenceArtifacts;
}) {
  const artifactId = typeof model.survival_evidence_artifact === "string"
    ? model.survival_evidence_artifact
    : "survival_evidence";
  const evidence = artifactPayload(artifacts[artifactId]);
  const hazardRatios = asValueEntries(model.hazard_ratios);
  if (!evidence) {
    return (
      <p style={{ fontSize: 12, color: "var(--label-tertiary)", margin: 0 }}>
        Survival evidence unavailable; generic coefficient table remains available.
      </p>
    );
  }
  const censoring = asRecord(evidence.censoring);
  const timeToEvent = asRecord(evidence.time_to_event);
  const kaplanMeier = asArray(evidence.kaplan_meier);
  const logRank = asRecord(evidence.log_rank);
  const riskSet = asArray(evidence.risk_set);
  const schoenfeld = asArray(evidence.schoenfeld);
  return (
    <>
      {hazardRatios.length > 0 && (
        <EvidenceSection title="Cox hazard ratios">
          <table style={tableStyle}><thead><tr><th style={cellStyle}>Variable</th><th style={cellStyle}>Hazard ratio</th></tr></thead>
            <tbody>{hazardRatios.map(([term, value]) => <tr key={term}><td style={cellStyle}>{term}</td><td style={cellStyle}>{displayValue(value)}</td></tr>)}</tbody>
          </table>
        </EvidenceSection>
      )}
      <EvidenceSection title="Censoring and time-to-event">
        <p style={{ margin: "0 0 5px", fontSize: 12 }}>
          Events: {displayValue(censoring?.events)} · Censored: {displayValue(censoring?.censored)}
        </p>
        <KeyValueList values={{
          events: censoring?.events,
          censored: censoring?.censored,
          duration: timeToEvent?.duration_column,
          event: timeToEvent?.event_column,
          entry: timeToEvent?.entry_column,
        }} />
      </EvidenceSection>
      <EvidenceSection title="Kaplan-Meier">
        {kaplanMeier.length === 0 ? <Unavailable label="Kaplan-Meier" /> : (
          <table style={tableStyle}><thead><tr><th style={cellStyle}>Group</th><th style={cellStyle}>Time</th><th style={cellStyle}>Survival</th><th style={cellStyle}>At risk</th></tr></thead>
            <tbody>{kaplanMeier.map((item, index) => { const row = asRecord(item); return <tr key={index}><td style={cellStyle}>{displayValue(row?.group)}</td><td style={cellStyle}>{displayValue(row?.time)}</td><td style={cellStyle}>{displayValue(row?.survival)}</td><td style={cellStyle}>{displayValue(row?.n_at_risk)}</td></tr>; })}</tbody>
          </table>
        )}
      </EvidenceSection>
      <EvidenceSection title="Log-rank">
        {logRank ? <KeyValueList values={{ status: logRank.status, statistic: logRank.statistic, p_value: logRank.p_value, groups: logRank.groups }} /> : <Unavailable label="Log-rank" />}
      </EvidenceSection>
      <EvidenceSection title="Risk set">
        {riskSet.length === 0 ? <Unavailable label="Risk set" /> : (
          <table style={tableStyle}><thead><tr><th style={cellStyle}>Time</th><th style={cellStyle}>At risk</th><th style={cellStyle}>Events</th><th style={cellStyle}>Censored</th></tr></thead>
            <tbody>{riskSet.map((item, index) => { const row = asRecord(item); return <tr key={index}><td style={cellStyle}>{displayValue(row?.time)}</td><td style={cellStyle}>{displayValue(row?.at_risk)}</td><td style={cellStyle}>{displayValue(row?.events)}</td><td style={cellStyle}>{displayValue(row?.censored)}</td></tr>; })}</tbody>
          </table>
        )}
      </EvidenceSection>
      <EvidenceSection title="Schoenfeld">
        {schoenfeld.length === 0 ? <Unavailable label="Schoenfeld" /> : (
          <table style={tableStyle}><thead><tr><th style={cellStyle}>Variable</th><th style={cellStyle}>Status</th><th style={cellStyle}>Time correlation</th></tr></thead>
            <tbody>{schoenfeld.map((item, index) => { const row = asRecord(item); return <tr key={index}><td style={cellStyle}>{displayValue(row?.variable)}</td><td style={cellStyle}>{displayValue(row?.status)}</td><td style={cellStyle}>{displayValue(row?.time_correlation)}</td></tr>; })}</tbody>
          </table>
        )}
      </EvidenceSection>
    </>
  );
}

function QuantileEvidence({ model }: { model: FamilyModelResult }) {
  const fits = asRecord(model.fits);
  const quantiles = asArray(model.quantiles).length > 0
    ? asArray(model.quantiles)
    : Object.keys(fits ?? {});
  const bootstrap = asRecord(model.bootstrap);
  const successful = asRecord(bootstrap?.successful_repetitions);
  const intervals = asRecord(bootstrap?.intervals);
  const comparisons = asArray(model.cross_quantile_comparisons);
  return (
    <>
      <EvidenceSection title="Quantile fits and confidence intervals">
        {quantiles.length === 0 ? <Unavailable label="Quantile fits" /> : quantiles.map((quantile) => {
          const key = String(quantile);
          const fit = asRecord((fits ?? {})[key]);
          const coefficients = asRecordEntries(fit?.coefficients);
          return (
            <div key={key} style={{ marginBottom: 7 }}>
              <strong style={{ fontSize: 12 }}>Quantile {key}{key === String(model.reference_quantile) ? " (reference)" : ""}</strong>
              {coefficients.length === 0 ? <Unavailable label={`Quantile ${key}`} /> : (
                <table style={tableStyle}><thead><tr><th style={cellStyle}>Term</th><th style={cellStyle}>Estimate</th><th style={cellStyle}>95% CI</th></tr></thead>
                  <tbody>{coefficients.map(([term, values]) => <tr key={term}><td style={cellStyle}>{term}</td><td style={cellStyle}>{displayValue(values.estimate)}</td><td style={cellStyle}>{displayInterval(values)}</td></tr>)}</tbody>
                </table>
              )}
            </div>
          );
        })}
      </EvidenceSection>
      <EvidenceSection title="Bootstrap">
        {!bootstrap ? <Unavailable label="Bootstrap" /> : (
          <KeyValueList values={{
            repetitions: bootstrap.repetitions,
            random_state: bootstrap.random_state,
            successful_repetitions: successful,
            intervals,
          }} />
        )}
      </EvidenceSection>
      <EvidenceSection title="Cross-quantile comparisons">
        {comparisons.length === 0 ? <Unavailable label="Cross-quantile comparisons" /> : (
          <table style={tableStyle}><thead><tr><th style={cellStyle}>Term</th><th style={cellStyle}>Lower</th><th style={cellStyle}>Upper</th><th style={cellStyle}>Difference</th><th style={cellStyle}>p-value</th></tr></thead>
            <tbody>{comparisons.map((item, index) => { const row = asRecord(item); return <tr key={index}><td style={cellStyle}>{displayValue(row?.term)}</td><td style={cellStyle}>{displayValue(row?.lower_quantile)}</td><td style={cellStyle}>{displayValue(row?.upper_quantile)}</td><td style={cellStyle}>{displayValue(row?.difference)}</td><td style={cellStyle}>{displayValue(row?.p_value)}</td></tr>; })}</tbody>
          </table>
        )}
      </EvidenceSection>
    </>
  );
}

function familyTitle(modelType: string): string {
  return {
    ordinal_logit: "Ordered logit",
    multinomial_logit: "Multinomial logit",
    survival_cox: "Survival / Cox",
    quantile_regression: "Quantile regression",
  }[modelType] ?? modelType;
}

function FamilyEvidenceCard({
  model,
  artifacts,
}: {
  model: FamilyModelResult;
  artifacts: FamilyEvidenceArtifacts;
}) {
  const modelType = typeof model.model_type === "string" ? model.model_type : "";
  return (
    <section
      aria-label={`${familyTitle(modelType)} evidence`}
      data-testid={`family-evidence-${model.model_id}`}
      style={{ marginBottom: 16 }}
    >
      <h3 style={{ fontSize: 14, margin: "0 0 7px" }}>
        {familyTitle(modelType)} <span style={{ color: "var(--label-tertiary)", fontWeight: 400 }}>({model.model_id})</span>
      </h3>
      {modelType === "ordinal_logit" && <OrdinalEvidence model={model} artifacts={artifacts} />}
      {modelType === "multinomial_logit" && <MultinomialEvidence model={model} />}
      {modelType === "survival_cox" && <SurvivalEvidence model={model} artifacts={artifacts} />}
      {modelType === "quantile_regression" && <QuantileEvidence model={model} />}
    </section>
  );
}

const SUPPORTED_FAMILIES = new Set([
  "ordinal_logit",
  "multinomial_logit",
  "survival_cox",
  "quantile_regression",
]);

export function FamilyEvidence({
  modelResults,
  artifacts = {},
}: {
  modelResults: readonly FamilyModelResult[];
  artifacts?: FamilyEvidenceArtifacts;
}) {
  const familyModels = modelResults.filter((model) => SUPPORTED_FAMILIES.has(String(model.model_type)));
  if (familyModels.length === 0) return null;
  return (
    <section aria-label="Model family evidence" data-testid="model-family-evidence">
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Model family evidence
      </div>
      {familyModels.map((model) => (
        <FamilyEvidenceCard key={model.model_id} model={model} artifacts={artifacts} />
      ))}
    </section>
  );
}
