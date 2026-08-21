import type { ClassificationEvidencePolicyRef, ClassificationEvidenceProjectionRef } from "./ClassificationEvidence";

export type ReportRendererKey = "classification-evidence";

const CLASSIFICATION_REPORT_PROJECTION_REF = {
  kind: "projection",
  logical_id: "workbench.classification_ml.report",
  semantic_version: "1.0",
  contract_digest: "5".repeat(64),
} as const;

const CLASSIFICATION_REPORT_RENDERER_REF = {
  kind: "renderer",
  logical_id: "workbench.classification_ml.report",
  semantic_version: "1.0",
  contract_digest: "6".repeat(64),
} as const;

const CLASSIFICATION_REPORT_POLICY_REF = {
  kind: "policy",
  logical_id: "workbench.classification_ml.policy",
  semantic_version: "1.0",
  contract_digest: "7".repeat(64),
} as const satisfies ClassificationEvidencePolicyRef;

/** The only provider binding accepted by the central Report parser and fallbacks. */
export const CLASSIFICATION_REPORT_BINDING = {
  provider_id: "workbench.classification_ml",
  exposure_path: "workbench.classification_ml.direct",
  policy_ref: CLASSIFICATION_REPORT_POLICY_REF,
  catalog_digest: "f59d0cc8c5746f7e8905fa6ff79e31465b11614284bcb9849d1545bfb271c952",
  provider_digest: "f2cd959aae60720574e4687940d562b20ac2ad7afc14d58af423f7a9e9a2b43c",
  coverage_status: "required",
} as const;

function sameReference(
  value: ClassificationEvidenceProjectionRef | null,
  expected: ClassificationEvidenceProjectionRef,
): boolean {
  return value !== null
    && value.kind === expected.kind
    && value.logical_id === expected.logical_id
    && value.semantic_version === expected.semantic_version
    && value.contract_digest === expected.contract_digest;
}

/** Closed server-catalog binding; unknown refs never become components. */
export function resolveReportRenderer(
  projectionRef: ClassificationEvidenceProjectionRef | null,
  rendererRef: ClassificationEvidenceProjectionRef | null,
): ReportRendererKey | null {
  if (
    sameReference(projectionRef, CLASSIFICATION_REPORT_PROJECTION_REF)
    && sameReference(rendererRef, CLASSIFICATION_REPORT_RENDERER_REF)
  ) return "classification-evidence";
  return null;
}

export const CLASSIFICATION_REPORT_REFS = {
  projection: CLASSIFICATION_REPORT_PROJECTION_REF,
  renderer: CLASSIFICATION_REPORT_RENDERER_REF,
} as const;

/** Identity carried by every server-owned unavailable central projection. */
export const CLASSIFICATION_REPORT_UNAVAILABLE_IDENTITY = {
  ...CLASSIFICATION_REPORT_BINDING,
  projection_ref: CLASSIFICATION_REPORT_REFS.projection,
  renderer_ref: CLASSIFICATION_REPORT_REFS.renderer,
} as const;
