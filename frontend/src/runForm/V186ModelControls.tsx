import { useEffect, useState } from "react";

export const V186_MODEL_TYPES = [
  "ordinal_logit",
  "multinomial_logit",
  "survival_cox",
  "quantile_regression",
] as const;

export type V186ModelType = (typeof V186_MODEL_TYPES)[number];
export type V186ModelOptions = Record<string, unknown>;
export type V186ModelOptionsByType = Partial<Record<V186ModelType, V186ModelOptions>>;

export function isV186ModelType(value: string): value is V186ModelType {
  return (V186_MODEL_TYPES as readonly string[]).includes(value);
}

export function defaultV186ModelOptions(modelType: V186ModelType): V186ModelOptions {
  switch (modelType) {
    case "ordinal_logit":
      return { optimizer: "bfgs", maxiter: 500 };
    case "multinomial_logit":
      return { maxiter: 500 };
    case "survival_cox":
      return { event_column: "", ties: "breslow" };
    case "quantile_regression":
      return { quantiles: [0.25, 0.5, 0.75], bootstrap_reps: 0, random_state: 0 };
  }
}

export function normalizeV186ModelOptions(
  modelType: V186ModelType,
  value: unknown,
): V186ModelOptions {
  const saved = value && typeof value === "object" && !Array.isArray(value)
    ? value as V186ModelOptions
    : {};
  return { ...defaultV186ModelOptions(modelType), ...saved };
}

function textOption(options: V186ModelOptions, key: string): string {
  return typeof options[key] === "string" ? options[key] as string : "";
}

function numberOption(options: V186ModelOptions, key: string, fallback: number): number {
  return typeof options[key] === "number" && Number.isFinite(options[key])
    ? options[key] as number
    : fallback;
}

function setOptionalColumn(
  options: V186ModelOptions,
  key: string,
  value: string,
  onChange: (next: V186ModelOptions) => void,
) {
  const next = { ...options };
  if (value) next[key] = value;
  else delete next[key];
  onChange(next);
}

function ColumnSelect(props: {
  label: string;
  value: string;
  columns: string[];
  required?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="ios-field">
      <span>{props.label}</span>
      <select
        aria-label={props.label}
        value={props.value}
        required={props.required}
        onChange={(event) => props.onChange(event.target.value)}
      >
        <option value="">{props.required ? "(select a required column)" : "(not used)"}</option>
        {props.columns.map((column) => (
          <option key={column} value={column}>{column}</option>
        ))}
      </select>
    </label>
  );
}

function JsonOptionsEditor(props: {
  label: string;
  options: V186ModelOptions;
  onChange: (options: V186ModelOptions) => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(props.options));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setText(JSON.stringify(props.options));
    setError(null);
  }, [props.options]);

  function handleChange(value: string) {
    setText(value);
    try {
      const parsed: unknown = JSON.parse(value);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("options must be a JSON object");
      }
      setError(null);
      props.onChange(parsed as V186ModelOptions);
    } catch {
      setError("model_options must be a JSON object");
    }
  }

  return (
    <label className="ios-field">
      <span>{props.label}</span>
      <textarea
        aria-label={props.label}
        value={text}
        rows={3}
        onChange={(event) => handleChange(event.target.value)}
      />
      {error && <span className="ios-warning">{error}</span>}
    </label>
  );
}

export function V186ModelControls(props: {
  modelType: V186ModelType;
  columns: string[];
  options: V186ModelOptions;
  onChange: (options: V186ModelOptions) => void;
}) {
  const { modelType, columns, options, onChange } = props;

  if (modelType === "ordinal_logit") {
    return (
      <div className="ios-group" aria-label="Ordinal logit settings">
        <p className="ios-hint">Ordered categorical outcome. The model_options JSON sent to the backend is editable directly.</p>
        <JsonOptionsEditor
          label="ordinal model options"
          options={options}
          onChange={onChange}
        />
      </div>
    );
  }

  if (modelType === "multinomial_logit") {
    return (
      <div className="ios-group" aria-label="Multinomial logit settings">
        <p className="ios-hint">Unordered categorical outcome. The model_options JSON sent to the backend is editable directly.</p>
        <JsonOptionsEditor
          label="multinomial model options"
          options={options}
          onChange={onChange}
        />
      </div>
    );
  }

  if (modelType === "survival_cox") {
    return (
      <div className="ios-group" aria-label="Survival Cox settings">
        <p className="ios-hint">duration uses y; event must be a 0/1 event column; group is optional.</p>
        <ColumnSelect
          label="survival event column"
          value={textOption(options, "event_column")}
          columns={columns}
          required
          onChange={(value) => onChange({ ...options, event_column: value })}
        />
        <ColumnSelect
          label="survival group column"
          value={textOption(options, "group_column")}
          columns={columns}
          onChange={(value) => setOptionalColumn(options, "group_column", value, onChange)}
        />
        <ColumnSelect
          label="survival entry column"
          value={textOption(options, "entry_column")}
          columns={columns}
          onChange={(value) => setOptionalColumn(options, "entry_column", value, onChange)}
        />
        <label className="ios-field">
          <span>survival ties</span>
          <select
            aria-label="survival ties"
            value={textOption(options, "ties") || "breslow"}
            onChange={(event) => onChange({ ...options, ties: event.target.value })}
          >
            <option value="breslow">Breslow</option>
            <option value="efron">Efron</option>
          </select>
        </label>
      </div>
    );
  }

  const quantiles = Array.isArray(options.quantiles)
    ? (options.quantiles as unknown[]).filter((value): value is number => typeof value === "number").join(", ")
    : "0.25, 0.5, 0.75";
  return (
    <div className="ios-group" aria-label="Quantile regression settings">
      <p className="ios-hint">Quantiles are comma-separated; every value must lie strictly between 0 and 1.</p>
      <label className="ios-field">
        <span>quantiles</span>
        <input
          aria-label="quantiles"
          value={quantiles}
          onChange={(event) => {
            const values = event.target.value
              .split(",")
              .map((part) => Number(part.trim()))
              .filter((value) => Number.isFinite(value));
            onChange({ ...options, quantiles: values });
          }}
        />
      </label>
      <label className="ios-field">
        <span>bootstrap reps</span>
        <input
          aria-label="bootstrap reps"
          type="number"
          min={0}
          max={1000}
          step={1}
          value={numberOption(options, "bootstrap_reps", 0)}
          onChange={(event) => onChange({ ...options, bootstrap_reps: Number(event.target.value) })}
        />
      </label>
      <label className="ios-field">
        <span>quantile random state</span>
        <input
          aria-label="quantile random state"
          type="number"
          min={0}
          step={1}
          value={numberOption(options, "random_state", 0)}
          onChange={(event) => onChange({ ...options, random_state: Number(event.target.value) })}
        />
      </label>
    </div>
  );
}
