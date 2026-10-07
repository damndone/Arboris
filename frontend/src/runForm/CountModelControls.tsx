export type CountModelType = "negative_binomial" | "glm:negative_binomial";
export type CountModelOptions = {dispersion: "mean" | "constant"; fixed: boolean; alpha: string};
export const emptyCountOptions: CountModelOptions = {dispersion: "mean", fixed: false, alpha: ""};

export function isCountModelType(value: string): value is CountModelType {
  return value === "negative_binomial" || value === "glm:negative_binomial";
}

export function countModelValidationError(modelType: CountModelType, value: CountModelOptions): string | null {
  const fixed = modelType === "glm:negative_binomial" || value.fixed;
  if (modelType === "negative_binomial" && value.fixed && value.dispersion === "constant") {
    return "Fixed alpha is available for NB2 only. Uncheck fixed alpha to estimate NB1 dispersion.";
  }
  if (fixed && (!value.alpha.trim() || !Number.isFinite(Number(value.alpha)) || Number(value.alpha) <= 0)) {
    return "Enter an explicit finite positive alpha.";
  }
  return null;
}

export function buildCountModelOptions(modelType: CountModelType, value: CountModelOptions): Record<string, unknown> {
  const error = countModelValidationError(modelType, value);
  if (error) throw new Error(error);
  const alpha = Number(value.alpha);
  return modelType === "glm:negative_binomial" ? {alpha}
    : {...{dispersion: value.dispersion}, ...(value.fixed ? {alpha} : {})};
}

export function CountModelControls(props: {
  modelType: CountModelType;
  value: CountModelOptions;
  onChange: (value: CountModelOptions) => void;
}) {
  const {modelType, value, onChange} = props;
  const isMl = modelType === "negative_binomial";
  const fixed = !isMl || value.fixed;
  return <div className="ios-group" aria-label="Negative binomial settings">
    {isMl && <>
      <label className="ios-field"><span>Dispersion</span>
        <select aria-label="Dispersion" value={value.dispersion}
          onChange={event => onChange({...value, dispersion: event.target.value as CountModelOptions["dispersion"]})}>
          <option value="mean">NB2: variance = mean + alpha × mean²</option>
          <option value="constant">NB1: variance = (1 + delta) × mean</option>
        </select>
      </label>
      <label className="ios-field"><input type="checkbox" aria-label="Fix alpha (advanced)"
        checked={value.fixed} onChange={event => onChange({...value, fixed: event.target.checked})}/>
        <span>Fix alpha (advanced)</span>
      </label>
    </>}
    {fixed && <label className="ios-field"><span>Fixed alpha</span>
      <input type="number" step="any" aria-label="Fixed alpha" value={value.alpha}
        onChange={event => onChange({...value, alpha: event.target.value})}/>
    </label>}
    <p className="ios-hint">{fixed
      ? "Alpha is fixed at your supplied value. It is not estimated; no dispersion interval or Poisson boundary LR test is reported."
      : "Dispersion is estimated jointly by maximum likelihood. Regression inference uses observed information."}</p>
  </div>;
}
