import type { Capabilities } from "../capabilities/types";

export function ImputationControls(props: {
  capabilities: Capabilities | null | undefined;
  value: string | null; // method key or null (not requested)
  onChange: (key: string | null) => void;
}) {
  const methods = props.capabilities?.imputation_methods ?? [];
  if (methods.length === 0) return null;

  if (methods.length === 1) {
    const only = methods[0];
    return (
      <div className="imputation-controls">
        <label>
          <input
            type="checkbox"
            checked={props.value === only.key}
            onChange={(e) => props.onChange(e.target.checked ? only.key : null)}
          />{" "}
          Impute missing values ({only.label})
        </label>
        {only.description && (
          <div className="imputation-controls-hint">{only.description}</div>
        )}
      </div>
    );
  }

  // 2+ methods: select
  return (
    <div className="imputation-controls">
      <label>
        Imputation
        <select
          value={props.value ?? ""}
          onChange={(e) => props.onChange(e.target.value || null)}
        >
          <option value="">(none)</option>
          {methods.map((m) => (
            <option key={m.key} value={m.key} title={m.description}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
