export type Role =
  | "outcome" | "focal" | "treatment" | "covariates"
  | "explanatory_unspecified" | "instruments" | "exposure"
  | "unit" | "time" | "cluster";

export const ROLE_OF_EDGE_OP: Record<string, Role> = {
  enters_as_outcome: "outcome",
  enters_as_focal: "focal",
  enters_as_treatment: "treatment",
  enters_as_covariates: "covariates",
  enters_as_explanatory_unspecified: "explanatory_unspecified",
  offsets_as_exposure: "exposure",
  identifies_as_instruments: "instruments",
  configures_unit: "unit",
  configures_time: "time",
  configures_cluster: "cluster",
};

export const ROLE_GROUP_ORDER: Role[] = [
  "outcome", "focal", "treatment", "covariates",
  "instruments", "exposure", "unit", "time", "cluster",
];

const LABELS: Record<Role, string> = {
  outcome: "Outcome Variable (Y)",
  focal: "Focal Explanatory Variable (X)",
  treatment: "Treatment (D)",
  covariates: "Covariates (Z)",
  explanatory_unspecified: "Explanatory variables (role unspecified)",
  instruments: "Instruments",
  exposure: "Exposure / offset",
  unit: "Unit (entity)",
  time: "Time",
  cluster: "Cluster (inference)",
};

export function roleLabel(role: Role): string {
  return LABELS[role];
}

export const DASHED_ROLES: Set<Role> = new Set(["unit", "time", "cluster"]);

// v1.6.5 canvas helpers — role colour token + short on-node abbreviation.
export function roleColorVar(role: Role): string {
  return `var(--role-${role.replace(/_/g, "-")})`;
}

const ABBREV: Record<Role, string> = {
  outcome: "Y",
  focal: "X",
  treatment: "D",
  covariates: "Z",
  explanatory_unspecified: "X",
  instruments: "IV",
  exposure: "off",
  unit: "U",
  time: "T",
  cluster: "C",
};

export function roleAbbrev(role: Role): string {
  return ABBREV[role];
}
