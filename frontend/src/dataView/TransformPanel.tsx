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

type Operation = "filter" | "keep" | "recode" | "compute" | "rename" | "dedupe" | "fill";

const OPERATIONS: { id: Operation; label: string }[] = [
  { id: "filter", label: "Select rows" },
  { id: "keep", label: "Keep variables" },
  { id: "recode", label: "Recode into new variable" },
  { id: "compute", label: "Compute new variable" },
  { id: "rename", label: "Rename variable" },
  { id: "dedupe", label: "Remove duplicate rows" },
  { id: "fill", label: "Fill missing values" },
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
}: {
  projectRoot: string;
  runId: string;
  nodeId: string;
  artifactId: string;
  variables: DatasetVariable[];
  onCreated: (childNodeId: string) => void;
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

  return (
    <section data-testid="transform-panel" style={{ fontSize: 12, border: "1px solid var(--separator)", padding: 8, marginBottom: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6, flexWrap: "wrap" }}>
        <strong>Transform</strong>
        <select aria-label="Operation" value={operation} onChange={(event) => { setOperation(event.target.value as Operation); reset(); }}>
          {OPERATIONS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
        <span style={{ color: "var(--label-secondary)" }}>creates a new dataset; this one is not changed</span>
      </div>

      {operation === "filter" && (
        <div>
          {conditions.map((condition, index) => (
            <div key={index} style={{ display: "flex", gap: 6, marginBottom: 4 }}>
              {select(`Condition ${index + 1} variable`, condition.column, (value) => setConditions((all) => all.map((item, i) => (i === index ? { ...item, column: value } : item))))}
              <select aria-label={`Condition ${index + 1} operator`} value={condition.op} onChange={(event) => { setConditions((all) => all.map((item, i) => (i === index ? { ...item, op: event.target.value } : item))); reset(); }}>
                {FILTER_OPS.map(([id, text]) => <option key={id} value={id}>{text}</option>)}
              </select>
              {condition.op !== "is_missing" && condition.op !== "not_missing" && (
                <input aria-label={`Condition ${index + 1} value`} value={condition.value} size={8} onChange={(event) => { setConditions((all) => all.map((item, i) => (i === index ? { ...item, value: event.target.value } : item))); reset(); }} />
              )}
              {condition.op === "between" && (
                <input aria-label={`Condition ${index + 1} upper value`} value={condition.high} size={8} onChange={(event) => { setConditions((all) => all.map((item, i) => (i === index ? { ...item, high: event.target.value } : item))); reset(); }} />
              )}
              {conditions.length > 1 && (
                <button type="button" onClick={() => { setConditions((all) => all.filter((_, i) => i !== index)); reset(); }}>Remove</button>
              )}
            </div>
          ))}
          <button type="button" onClick={() => { setConditions((all) => [...all, { column: first, op: "eq", value: "", high: "" }]); reset(); }}>
            Add condition (all must hold)
          </button>
        </div>
      )}

      {(operation === "keep" || operation === "dedupe") && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <span>{operation === "keep" ? "Keep:" : "Duplicates judged on:"}</span>
          {names.map((name) => (
            <label key={name}>
              <input type="checkbox" checked={keep.includes(name)} onChange={(event) => { setKeep((all) => (event.target.checked ? [...all, name] : all.filter((item) => item !== name))); reset(); }} /> {name}
            </label>
          ))}
        </div>
      )}

      {(operation === "recode" || operation === "rename" || operation === "fill" || operation === "compute") && (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          {select("Variable", column, setColumn, operation === "compute" ? names.filter((name) => numeric.has(name)) : names)}
          {operation === "compute" && (
            <>
              <select aria-label="Compute operation" value={computeOp} onChange={(event) => { setComputeOp(event.target.value); reset(); }}>
                <option value="add">+</option>
                <option value="subtract">−</option>
                <option value="multiply">×</option>
                <option value="ratio">÷</option>
                <option value="log">ln( )</option>
              </select>
              {computeOp !== "log" && select("Second variable", second, setSecond, names.filter((name) => numeric.has(name)))}
            </>
          )}
          {operation === "fill" && (
            <>
              <select aria-label="Fill strategy" value={fillStrategy} onChange={(event) => { setFillStrategy(event.target.value); reset(); }}>
                {["mean", "median", "mode", "constant", "drop_rows"].map((item) => <option key={item} value={item}>{item.replace("_", " ")}</option>)}
              </select>
              {fillStrategy === "constant" && <input aria-label="Fill value" value={fillValue} onChange={(event) => { setFillValue(event.target.value); reset(); }} size={8} />}
            </>
          )}
          {operation !== "fill" && (
            <label>
              {operation === "rename" ? "New name" : "New variable"}{" "}
              <input aria-label={operation === "rename" ? "New name" : "New variable"} value={output} onChange={(event) => { setOutput(event.target.value); reset(); }} size={14} />
            </label>
          )}
        </div>
      )}
      {operation === "recode" && (
        <textarea
          aria-label="Recode rules"
          value={rulesText}
          onChange={(event) => { setRulesText(event.target.value); reset(); }}
          placeholder={"18..29 = 1\n30..49 = 2\n50..120 = 3\nelse = missing"}
          rows={4}
          style={{ display: "block", marginTop: 6, width: 260, fontFamily: "var(--font-mono, monospace)" }}
        />
      )}

      <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
        <button type="button" disabled={busy} onClick={() => void runPreview()}>{busy && !preview ? "Previewing…" : "Preview"}</button>
        {preview && !preview.blocked && (
          <button type="button" disabled={busy} onClick={() => void confirm()}>{busy ? "Applying…" : "Apply as new dataset"}</button>
        )}
      </div>
      {preview && (
        <div data-testid="transform-preview" style={{ marginTop: 6, color: "var(--label-secondary)" }}>
          {preview.blocked ? (
            <span role="alert" style={{ color: "var(--red, #c00)" }}>Blocked: {preview.blocked}</span>
          ) : (
            <>
              Rows {preview.rowsBefore} → {preview.rowsAfter} · {preview.outputColumns.length} variables
              {preview.invalidates.length > 0 && ` · results built on this dataset (${preview.invalidates.join(", ")}) stay tied to the original`}
            </>
          )}
        </div>
      )}
      {error && <div role="alert" style={{ color: "var(--red, #c00)", marginTop: 6 }}>{error}</div>}
    </section>
  );
}
