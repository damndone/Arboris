// v1.9.0 — the steps of a manual analysis, as pure data. The panel edits a
// list of steps; these functions create a step, check the list before a
// preview, and say which earlier steps can feed a later one.

import { initialValue, validateValue, type JsonSchema } from "../schemaModel";
import type { Operation, Target } from "../manualApi";

export type Step = {
  step_id: string;
  operation_id: string;
  spec: Record<string, unknown>;
};

type Source = { from_step?: string };
type Branch = { branch_id?: unknown };

const schemaOf = (operation: Operation | undefined) => (operation?.spec_schema ?? { type: "object" }) as JsonSchema;

export function takesModel(operation: Operation | undefined): boolean {
  return !!schemaOf(operation).properties?.model_ref;
}

/** A new step, pre-bound to the selected model when it reads one. */
export function newStep(operation: Operation, index: number, target: Target | undefined, suffix: string): Step {
  let spec = (initialValue(schemaOf(operation)) ?? {}) as Record<string, unknown>;
  if (target?.kind === "model_node" && takesModel(operation)) spec = { ...spec, model_ref: target.node_id, model_run_id: target.run_id };
  return { step_id: `step_${index + 1}_${suffix}`, operation_id: operation.id, spec };
}

/** Problems that would make the server refuse the preview, one line per step. */
export function stepIssues(steps: Step[], operations: Operation[]): string[] {
  return steps.flatMap((step, index) => {
    const label = `Step ${index + 1}`;
    const operation = operations.find((op) => op.id === step.operation_id);
    if (!operation) return [`${label}: this operation is no longer offered.`];
    const schema = schemaOf(operation);
    const { source, ...fields } = step.spec;
    const earlier = steps.slice(0, index);
    if (source && !earlier.some((s) => s.step_id === (source as Source).from_step)) {
      return [`${label}: the dataset producer no longer exists before this step.`];
    }
    if (typeof step.spec.model_ref === "string" && step.spec.model_ref.startsWith("step:")) {
      const [, producerId, branchId] = step.spec.model_ref.split(":");
      const producer = earlier.find((s) => s.step_id === producerId);
      const branches = Array.isArray(producer?.spec.branches) ? (producer.spec.branches as Branch[]) : [];
      if (!branches.some((branch) => branch?.branch_id === branchId)) return [`${label}: choose a model branch from an earlier step.`];
    }
    return validateValue(schema, schema.properties?.source ? step.spec : fields, schema, label);
  });
}

/** Model branches declared by earlier steps, as `step:<step>:<branch>` references. */
export function modelProducers(steps: Step[], index: number): Array<{ value: string; label: string }> {
  return steps.slice(0, index).flatMap((producer, position) =>
    (Array.isArray(producer.spec.branches) ? (producer.spec.branches as Branch[]) : []).flatMap((branch) =>
      typeof branch?.branch_id === "string" && branch.branch_id
        ? [{ value: `step:${producer.step_id}:${branch.branch_id}`, label: `${position + 1}. ${branch.branch_id}` }]
        : [],
    ),
  );
}

/** Feed this step from an earlier step's dataset, or from the selected target. */
export function withSource(step: Step, fromStep: string): Step {
  const spec = { ...step.spec };
  if (fromStep) spec.source = { from_step: fromStep, output: "produced_dataset" };
  else delete spec.source;
  return { ...step, spec };
}

/** Read the model from an earlier step's branch, or from the selected model. */
export function withModelProducer(step: Step, reference: string, target: Target | undefined): Step {
  const spec = { ...step.spec };
  if (reference) {
    spec.model_ref = reference;
    delete spec.model_run_id;
  } else if (target?.kind === "model_node") {
    spec.model_ref = target.node_id;
    spec.model_run_id = target.run_id;
  } else {
    delete spec.model_ref;
    delete spec.model_run_id;
  }
  return { ...step, spec };
}
