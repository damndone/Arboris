export type ModelGroup = "auto" | "Linear" | "Binary" | "Count" | "Panel" | "GLM" | "IV";

export interface ModelTypeEntry {
  key: string;
  label: string;
  group: ModelGroup;
  description?: string;
  requires?: string[];
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
}

export interface Capabilities {
  schema_version: number;
  model_types: ModelTypeEntry[];
  imputation_methods: ImputationMethodEntry[];
  prediction_models?: PredictionModelEntry[];
  sampling_methods?: SamplingMethodEntry[];
  covariance_options?: CovarianceOption[];
}
