import type { ArmaGarchTransformPreflight, FilePreview } from "../api";

export type TimeSemantics =
  | "regular_calendar"
  | "business_or_trading_observations"
  | "observation_order";
export type TransformId = "level" | "log_level" | "diff_1" | "log_return_pct";
export type SelectionMode = "auto" | "manual";
export type VarianceModel = "constant_variance" | "arch" | "garch";
export type MissingValuePolicy = "block" | "drop_missing_confirmed";

export type ArmaGarchControlValue = {
  timeColumn: string;
  valueColumn: string;
  timeIndexSemantics: TimeSemantics;
  transform: TransformId;
  transformConfirmed: boolean;
  missingValuePolicy: MissingValuePolicy;
  selectionMode: SelectionMode;
  armaP: number;
  armaQ: number;
  constantMode: "auto" | "include" | "exclude";
  varianceModel: VarianceModel;
  archP: number;
  garchP: number;
  garchQ: number;
  estimationStrategy: "auto" | "sequential" | "joint";
  innovationDistribution: "normal" | "student_t";
  validationN: number;
  refitEvery: number;
  randomSeed: number;
};

type Props = {
  columns: string[];
  preview: FilePreview | null;
  value: ArmaGarchControlValue;
  onChange: (value: ArmaGarchControlValue) => void;
  transformPreflight?: ArmaGarchTransformPreflight | null;
  transformPreflightError?: string | null;
};

const TRANSFORM_LABELS: Record<TransformId, string> = {
  level: "Original level",
  log_level: "Log level",
  diff_1: "First difference",
  log_return_pct: "Log difference (%)",
};

export function createDefaultArmaGarchValue(): ArmaGarchControlValue {
  return {
    timeColumn: "",
    valueColumn: "",
    timeIndexSemantics: "business_or_trading_observations",
    transform: "level",
    transformConfirmed: false,
    missingValuePolicy: "block",
    selectionMode: "auto",
    armaP: 1,
    armaQ: 0,
    constantMode: "auto",
    varianceModel: "garch",
    archP: 1,
    garchP: 1,
    garchQ: 1,
    estimationStrategy: "auto",
    innovationDistribution: "normal",
    validationN: 20,
    refitEvery: 1,
    randomSeed: 20260720,
  };
}

export function buildArmaGarchModelOptions(
  value: ArmaGarchControlValue,
  datasetRef: string,
): Record<string, unknown> {
  const variance = value.selectionMode === "auto"
    ? {
        model: "auto",
        arch_p: null,
        garch_p: null,
        garch_q: null,
        auto_arch_max_p: 10,
        include_garch_1_1: true,
      }
    : value.varianceModel === "constant_variance"
      ? { model: "constant_variance" }
      : value.varianceModel === "arch"
        ? { model: "arch", arch_p: value.archP }
        : { model: "garch", garch_p: value.garchP, garch_q: value.garchQ };
  const arma = value.selectionMode === "auto"
    ? {
        p: null,
        q: null,
        constant_mode: value.constantMode,
        auto_max_p: 3,
        auto_max_q: 3,
        auto_max_total_order: 4,
      }
    : {
        p: value.armaP,
        q: value.armaQ,
        constant_mode: value.constantMode,
      };
  return {
    dataset_ref: datasetRef,
    time_column: value.timeColumn,
    value_column: value.valueColumn,
    time_index_semantics: value.timeIndexSemantics,
    transform: value.transform,
    transform_confirmed: value.transformConfirmed,
    missing_value_policy: value.missingValuePolicy,
    analysis_goal: "balanced",
    selection_mode: value.selectionMode,
    arma,
    variance,
    estimation_strategy: value.estimationStrategy,
    innovation_distribution: value.innovationDistribution,
    validation: {
      validation_n: value.validationN,
      refit_every: value.refitEvery,
    },
    random_seed: value.randomSeed,
  };
}

export function armaGarchValueFromModelOptions(
  options: Record<string, unknown>,
  base: ArmaGarchControlValue,
): ArmaGarchControlValue {
  const arma = (options.arma ?? {}) as Record<string, unknown>;
  const variance = (options.variance ?? {}) as Record<string, unknown>;
  const validation = (options.validation ?? {}) as Record<string, unknown>;
  const pick = <T,>(candidate: unknown, fallback: T): T =>
    candidate == null ? fallback : (candidate as T);
  const varianceModel = pick<VarianceModel | "auto">(variance.model, base.varianceModel);
  return {
    timeColumn: pick(options.time_column, base.timeColumn),
    valueColumn: pick(options.value_column, base.valueColumn),
    timeIndexSemantics: pick(options.time_index_semantics, base.timeIndexSemantics),
    transform: pick(options.transform, base.transform),
    transformConfirmed: pick(options.transform_confirmed, base.transformConfirmed),
    missingValuePolicy: pick(options.missing_value_policy, base.missingValuePolicy),
    selectionMode: pick(options.selection_mode, base.selectionMode),
    armaP: pick(arma.p, base.armaP),
    armaQ: pick(arma.q, base.armaQ),
    constantMode: pick(arma.constant_mode, base.constantMode),
    varianceModel: varianceModel === "auto" ? base.varianceModel : varianceModel,
    archP: pick(variance.arch_p, base.archP),
    garchP: pick(variance.garch_p, base.garchP),
    garchQ: pick(variance.garch_q, base.garchQ),
    estimationStrategy: pick(options.estimation_strategy, base.estimationStrategy),
    innovationDistribution: pick(options.innovation_distribution, base.innovationDistribution),
    validationN: pick(validation.validation_n, base.validationN),
    refitEvery: pick(validation.refit_every, base.refitEvery),
    randomSeed: pick(options.random_seed, base.randomSeed),
  };
}

export function armaGarchValidationErrors(
  value: ArmaGarchControlValue,
): string[] {
  const errors: string[] = [];
  const boundedInteger = (
    candidate: number,
    minimum: number,
    maximum: number | null,
    label: string,
  ) => {
    if (
      !Number.isInteger(candidate)
      || candidate < minimum
      || (maximum !== null && candidate > maximum)
    ) {
      errors.push(`${label} must be an integer from ${minimum}${maximum === null ? " upward" : ` to ${maximum}`}`);
    }
  };
  if (!value.timeColumn) errors.push("Choose a time column");
  if (!value.valueColumn) errors.push("Choose a numeric value column");
  if (value.timeColumn && value.timeColumn === value.valueColumn) {
    errors.push("Time and value columns must be different");
  }
  if (!value.transformConfirmed) errors.push("Confirm the selected transform");
  if (value.estimationStrategy === "joint" && value.selectionMode === "manual" && value.armaQ > 0) {
    errors.push("Joint estimation supports AR(q=0) mean models only in v1.8");
  }
  if (value.selectionMode === "manual") {
    boundedInteger(value.armaP, 0, 10, "AR order");
    boundedInteger(value.armaQ, 0, 10, "MA order");
    if (value.varianceModel === "arch") {
      boundedInteger(value.archP, 1, 10, "ARCH order");
    }
    if (value.varianceModel === "garch") {
      boundedInteger(value.garchP, 1, 5, "GARCH p");
      boundedInteger(value.garchQ, 1, 5, "GARCH q");
    }
  }
  boundedInteger(value.validationN, 1, 250, "Validation observations");
  boundedInteger(value.refitEvery, 1, 250, "Refit frequency");
  boundedInteger(value.randomSeed, 0, null, "Random seed");
  return errors;
}

function numericInput(value: number, minimum: number, maximum: number, onChange: (value: number) => void, label: string) {
  return (
    <input
      aria-label={label}
      type="number"
      min={minimum}
      max={maximum}
      value={value}
      onChange={(event) => onChange(Number(event.target.value))}
    />
  );
}

export function ArmaGarchControls({
  columns,
  preview,
  value,
  onChange,
  transformPreflight = null,
  transformPreflightError = null,
}: Props) {
  const update = (patch: Partial<ArmaGarchControlValue>) => onChange({ ...value, ...patch });
  const advised = transformPreflight?.recommendation ?? null;
  const numericColumns = preview
    ? preview.columns
        .filter((column) => column.dtype === "numeric")
        .map((column) => column.name)
    : columns;
  const valueMetadata = preview?.columns.find((column) => column.name === value.valueColumn);
  const errors = armaGarchValidationErrors(value);

  return (
    <section className="ios-group" aria-label="ARMA-GARCH controls">
      <p className="ios-hint"><strong>Source table will not be modified.</strong> The model uses an internal time/value analysis view.</p>

      <fieldset>
        <legend>1. Select time and value</legend>
        <label>
          Time column
          <select aria-label="time column" value={value.timeColumn} onChange={(event) => update({ timeColumn: event.target.value })}>
            <option value="">Choose…</option>
            {columns.map((column) => <option key={column} value={column}>{column}</option>)}
          </select>
        </label>
        <label>
          Numeric value column
          <select aria-label="value column" value={value.valueColumn} onChange={(event) => update({ valueColumn: event.target.value, transformConfirmed: false })}>
            <option value="">Choose…</option>
            {numericColumns.map((column) => <option key={column} value={column}>{column}</option>)}
          </select>
        </label>
      </fieldset>

      <fieldset>
        <legend>2. Review time index and data quality</legend>
        <label>
          Time-index semantics
          <select aria-label="time index semantics" value={value.timeIndexSemantics} onChange={(event) => update({ timeIndexSemantics: event.target.value as TimeSemantics })}>
            <option value="business_or_trading_observations">Business / trading observations</option>
            <option value="regular_calendar">Regular calendar</option>
            <option value="observation_order">Observation order</option>
          </select>
        </label>
        <p className="ios-hint">
          Preview: {preview?.rowCount ?? "—"} rows; selected value missing rate {valueMetadata ? `${(valueMetadata.missingRate * 100).toFixed(1)}%` : "—"}. The backend will block duplicates, gaps that conflict with the chosen semantics, non-finite values, and constant series.
        </p>
        <div role="group" aria-label="missing value policy">
          <label className="inline-choice">
            <input
              aria-label="block missing values"
              type="radio"
              name="arma-garch-missing-policy"
              checked={value.missingValuePolicy === "block"}
              onChange={() => update({ missingValuePolicy: "block", transformConfirmed: false })}
            />
            Block when the selected value has missing observations.
          </label>
          <label className="inline-choice">
            <input
              aria-label="confirm drop missing values"
              type="radio"
              name="arma-garch-missing-policy"
              checked={value.missingValuePolicy === "drop_missing_confirmed"}
              onChange={() => update({ missingValuePolicy: "drop_missing_confirmed", transformConfirmed: false })}
            />
            I explicitly confirm excluding rows where the selected value is missing; do not fill, interpolate, or aggregate values.
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>3. Review and confirm transform</legend>
        {advised ? (
          <p className="ios-hint">
            <strong>System suggestion: {TRANSFORM_LABELS[advised.transform_id]}.</strong>{" "}
            {advised.reason} Full-data profile used {transformPreflight?.analysis_row_count.toLocaleString()} of {transformPreflight?.source_row_count.toLocaleString()} source rows.
          </p>
        ) : (
          <p className="ios-hint">
            <strong>Full-data suggestion pending.</strong>{" "}
            {transformPreflightError ?? "Choose valid time/value columns and a missing-value policy to run the backend profile."}
          </p>
        )}
        <label>
          Transform
          <select aria-label="transform" value={value.transform} onChange={(event) => update({ transform: event.target.value as TransformId, transformConfirmed: false })}>
            {Object.entries(TRANSFORM_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
        <label className="inline-choice">
          <input aria-label="confirm transform" type="checkbox" checked={value.transformConfirmed} onChange={(event) => update({ transformConfirmed: event.target.checked })} />
          I confirm this transform after reviewing the suggestion; the system must not change it automatically.
        </label>
      </fieldset>

      <fieldset>
        <legend>4. Configure bounded search and validation</legend>
        <label>
          Selection mode
          <select aria-label="selection mode" value={value.selectionMode} onChange={(event) => update({ selectionMode: event.target.value as SelectionMode })}>
            <option value="auto">Automatic bounded search</option>
            <option value="manual">Manual orders</option>
          </select>
        </label>
        <label>
          Estimation strategy
          <select aria-label="estimation strategy" value={value.estimationStrategy} onChange={(event) => update({ estimationStrategy: event.target.value as ArmaGarchControlValue["estimationStrategy"] })}>
            <option value="auto">Auto (joint for AR; sequential for ARMA)</option>
            <option value="sequential">Sequential ARMA → ARCH/GARCH</option>
            <option value="joint">Joint AR-GARCH (MA order must be 0)</option>
          </select>
        </label>
        <label>
          Innovation distribution
          <select aria-label="innovation distribution" value={value.innovationDistribution} onChange={(event) => update({ innovationDistribution: event.target.value as ArmaGarchControlValue["innovationDistribution"] })}>
            <option value="normal">Normal</option>
            <option value="student_t">Student-t</option>
          </select>
        </label>
        <label>Validation observations {numericInput(value.validationN, 1, 250, (next) => update({ validationN: next }), "validation observations")}</label>
        <label>Refit every N origins {numericInput(value.refitEvery, 1, 250, (next) => update({ refitEvery: next }), "refit every")}</label>
        <p className="ios-hint">
          {value.selectionMode === "auto"
            ? "Bounded search: up to 26 mean specifications, then up to 12 variance specifications for each shortlisted mean."
            : "Manual search: one confirmed mean specification and one confirmed variance specification."}
          {" "}Automatic mode is capped at AR/MA ≤ 3, p+q ≤ 4, ARCH(1…10), and GARCH(1,1).
        </p>
        <details>
          <summary>Advanced ARMA / ARCH / GARCH orders</summary>
          <label>Constant <select aria-label="constant mode" value={value.constantMode} onChange={(event) => update({ constantMode: event.target.value as ArmaGarchControlValue["constantMode"] })}><option value="auto">Auto</option><option value="include">Include</option><option value="exclude">Exclude</option></select></label>
          {value.selectionMode === "manual" && (
            <div className="control-grid">
              <label>AR order {numericInput(value.armaP, 0, 10, (next) => update({ armaP: next }), "AR order")}</label>
              <label>MA order {numericInput(value.armaQ, 0, 10, (next) => update({ armaQ: next }), "MA order")}</label>
              <label>Variance model <select aria-label="variance model" value={value.varianceModel} onChange={(event) => update({ varianceModel: event.target.value as VarianceModel })}><option value="constant_variance">Constant variance</option><option value="arch">ARCH</option><option value="garch">GARCH</option></select></label>
              {value.varianceModel === "arch" && <label>ARCH p {numericInput(value.archP, 1, 10, (next) => update({ archP: next }), "ARCH order")}</label>}
              {value.varianceModel === "garch" && <><label>GARCH p {numericInput(value.garchP, 1, 5, (next) => update({ garchP: next }), "GARCH p")}</label><label>GARCH q {numericInput(value.garchQ, 1, 5, (next) => update({ garchQ: next }), "GARCH q")}</label></>}
            </div>
          )}
        </details>
      </fieldset>

      <fieldset>
        <legend>5. Review execution graph</legend>
        <p className="ios-hint">Raw input → internal analysis view → frozen split → ARMA selection → volatility selection → one-step rolling validation → full-sample production child.</p>
        <p className="ios-hint">Current: {value.timeColumn || "time?"} + {value.valueColumn || "value?"}; {TRANSFORM_LABELS[value.transform]}; {value.selectionMode}; {value.estimationStrategy}; {value.innovationDistribution}.</p>
        {errors.length > 0 && <ul className="field-error" aria-label="ARMA-GARCH blocking issues">{errors.map((error) => <li key={error}>{error}</li>)}</ul>}
      </fieldset>
    </section>
  );
}
