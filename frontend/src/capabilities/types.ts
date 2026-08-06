export type ModelGroup = "auto" | "Linear" | "Binary" | "Count" | "Panel" | "GLM" | "IV" | "DID" | "Causal" | "Time Series" | "Ordinal" | "Nominal" | "Survival" | "Quantile";

export interface EditableControlSpec {
  key: string;
  kind: "radio" | "select" | "multiselect" | "slider" | "text" | "textarea" | "toggle" | "columns" | "json";
  label?: string;
  role?: string;
  required?: boolean;
  value?: unknown;
  options?: Array<string | { value: unknown; label: string }>;
}

export interface ModelTypeEntry {
  key: string;
  label: string;
  group: ModelGroup;
  description?: string;
  requires?: string[];
  schema_id?: string;
  params?: EditableControlSpec[];
}

export interface ImputationMethodEntry {
  key: string;
  label: string;
  description?: string;
}

export interface PredictionModelEntry {
  key: string;
  label: string;
  description?: string;
}

export interface SamplingMethodEntry {
  key: string;
  label: string;
}

export interface CovarianceOption {
  key: string;
  label: string;
  /** U3: backend marks the default option explicitly; consumers must read this
   *  flag rather than assuming `options[0]` (reordering must not change SE). */
  default?: boolean;
}

/** Published so the form can *derive* what composes instead of restating it.
 *  A local copy of these option sets drifts the first time the backend adds or
 *  withdraws a policy, and nothing reports the disagreement. */
export interface SurveyDesignCapability {
  variance_methods: string[];
  variance_method_requirements: Record<string, string[]>;
  replicate_types: string[];
  lonely_psu_policies: string[];
  design_fields: string[];
}

export interface Capabilities {
  schema_version: number;
  editable_stages?: string[];
  model_types: ModelTypeEntry[];
  imputation_methods: ImputationMethodEntry[];
  prediction_models?: PredictionModelEntry[];
  sampling_methods?: SamplingMethodEntry[];
  covariance_options?: CovarianceOption[];
  survey_design?: SurveyDesignCapability;
}
