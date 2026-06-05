export type ModelGroup = "auto" | "Linear" | "Binary" | "Count" | "Panel" | "GLM";

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

export interface Capabilities {
  schema_version: number;
  model_types: ModelTypeEntry[];
  imputation_methods: ImputationMethodEntry[];
}
