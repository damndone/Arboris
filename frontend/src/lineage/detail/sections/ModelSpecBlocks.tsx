// frontend/src/lineage/detail/sections/ModelSpecBlocks.tsx
//
// V1.6.5 — node detail drawer model-spec blocks (Plan §7 / Phase D4).
//
// Separates the model specification into reader-friendly blocks instead of
// one flat RHS string:
//   - Formula:        outcome ~ focal + covariates   (or ~ explanatory when
//                     focal is empty). NEVER concatenates instruments or the
//                     exposure offset into the RHS — those identify / offset,
//                     they are not regressors.
//   - Identification: instruments (only when present)
//   - Offset:         exposure (only when present)
//   - Inference:      unit / time / cluster (only when present)
//
// Focal/Treatment are read from the structural spec the caller passes (derived
// from role edges), never from a stale `focal_x` string.

export interface ModelSpec {
  outcome: string;
  focal: string[];
  /** Causal families (DID/CS/SA/dCDH) carry treatment instead of focal. */
  treatment?: string[];
  covariates: string[];
  /** Used only when focal+covariates are both empty (role unspecified). */
  explanatory?: string[];
  instruments: string[];
  exposure: string | null;
  unit: string | null;
  time: string | null;
  cluster: string | null;
  se_type?: string;
  estimator?: string;
}

import type { RoleGroup } from "../../../workbench/RunSnapshotAdapter";

/** Build a ModelSpec from the role-edge groups for a model node. Roles live
 *  on the edges, so this is the single source of truth — never a stale
 *  `focal_x`. `se_type` / `estimator` are optional drawer metadata. */
export function deriveModelSpec(
  groups: RoleGroup[],
  meta: { se_type?: string; estimator?: string } = {},
): ModelSpec {
  const cols = (role: string) =>
    groups.find((g) => g.role === role)?.columns ?? [];
  const first = (role: string) => cols(role)[0] ?? null;
  return {
    outcome: first("outcome") ?? "",
    focal: cols("focal"),
    treatment: cols("treatment"),
    covariates: cols("covariates"),
    explanatory: cols("explanatory_unspecified"),
    instruments: cols("instruments"),
    exposure: first("exposure"),
    unit: first("unit"),
    time: first("time"),
    cluster: first("cluster"),
    se_type: meta.se_type,
    estimator: meta.estimator,
  };
}

function Block({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        className="ln-section-label"
        style={{ marginBottom: 4, fontSize: 11, color: "var(--label-secondary)" }}
      >
        {label}
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--label)" }}>
        {children}
      </div>
    </div>
  );
}

export function ModelSpecBlocks({ spec }: { spec: ModelSpec }) {
  const treatment = spec.treatment ?? [];
  const structural = [...spec.focal, ...treatment, ...spec.covariates];
  const rhs = structural.length > 0 ? structural : spec.explanatory ?? [];
  const formula = `${spec.outcome} ~ ${rhs.join(" + ")}`;

  const meta = [spec.estimator, spec.se_type].filter(Boolean).join(" · ");
  const hasInference = Boolean(spec.unit || spec.time || spec.cluster);

  return (
    <div data-testid="model-spec-blocks">
      <Block label="Formula">
        <div>{formula}</div>
        {meta && (
          <div style={{ marginTop: 4, fontSize: 11, color: "var(--label-tertiary)" }}>
            {meta}
          </div>
        )}
      </Block>

      {spec.instruments.length > 0 && (
        <Block label="Identification (instruments)">
          {spec.instruments.join(", ")}
        </Block>
      )}

      {spec.exposure && <Block label="Offset (exposure)">{spec.exposure}</Block>}

      {hasInference && (
        <Block label="Inference / panel">
          {[
            spec.unit && `unit: ${spec.unit}`,
            spec.time && `time: ${spec.time}`,
            spec.cluster && `cluster: ${spec.cluster}`,
          ]
            .filter(Boolean)
            .join("  ·  ")}
        </Block>
      )}
    </div>
  );
}
