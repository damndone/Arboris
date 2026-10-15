// v1.9.0 — what a manual analysis can run on: the datasets of the source run
// and the models in the project. The list is read once per source run (and
// again after an analysis completes); repeated labels are numbered.

import { useEffect, useState } from "react";
import { fetchDatasetPage, listDatasets } from "../../dataView/dataViewApi";
import type { Target } from "../manualApi";

export type ModelChoice = { runId: string; nodeId: string; label: string };

export type TargetChoice = {
  key: string;
  kind: "Data" | "Model";
  label: string;
  target: Target;
  columns: string[];
};

function numbered<T extends { label: string }>(items: T[]): T[] {
  const totals = new Map<string, number>();
  items.forEach((item) => totals.set(item.label, (totals.get(item.label) ?? 0) + 1));
  const seen = new Map<string, number>();
  return items.map((item) => {
    if ((totals.get(item.label) ?? 0) < 2) return item;
    const n = (seen.get(item.label) ?? 0) + 1;
    seen.set(item.label, n);
    return { ...item, label: `${item.label} (${n})` };
  });
}

export function useTargetChoices(projectRoot: string, sourceRunId: string, models: ModelChoice[], revision: number) {
  const [choices, setChoices] = useState<TargetChoice[] | null>(null);
  const [error, setError] = useState("");
  const modelKey = JSON.stringify(models);
  useEffect(() => {
    let live = true;
    (async () => {
      const datasets = sourceRunId ? await listDatasets(projectRoot, sourceRunId) : [];
      const data = await Promise.all(
        datasets.map(async (dataset) => {
          const page = await fetchDatasetPage(projectRoot, sourceRunId, dataset.node_id, { offset: 0, limit: 1 });
          const target: Target = { kind: "dataset_node", run_id: sourceRunId, node_id: dataset.node_id, artifact_id: page.artifact_id };
          return { key: JSON.stringify(target), kind: "Data" as const, label: dataset.label, target, columns: page.columns };
        }),
      );
      const fitted = (JSON.parse(modelKey) as ModelChoice[]).map((model) => {
        const target: Target = { kind: "model_node", run_id: model.runId, node_id: model.nodeId };
        return { key: JSON.stringify(target), kind: "Model" as const, label: model.label, target, columns: [] };
      });
      if (live) setChoices([...numbered(data), ...numbered(fitted)]);
    })().catch((reason) => live && setError(reason instanceof Error ? reason.message : String(reason)));
    return () => {
      live = false;
    };
  }, [projectRoot, sourceRunId, modelKey, revision]);
  return { choices, error };
}
