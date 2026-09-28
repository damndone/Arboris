import type {
  EvidenceFactViewModel,
  EvidenceSectionViewModel,
  EvidenceViewModel,
} from "../report/reportEvidence";

export interface NotebookEvidenceContract {
  readonly contract: "workbench.notebook.evidence.v1";
  readonly projectionId: string;
  readonly consumerId: "notebook";
  readonly consumerVersion: string;
  readonly artifactRef: string;
  readonly envelopeRef: string;
  readonly envelopeDigest: string;
  readonly status: EvidenceViewModel["status"];
  readonly executionStatus: string;
  readonly availability: string;
  readonly completenessStatus: string;
  readonly facts: readonly EvidenceFactViewModel[];
  readonly sections: readonly EvidenceSectionViewModel[];
}

/** Copy the already typed projection into a notebook envelope; no calculations. */
export function toNotebookEvidenceContract(
  evidence: EvidenceViewModel,
): NotebookEvidenceContract | null {
  if (evidence.consumerId !== "notebook") return null;
  return {
    contract: "workbench.notebook.evidence.v1",
    projectionId: evidence.projectionId,
    consumerId: "notebook",
    consumerVersion: evidence.consumerVersion,
    artifactRef: evidence.artifactRef,
    envelopeRef: evidence.envelopeRef,
    envelopeDigest: evidence.envelopeDigest,
    status: evidence.status,
    executionStatus: evidence.executionStatus,
    availability: evidence.availability,
    completenessStatus: evidence.completenessStatus,
    facts: evidence.facts,
    sections: evidence.sections,
  };
}

