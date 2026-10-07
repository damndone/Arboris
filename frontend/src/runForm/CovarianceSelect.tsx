import type { Capabilities } from "../capabilities/types";

export function covarianceDefault(capabilities: Capabilities | null | undefined, modelType?: string): string {
  // v1.8.11: a family may declare its own default (panel and DID cluster by
  // entity); it is the value of that family's covariance control.
  const family = modelType ? capabilities?.model_types?.find((entry) => entry.key === modelType) : undefined;
  const declared = family?.params?.find((param) => param.key === "covariance")?.value;
  if (typeof declared === "string" && declared) return declared;
  // U3: read the option the backend flags as default. Fall back to the first
  // option only if none is flagged (defensive) — never assume ordering.
  const options = capabilities?.covariance_options ?? [];
  return (options.find((option) => option.default)?.key ?? options[0]?.key) ?? "";
}

export function CovarianceSelect({
  capabilities,
  value,
  onChange,
}: {
  capabilities: Capabilities | null | undefined;
  value: string;
  onChange: (value: string) => void;
}) {
  const options = capabilities?.covariance_options ?? [];
  if (options.length === 0) return null;
  return (
    <label className="ios-field">
      <span>Covariance</span>
      <select
        aria-label="covariance"
        value={value || covarianceDefault(capabilities)}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.key} value={option.key}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
