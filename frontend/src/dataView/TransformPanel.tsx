import { useState } from "react";

import {
  confirmDataTransform,
  confirmFeatureRecipe,
  previewDataTransform,
  previewFeatureRecipe,
  type DataTransformRequest,
  type FeatureRecipeRequest,
} from "../lineage/dataOperations";
import type { DatasetVariable } from "./dataViewApi";
import { parseRecodeRules } from "./recodeRules";
import { ToolSheet } from "./ToolSheet";

type Operation = "filter" | "keep" | "recode" | "compute" | "rename" | "dedupe" | "fill";

const OPERATIONS: { id: Operation; label: string; hint: string }[] = [
  { id: "filter", label: "Select rows", hint: "Keep the rows where every condition holds." },
  { id: "keep", label: "Keep variables", hint: "Keep only the variables you tick." },
  { id: "recode", label: "Recode into new variable", hint: "Map values and ranges to new codes, one rule per line; the first match wins." },
  { id: "compute", label: "Compute new variable", hint: "A sum, difference, product, ratio or natural log of numeric variables." },
  { id: "rename", label: "Rename variable", hint: "Give one variable a new name." },
  { id: "dedupe", label: "Remove duplicate rows", hint: "Rows equal on the ticked variables count as duplicates; the first is kept." },
  { id: "fill", label: "Fill missing values", hint: "Replace missing values of one variable, or drop those rows." },
];

const FILTER_OPS = [
  ["eq", "="], ["ne", "≠"], ["gt", ">"], ["ge", "≥"], ["lt", "<"], ["le", "≤"],
  ["between", "between"], ["is_missing", "is missing"], ["not_missing", "is not missing"],
] as const;

type Condition = { column: string; op: string; value: string; high: string };

type Preview = {
  rowsBefore: number;
  rowsAfter: number;
  outputColumns: string[];
  invalidates: string[];
  blocked: string | null;
  fingerprint: string;
};

type Built =
  | { kind: "transform"; request: DataTransformRequest }
  | { kind: "recipe"; request: FeatureRecipeRequest };

function literal(text: string, numeric: boolean): number | string {
  const trimmed = text.trim();
  return numeric && trimmed !== "" && !Number.isNaN(Number(trimmed)) ? Number(trimmed) : trimmed;
}

/** Guided data operations; each confirmed operation becomes a child dataset. */
export function TransformPanel({
  projectRoot,
  runId,
  nodeId,
  artifactId,
  variables,
  onCreated,
  onClose,
}: {
  projectRoot: string;
  runId: string;
  nodeId: string;
  artifactId: string;
  variables: DatasetVariable[];
  onCreated: (childNodeId: string) => void;
  onClose?: () => void;
}) {
  const names = variables.map((variable) => variable.name);
  const numeric = new Set(variables.filter((variable) => variable.type === "numeric").map((variable) => variable.name));
  const first = names[0] ?? "";
  const [operation, setOperation] = useState<Operation>("filter");
  const [conditions, setConditions] = useState<Condition[]>([{ column: first, op: "ge", value: "", high: "" }]);
  const [keep, setKeep] = useState<string[]>(names);
  const [column, setColumn] = useState(first);
  const [second, setSecond] = useState(names[1] ?? first);
  const [output, setOutput] = useState("");
  const [rulesText, setRulesText] = useState("");
  const [computeOp, setComputeOp] = useState("add");
  const [fillStrategy, setFillStrategy] = useState("mean");
  const [fillValue, setFillValue] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [built, setBuilt] = useState<Built | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const source = { source_run_id: runId, source_node_id: nodeId, source_artifact_id: artifactId };

  function reset() {
    setPreview(null);
    setBuilt(null);
    setError(null);
  }

  function build(): Built {
    const transform = (op: DataTransformRequest["operation"], parameters: Record<string, unknown>): Built => ({
      kind: "transform",
      request: { ...source, operation: op, parameters },
    });
    switch (operation) {
      case "filter": {
        const filters = conditions.map((condition) => {
          const isNumber = numeric.has(condition.column);
          if (condition.op === "is_missing" || condition.op === "not_missing") {
            return { column: condition.column, op: condition.op };
          }
          if (condition.op === "between") {
            return { column: condition.column, op: "between", value: [literal(condition.value, isNumber), literal(condition.high, isNumber)] };
          }
          if (condition.value.trim() === "") throw new Error(`give a value for ${condition.column}`);
          return { column: condition.column, op: condition.op, value: literal(condition.value, isNumber) };
        });
        return transform("subset", { columns: names, filters });
      }
      case "keep":
        if (keep.length === 0) throw new Error("keep at least one variable");
        return transform("subset", { columns: names.filter((name) => keep.includes(name)) });
      case "recode":
        if (!output.trim()) throw new Error("name the new variable");
        return transform("recode", { column, output: output.trim(), rules: parseRecodeRules(rulesText) });
      case "rename":
        if (!output.trim()) throw new Error("give the new name");
        return transform("rename", { mapping: { [column]: output.trim() } });
      case "dedupe":
        return transform("dedupe", { columns: names.filter((name) => keep.includes(name)), keep: "first" });
      case "fill": {
        const strategy: Record<string, unknown> = { column, strategy: fillStrategy };
        if (fillStrategy === "constant") strategy.value = literal(fillValue, numeric.has(column));
        return transform("fill_missing", { strategies: [strategy] });
      }
      case "compute": {
        if (!output.trim()) throw new Error("name the new variable");
        const base = { ...source, recipe_id: `data-view-${output.trim()}`, output: output.trim(), output_type: "numeric" };
        if (computeOp === "log") {
          return { kind: "recipe", request: { ...base, operation_id: "log", inputs: [column], parameters: { input: column, base: "e" } } };
        }
        if (computeOp === "ratio") {
          return {
            kind: "recipe",
            request: { ...base, operation_id: "ratio", inputs: [column, second], parameters: { numerator: column, denominator: second, zero_policy: "fail_closed" } },
          };
        }
        return {
          kind: "recipe",
          request: { ...base, operation_id: "derived_variable", inputs: [column, second], parameters: { operator: computeOp } },
        };
      }
    }
  }

  async function runPreview() {
    setBusy(true);
    reset();
    try {
      const next = build();
      if (next.kind === "transform") {
        const { preview: result } = await previewDataTransform(projectRoot, next.request);
        setPreview({
          rowsBefore: result.row_count_before, rowsAfter: result.row_count_after,
          outputColumns: result.output_columns, invalidates: result.downstream_invalidation,
          blocked: result.status === "ready" ? null : result.reason ?? "blocked", fingerprint: result.fingerprint,
        });
      } else {
        const { preview: result } = await previewFeatureRecipe(projectRoot, next.request);
        setPreview({
          rowsBefore: result.row_count, rowsAfter: result.row_count,
          outputColumns: result.output_columns, invalidates: result.downstream_invalidation,
          blocked: result.status === "ready" ? null : result.reason ?? "blocked", fingerprint: result.fingerprint,
        });
      }
      setBuilt(next);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Preview failed");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!built || !preview) return;
    setBusy(true);
    setError(null);
    try {
      const response =
        built.kind === "transform"
          ? await confirmDataTransform(projectRoot, { ...built.request, preview_fingerprint: preview.fingerprint })
          : await confirmFeatureRecipe(projectRoot, { ...built.request, preview_fingerprint: preview.fingerprint });
      const child = response.effect.child_node_id;
      if (typeof child !== "string") throw new Error("The operation did not report its new dataset.");
      reset();
      onCreated(child);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not apply the operation");
    } finally {
      setBusy(false);
    }
  }

  const select = (label: string, value: string, onChange: (next: string) => void, options = names) => (
    <select aria-label={label} value={value} onChange={(event) => { onChange(event.target.value); reset(); }}>
      {options.map((name) => <option key={name} value={name}>{name}</option>)}
    </select>
  );
  const updateCondition = (index: number, patch: Partial<Condition>) => {
    setConditions((all) => all.map((item, i) => (i === index ? { ...item, ...patch } : item)));
    reset();
  };
  const numericNames = names.filter((name) => numeric.has(name));
  const current = OPERATIONS.find((item) => item.id === operation)!;

  return (
    <ToolSheet
      title="Transform"
      description="Creates a new dataset from this one; this dataset is not changed."
      onClose={onClose}
      testId="transform-panel"
    >
      <div className="dv-chips" role="radiogroup" aria-label="Operation">
        {OPERATIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="radio"
            className="dv-chip"
            aria-checked={operation === item.id}
            onClick={() => { setOperation(item.id); reset(); }}
          >
            {item.label}
          </button>
        ))}
      </div>
      <p className="dv-note">{current.hint}</p>

      {operation === "filter" && (
        <div className="dv-sheet__section">
          {conditions.map((condition, index) => (
            <div key={index} className="dv-row">
              {select(`Condition ${index + 1} variable`, condition.column, (value) => updateCondition(index, { column: value }))}
              <select aria-label={`Condition ${index + 1} operator`} value={condition.op} onChange={(event) => updateCondition(index, { op: event.target.value })}>
                {FILTER_OPS.map(([id, text]) => <option key={id} value={id}>{text}</option>)}
              </select>
              {condition.op !== "is_missing" && condition.op !== "not_missing" && (
                <input aria-label={`Condition ${index + 1} value`} placeholder="value" value={condition.value} size={10} onChange={(event) => updateCondition(index, { value: event.target.value })} />
              )}
              {condition.op === "between" && (
                <input aria-label={`Condition ${index + 1} upper value`} placeholder="and" value={condition.high} size={10} onChange={(event) => updateCondition(index, { high: event.target.value })} />
              )}
              {conditions.length > 1 && (
                <button type="button" className="dv-link" onClick={() => { setConditions((all) => all.filter((_, i) => i !== index)); reset(); }}>Remove</button>
              )}
            </div>
          ))}
          <div>
            <button type="button" className="dv-link" onClick={() => { setConditions((all) => [...all, { column: first, op: "eq", value: "", high: "" }]); reset(); }}>
              + Add a condition
            </button>
          </div>
        </div>
      )}

      {(operation === "keep" || operation === "dedupe") && (
        <div className="dv-chips" role="group" aria-label={operation === "keep" ? "Variables to keep" : "Variables that define a duplicate"}>
          {names.map((name) => (
            <label key={name} className="dv-chip">
              <input type="checkbox" checked={keep.includes(name)} onChange={(event) => { setKeep((all) => (event.target.checked ? [...all, name] : all.filter((item) => item !== name))); reset(); }} />
              {name}
            </label>
          ))}
        </div>
      )}

      {(operation === "recode" || operation === "rename" || operation === "fill" || operation === "compute") && (
        <div className="dv-row">
          <label className="dv-field">
            {operation === "compute" ? "First variable" : "Variable"}
            {select("Variable", column, setColumn, operation === "compute" ? numericNames : names)}
          </label>
          {operation === "compute" && (
            <>
              <label className="dv-field">
                Operation
                <select aria-label="Compute operation" value={computeOp} onChange={(event) => { setComputeOp(event.target.value); reset(); }}>
                  <option value="add">+ add</option>
                  <option value="subtract">− subtract</option>
                  <option value="multiply">× multiply</option>
                  <option value="ratio">÷ divide</option>
                  <option value="log">ln natural log</option>
                </select>
              </label>
              {computeOp !== "log" && (
                <label className="dv-field">
                  Second variable
                  {select("Second variable", second, setSecond, numericNames)}
                </label>
              )}
            </>
          )}
          {operation === "fill" && (
            <>
              <label className="dv-field">
                Replace with
                <select aria-label="Fill strategy" value={fillStrategy} onChange={(event) => { setFillStrategy(event.target.value); reset(); }}>
                  <option value="mean">the mean</option>
                  <option value="median">the median</option>
                  <option value="mode">the most common value</option>
                  <option value="constant">a value</option>
                  <option value="drop_rows">drop those rows</option>
                </select>
              </label>
              {fillStrategy === "constant" && (
                <label className="dv-field">
                  Value
                  <input aria-label="Fill value" value={fillValue} onChange={(event) => { setFillValue(event.target.value); reset(); }} size={10} />
                </label>
              )}
            </>
          )}
          {operation !== "fill" && (
            <label className="dv-field">
              {operation === "rename" ? "New name" : "New variable"}
              <input aria-label={operation === "rename" ? "New name" : "New variable"} value={output} onChange={(event) => { setOutput(event.target.value); reset(); }} size={16} />
            </label>
          )}
        </div>
      )}
      {operation === "recode" && (
        <label className="dv-field">
          Rules
          <textarea
            aria-label="Recode rules"
            value={rulesText}
            onChange={(event) => { setRulesText(event.target.value); reset(); }}
            placeholder={"18..29 = 1\n30..49 = 2\n50..120 = 3\nelse = missing"}
            rows={4}
            cols={32}
          />
        </label>
      )}

      <div className="dv-actions">
        <button type="button" className="dv-button" disabled={busy} onClick={() => void runPreview()}>
          {busy && !preview ? "Previewing…" : "Preview"}
        </button>
        {preview && !preview.blocked && (
          <button type="button" className="dv-button dv-button--primary" disabled={busy} onClick={() => void confirm()}>
            {busy ? "Applying…" : "Apply as new dataset"}
          </button>
        )}
      </div>
      {preview && (
        <div data-testid="transform-preview">
          {preview.blocked ? (
            <p role="alert" className="dv-alert">Blocked: {preview.blocked}</p>
          ) : (
            <p className="dv-result">
              Rows {preview.rowsBefore.toLocaleString("en")} → {preview.rowsAfter.toLocaleString("en")} · {preview.outputColumns.length} variables
              {preview.invalidates.length > 0 && ` · results built on this dataset (${preview.invalidates.join(", ")}) stay tied to the original`}
            </p>
          )}
        </div>
      )}
      {error && <p role="alert" className="dv-alert">{error}</p>}
    </ToolSheet>
  );
}
