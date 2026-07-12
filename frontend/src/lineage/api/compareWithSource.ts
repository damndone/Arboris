import type { NodeOperationContextV1 } from "./nodeOperationContext";
import {
  CompareSection,
  decisionSection,
  diagnosticsSection,
  emptySection,
  FieldDiff,
  recordSection,
  upstreamPathSection,
} from "./nodeDiff";

export type { CompareSection, FieldDiff } from "./nodeDiff";

export interface CompareWithSourceResult {
  compare_version: "compare-with-source/v1";
  compare_kind: "source";
  left: NodeOperationContextV1;
  right: NodeOperationContextV1;
  provenance: {
    source_kind: "node_level_rerun_from" | "run_level_rerun_from_fallback";
    rerun_request_id: string;
    patch_id?: string;
  };
  sections: {
    params: CompareSection<FieldDiff>;
    decisions: CompareSection<FieldDiff>;
    metrics: CompareSection<FieldDiff>;
    diagnostics: CompareSection<FieldDiff>;
    artifacts: CompareSection<FieldDiff>;
    upstream_path: CompareSection<FieldDiff>;
  };
}

export function buildCompareWithSourceResult(input: {
  source: NodeOperationContextV1;
  current: NodeOperationContextV1;
  provenance: CompareWithSourceResult["provenance"];
}): CompareWithSourceResult {
  const { source, current } = input;
  return {
    compare_version: "compare-with-source/v1",
    compare_kind: "source",
    left: source,
    right: current,
    provenance: input.provenance,
    sections: {
      params: recordSection("parameter", source.node_payload.params, current.node_payload.params),
      decisions: decisionSection(source.node_payload.decisions, current.node_payload.decisions),
      metrics: recordSection(
        "metric",
        source.node_payload.metrics ?? {},
        current.node_payload.metrics ?? {},
      ),
      diagnostics: diagnosticsSection(
        source.node_payload.execution_diagnostics,
        current.node_payload.execution_diagnostics,
      ),
      artifacts: emptySection("No artifact summary changes detected."),
      upstream_path: upstreamPathSection(source, current),
    },
  };
}
