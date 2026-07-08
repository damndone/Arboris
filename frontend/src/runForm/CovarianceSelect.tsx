import type { Capabilities } from "../capabilities/types";

export function covarianceDefault(capabilities: Capabilities | null | undefined): string {
  return capabilities?.covariance_options?.[0]?.key ?? "";
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
      <span>标准误 covariance</span>
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
