import { useEffect, useState } from "react";
import { catalog, type Operation } from "../../manual/manualApi";
import { SchemaField, type JsonSchema } from "../../manual/SchemaFields";
import { validateValue } from "../../manual/schemaModel";

/** Uses the manual operation declarations; revisions still receive server validation. */
export function ProposalFields({ projectRoot, label, value, onChange, onIssues }: {
  projectRoot: string;
  label: string;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  onIssues: (issues: string[]) => void;
}) {
  const workflow = Array.isArray(value.steps);
  const [operations, setOperations] = useState<Operation[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!workflow) return;
    let current = true;
    setOperations(null);
    setError("");
    catalog(projectRoot).then(result => { if (current) setOperations(result.operations); })
      .catch(reason => { if (current) setError(String(reason)); });
    return () => { current = false; };
  }, [projectRoot, workflow]);
  useEffect(() => {
    if (!workflow) { onIssues([]); return; }
    if (!operations) { onIssues([error || "Loading operation declarations…"]); return; }
    const issues = (value.steps as unknown[]).flatMap((raw, index) => {
      const step = raw as Record<string, unknown>;
      const declaration = operations.find(op => op.id === step.operation_id);
      if (!declaration) return [`Step ${index + 1}: operation declaration is unavailable.`];
      const schema = declaration.spec_schema as JsonSchema;
      const spec = step.spec as Record<string, unknown> | undefined;
      const fields = spec && !schema.properties?.source ? Object.fromEntries(Object.entries(spec).filter(([key]) => key !== "source")) : spec;
      return validateValue(schema, fields, schema, `Step ${index + 1}`);
    });
    onIssues(issues);
  }, [value, workflow, operations, error, onIssues]);
  if (!workflow) return <SchemaField label={label} schema={{type: "object"}} value={value} onChange={next => onChange(next as Record<string, unknown>)} />;
  if (!operations) return <p role={error ? "alert" : "status"}>{error || "Loading operation declarations…"}</p>;
  const {steps, ...metadata} = value;
  return <>
    <SchemaField label={label} schema={{type: "object"}} value={metadata} onChange={next => onChange({...next as Record<string, unknown>, steps})} />
    {(steps as Record<string, unknown>[]).map((step, index) => {
      const {spec, ...stepMetadata} = step;
      const schema = operations.find(op => op.id === step.operation_id)?.spec_schema as JsonSchema | undefined;
      const update = (next: Record<string, unknown>) => onChange({...value, steps: (steps as unknown[]).map((old, i) => i === index ? next : old)});
      // Keep the producer reference alongside the declared fields for composition.
      const editable = schema ? {...schema, properties: {...schema.properties, source: {type: "object"} as JsonSchema}} : {type: "object"} as JsonSchema;
      return <fieldset key={index}><legend>Step {index + 1}</legend>
        <SchemaField label={`${label}.steps[${index + 1}]`} schema={{type: "object"}} value={stepMetadata} onChange={next => update({...next as Record<string, unknown>, spec})} />
        <SchemaField label={`${label}.steps[${index + 1}].spec`} schema={editable} value={spec} onChange={next => update({...step, spec: next})} />
      </fieldset>;
    })}
  </>;
}
