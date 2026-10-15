import type { Operation, Target } from "./manualApi";

/** Navigation requirements; execution authority remains with each server route. */
export function dedicatedTargetReason(operation: Operation, target?: Target): string | undefined {
  if (operation.execution.kind !== "dedicated") return;
  const requirements = operation.target_requirements ?? [];
  if (requirements.includes("dataset_node") && target?.kind !== "dataset_node") return "Select a dataset target first.";
  if ((requirements.includes("model_nodes") || operation.id === "model.rerun" || operation.id === "script.export") && target?.kind !== "model_node") return "Select a model target first.";
  if ((requirements.includes("run") || requirements.includes("graph_node")) && (!target || !("run_id" in target))) return "Select a saved data or model target first.";
}
