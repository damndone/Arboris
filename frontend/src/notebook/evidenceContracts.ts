import { readPersistedEvidenceProjection, type EvidenceViewModel } from "../report/reportEvidence";

export type NotebookEvidenceContract = EvidenceViewModel & {
  readonly contract: "workbench.notebook.evidence.v1";
  readonly consumerId: "notebook";
};
/** Copy the already typed projection into a notebook envelope; no calculations. */
export function toNotebookEvidenceContract(
  evidence: EvidenceViewModel,
): NotebookEvidenceContract | null {
  const parsedEvidence = readPersistedEvidenceProjection(evidence);
  if (!parsedEvidence
    || parsedEvidence.consumerId !== "notebook"
    || (parsedEvidence.contract !== undefined && parsedEvidence.contract !== "workbench.notebook.evidence.v1")) return null;
  return {
    ...parsedEvidence,
    contract: "workbench.notebook.evidence.v1",
    consumerId: "notebook",
  };
}
