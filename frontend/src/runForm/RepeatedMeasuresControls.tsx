export type RepeatedMeasuresOptions = {
  subject_id: string;
  time: string;
  group: string;
  fit_method: "reml" | "ml";
  random_slope: boolean;
};

type RepeatedMeasuresControlsProps = {
  columns: readonly string[];
  value: RepeatedMeasuresOptions;
  onChange: (value: RepeatedMeasuresOptions) => void;
};

function exactOptions(value: RepeatedMeasuresOptions): RepeatedMeasuresOptions {
  return {
    subject_id: value.subject_id,
    time: value.time,
    group: value.group,
    fit_method: value.fit_method,
    random_slope: value.random_slope,
  };
}

function ColumnSelect(props: {
  label: string;
  value: string;
  columns: readonly string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="ios-field">
      <span>{props.label}</span>
      <select
        aria-label={props.label}
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
      >
        <option value="">(选择列)</option>
        {props.columns.map((column) => (
          <option key={column} value={column}>{column}</option>
        ))}
      </select>
    </label>
  );
}

export function RepeatedMeasuresControls(props: RepeatedMeasuresControlsProps) {
  const value = exactOptions(props.value);
  const update = <Key extends keyof RepeatedMeasuresOptions>(
    key: Key,
    value: RepeatedMeasuresOptions[Key],
  ) => props.onChange({ ...exactOptions(props.value), [key]: value } as RepeatedMeasuresOptions);

  return (
    <section className="ios-group" aria-label="Repeated measures settings">
      <ColumnSelect label="Subject ID" value={value.subject_id} columns={props.columns}
        onChange={(value) => update("subject_id", value)} />
      <ColumnSelect label="Time" value={value.time} columns={props.columns}
        onChange={(value) => update("time", value)} />
      <ColumnSelect label="Group" value={value.group} columns={props.columns}
        onChange={(value) => update("group", value)} />
      <label className="ios-field">
        <span>Fit method</span>
        <select aria-label="Fit method" value={value.fit_method}
          onChange={(event) => update("fit_method", event.target.value as "reml" | "ml")}>
          <option value="reml">REML</option>
          <option value="ml">ML</option>
        </select>
      </label>
      <label className="ios-row">
        <span>Random slope</span>
        <input aria-label="Random slope" type="checkbox" className="ios-switch"
          checked={value.random_slope}
          onChange={(event) => update("random_slope", event.target.checked)} />
      </label>
    </section>
  );
}
