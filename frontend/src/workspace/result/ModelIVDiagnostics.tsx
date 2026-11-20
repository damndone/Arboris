import {useEffect, useState} from "react";
import {fetchArtifactJson} from "../../api";
import {IVDiagnosticsCard, type IVDiagnostics} from "../../runResult/IVDiagnosticsCard";

const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const probability = (value: unknown): boolean =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
const statistic = (value: unknown): boolean => typeof value === "number" && Number.isFinite(value);
const optionalNumber = (value: unknown): boolean => value == null || statistic(value);

function validARSet(value: unknown): boolean {
  if (value == null) return true;
  if (!record(value) || typeof value.kind !== "string" || !optionalNumber(value.lower) || !optionalNumber(value.upper) ||
      (value.reason != null && typeof value.reason !== "string")) return false;
  if (value.global_certification != null && (!record(value.global_certification) ||
      typeof value.global_certification.status !== "string")) return false;
  return value.components == null || (Array.isArray(value.components) && value.components.every(component =>
    record(component) && (component.lower === null || statistic(component.lower)) &&
    (component.upper === null || statistic(component.upper)) &&
    typeof component.lower_closed === "boolean" && typeof component.upper_closed === "boolean"));
}

/** Read only the selected model's registered completion artifact, never run-level diagnostics. */
export async function loadModelIVDiagnostics(projectRoot: string, runId: string, modelId: string): Promise<IVDiagnostics> {
  const evidence = await fetchArtifactJson(projectRoot, runId, `${modelId}.completion`);
  if (!record(evidence) || evidence.contract !== "analysis-completion.evidence.v2") {
    throw new Error("The completion evidence contract is not analysis-completion.evidence.v2.");
  }
  if (evidence.model_id !== modelId) throw new Error("The completion evidence does not match the selected model.");
  if (evidence.model_type !== "iv_2sls") throw new Error("The completion evidence model type is not iv_2sls.");
  if (!record(evidence.diagnostics) || evidence.diagnostics.iv == null) {
    throw new Error("The selected model's completion evidence has no IV diagnostics.");
  }
  const iv = evidence.diagnostics.iv;
  if (!record(iv) || !["under", "just", "over"].includes(String(iv.identification)) ||
      !record(iv.weak_instruments) || typeof iv.weak_instruments.message !== "string" ||
      !record(iv.endogeneity) || !record(iv.overidentification)) {
    throw new Error("The selected model's completion evidence contains malformed IV diagnostics.");
  }
  const weak = iv.weak_instruments;
  const validWeak = ["strong", "caution", "weak", "unassessed"].includes(weak.verdict as string) &&
    (weak.test == null || typeof weak.test === "string") &&
    (weak.reference_distribution == null || typeof weak.reference_distribution === "string") &&
    [weak.first_stage_f, weak.first_stage_statistic, weak.threshold, weak.caution_threshold].every(optionalNumber) &&
    validARSet(weak.anderson_rubin_95);
  const endogeneity = iv.endogeneity;
  const overidentification = iv.overidentification;
  const validEndogeneity = typeof endogeneity.test === "string" && typeof endogeneity.message === "string" &&
    (endogeneity.verdict === "unavailable"
      ? endogeneity.statistic === null && endogeneity.pvalue === null && typeof endogeneity.reason === "string" && !!endogeneity.reason
      : ["rejects_exogeneity", "does_not_reject", "endogenous", "exogenous"].includes(String(endogeneity.verdict)) &&
        statistic(endogeneity.statistic) && probability(endogeneity.pvalue));
  const validOveridentification = typeof overidentification.verdict === "string" &&
    (overidentification.applicable === false || (overidentification.applicable === true &&
      typeof overidentification.test === "string" && typeof overidentification.message === "string" &&
      statistic(overidentification.statistic) && probability(overidentification.pvalue)));
  if (!validWeak || !validEndogeneity || !validOveridentification) {
    throw new Error("The selected model's completion evidence contains malformed IV diagnostics.");
  }
  return iv as unknown as IVDiagnostics;
}

type Load = {status: "loading"} | {status: "error"; message: string} | {status: "ready"; diagnostics: IVDiagnostics};

export function ModelIVDiagnostics({projectRoot, runId, modelId}: {projectRoot: string; runId: string; modelId: string}) {
  const [load, setLoad] = useState<Load>({status: "loading"});
  useEffect(() => {
    let live = true;
    setLoad({status: "loading"});
    loadModelIVDiagnostics(projectRoot, runId, modelId)
      .then(diagnostics => {if (live) setLoad({status: "ready", diagnostics});})
      .catch((error: unknown) => {
        if (live) setLoad({status: "error", message: error instanceof Error ? error.message : String(error)});
      });
    return () => {live = false;};
  }, [projectRoot, runId, modelId]);

  if (load.status === "loading") return <p className="ws-result__note" role="status">Loading IV diagnostics…</p>;
  if (load.status === "error") return <p className="ws-result__note" role="alert">IV diagnostics could not be loaded for {modelId}: {load.message}</p>;
  return <IVDiagnosticsCard diagnostics={load.diagnostics}/>;
}
