// Reusable loader for the time-series pack's conclusion artifacts.
//
// Extracted from runResult.tsx so both the legacy result page and the graph
// node drawer read the same `ts.*` artifacts through one code path. Each
// artifact is stored as an envelope; we surface only its `payload`.

import { useEffect, useState } from "react";
import { fetchArtifactJson, fetchRunArtifacts, type ArtifactGroup } from "../api";
import type { ArmaGarchArtifacts } from "./ArmaGarchResultCard";

/** Logical field -> persisted artifact id. Mirrors the pack's artifact contract. */
export const ARMA_GARCH_ARTIFACT_IDS = {
  report: "ts.report",
  contract: "ts.analysis_contract",
  dataAudit: "ts.data_audit",
  meanCandidates: "ts.arma_candidates",
  volatilityCandidates: "ts.volatility_candidates",
  diagnostics: "ts.final_diagnostics",
  metrics: "ts.forecast_metrics",
  nextForecast: "ts.next_forecast",
  comparison: "ts.arma_vs_garch_comparison",
  conditionalSeries: "ts.conditional_series",
  artifactManifest: "ts.artifact_manifest",
} as const;

export function useArmaGarchArtifacts(
  projectRoot: string | null | undefined,
  runId: string | null | undefined,
  /** Pass an already-loaded artifact list to avoid a second listing request. */
  knownGroups?: ArtifactGroup[],
): ArmaGarchArtifacts | undefined {
  const [artifacts, setArtifacts] = useState<ArmaGarchArtifacts | undefined>(undefined);

  useEffect(() => {
    if (!projectRoot || !runId) {
      setArtifacts(undefined);
      return;
    }
    let cancelled = false;

    const listing = knownGroups
      ? Promise.resolve({ groups: knownGroups })
      : fetchRunArtifacts(projectRoot, runId);
    listing
      .then(async (value) => {
        const artifactIds = new Set(
          value.groups.flatMap((group) => group.items.map((item) => item.artifact_id)),
        );
        // The pack always writes ts.report on a completed run; its absence
        // means this run is not an ARMA-GARCH run.
        if (!artifactIds.has(ARMA_GARCH_ARTIFACT_IDS.report)) {
          if (!cancelled) setArtifacts(undefined);
          return;
        }
        const entries = await Promise.all(
          Object.entries(ARMA_GARCH_ARTIFACT_IDS).map(async ([key, artifactId]) => {
            if (!artifactIds.has(artifactId)) return [key, undefined] as const;
            try {
              const envelope = await fetchArtifactJson<{ payload?: Record<string, unknown> }>(
                projectRoot,
                runId,
                artifactId,
              );
              return [key, envelope?.payload] as const;
            } catch {
              return [key, undefined] as const;
            }
          }),
        );
        if (!cancelled) {
          setArtifacts(Object.fromEntries(entries) as ArmaGarchArtifacts);
        }
      })
      .catch(() => {
        if (!cancelled) setArtifacts(undefined);
      });

    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, knownGroups]);

  return artifacts;
}
