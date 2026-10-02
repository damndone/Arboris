# Time-Series Graph-Native — Slice A: Operable Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the ARMA-GARCH model node a friendly, time-series-adapted operation form in the graph drawer so a user can fork a child model (change transform / orders / distribution / strategy / validation) without editing raw JSON.

**Architecture:** Add a bespoke `ArmaGarchOperationSection` to the lineage detail drawer that reuses the existing, tested `ArmaGarchControls` component and its `buildArmaGarchModelOptions` converter to emit a `model_options` rerun override. The backend already accepts a `model_options` op-override (`op_contract.validate_overrides` canonicalizes it), and `RerunContext.submitRerun` already forks a child node — so this slice is frontend-only and reuses the existing rerun path. The generic `OperationSection` is suppressed for ARMA-GARCH nodes to avoid a duplicate raw-JSON control.

**Tech Stack:** React + TypeScript (Vitest/RTL), existing lineage drawer `sectionRegistry`, existing `RerunContext`/`NodeOperationContextProvider`, existing `ArmaGarchControls`.

**Scope guard:** This slice does NOT touch the capability `params`/`editable_schema` contract, the backend, or golden snapshots. Result rendering (dashboard) is Slice B; persisted compare node is Slice C; VIXCLS is Slice D.

---

### Task 1: Reverse converter `armaGarchValueFromModelOptions`

Seeds the operation form from the node's current `model_options` so the user edits from the current config. It is the inverse of the existing `buildArmaGarchModelOptions`.

**Files:**
- Modify: `frontend/src/runForm/ArmaGarchControls.tsx` (add + export `armaGarchValueFromModelOptions`)
- Test: `frontend/src/runForm/ArmaGarchControls.roundtrip.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, expect, test } from "vitest";
import {
  buildArmaGarchModelOptions,
  createDefaultArmaGarchValue,
  armaGarchValueFromModelOptions,
} from "./ArmaGarchControls";

describe("armaGarchValueFromModelOptions", () => {
  test("round-trips a manual GARCH config through model_options", () => {
    const original = {
      ...createDefaultArmaGarchValue(),
      valueColumn: "vixcls",
      timeColumn: "observation_date",
      transform: "log_return_pct" as const,
      selectionMode: "manual" as const,
      armaP: 1,
      armaQ: 1,
      constantMode: "exclude" as const,
      varianceModel: "garch" as const,
      garchP: 1,
      garchQ: 1,
      estimationStrategy: "sequential" as const,
      innovationDistribution: "normal" as const,
      validationN: 250,
    };
    const options = buildArmaGarchModelOptions(original);
    const restored = armaGarchValueFromModelOptions(options, createDefaultArmaGarchValue());
    expect(buildArmaGarchModelOptions(restored)).toEqual(options);
  });

  test("falls back to defaults for absent fields", () => {
    const base = createDefaultArmaGarchValue();
    const restored = armaGarchValueFromModelOptions({}, base);
    expect(restored.transform).toBe(base.transform);
    expect(restored.selectionMode).toBe(base.selectionMode);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/runForm/ArmaGarchControls.roundtrip.test.tsx`
Expected: FAIL — `armaGarchValueFromModelOptions` is not exported.

- [ ] **Step 3: Implement the converter**

Add to `frontend/src/runForm/ArmaGarchControls.tsx` (mirror the exact field names produced by `buildArmaGarchModelOptions`; read that function first and invert each field). Skeleton:

```tsx
export function armaGarchValueFromModelOptions(
  options: Record<string, unknown>,
  base: ArmaGarchControlValue,
): ArmaGarchControlValue {
  const arma = (options.arma ?? {}) as Record<string, unknown>;
  const variance = (options.variance ?? {}) as Record<string, unknown>;
  const validation = (options.validation ?? {}) as Record<string, unknown>;
  const pick = <T,>(v: unknown, fallback: T): T => (v == null ? fallback : (v as T));
  return {
    ...base,
    timeColumn: pick(options.time_column, base.timeColumn),
    valueColumn: pick(options.value_column, base.valueColumn),
    timeSemantics: pick(options.time_index_semantics, base.timeSemantics),
    transform: pick(options.transform, base.transform),
    selectionMode: pick(options.selection_mode, base.selectionMode),
    armaP: pick(arma.p, base.armaP),
    armaQ: pick(arma.q, base.armaQ),
    constantMode: pick(arma.constant_mode, base.constantMode),
    varianceModel: pick(variance.model, base.varianceModel),
    archP: pick(variance.arch_p, base.archP),
    garchP: pick(variance.garch_p, base.garchP),
    garchQ: pick(variance.garch_q, base.garchQ),
    estimationStrategy: pick(options.estimation_strategy, base.estimationStrategy),
    innovationDistribution: pick(options.innovation_distribution, base.innovationDistribution),
    validationN: pick(validation.validation_n, base.validationN),
  };
}
```

Adjust every key to match `buildArmaGarchModelOptions`'s real output shape (read it in the same file). If a field name differs, the round-trip test will catch it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/runForm/ArmaGarchControls.roundtrip.test.tsx`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runForm/ArmaGarchControls.tsx frontend/src/runForm/ArmaGarchControls.roundtrip.test.tsx
git commit -m "feat(ts-graph): add armaGarchValueFromModelOptions inverse converter"
```

---

### Task 2: `ArmaGarchOperationSection` component

Renders the friendly rerun form in the drawer and forks a child via the existing rerun path.

**Files:**
- Create: `frontend/src/lineage/detail/sections/ArmaGarchOperationSection.tsx`
- Test: `frontend/src/lineage/detail/sections/ArmaGarchOperationSection.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { describe, expect, test, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ArmaGarchOperationSection } from "./ArmaGarchOperationSection";
import { RerunContext } from "../RerunContext";

const node = {
  kind: "model",
  stage: "model",
  title: "ARMA(1,1)-GARCH(1,1)",
  modelType: "time_series.arma_garch",
  modelOptions: { time_column: "observation_date", value_column: "vixcls" },
  runs: [],
} as never;

test("submits a model_options rerun override when a field changes", async () => {
  const submitRerun = vi.fn().mockResolvedValue({ focus: {} });
  render(
    <RerunContext.Provider value={{ submitRerun }}>
      <ArmaGarchOperationSection node={node} />
    </RerunContext.Provider>,
  );
  fireEvent.change(screen.getByLabelText("innovation distribution"), {
    target: { value: "student_t" },
  });
  fireEvent.click(screen.getByTestId("arma-garch-op-submit"));
  expect(submitRerun).toHaveBeenCalledTimes(1);
  const arg = submitRerun.mock.calls[0][0];
  expect(arg.opOverrides.model_options.innovation_distribution).toBe("student_t");
});
```

(Provide whatever `NodeOperationContextProvider` value `useResolvedNodeOperationContext` requires — read `ArmaGarchOperationSection` peers `OperationSection.test.tsx` for the exact test harness/mocks and reuse them.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lineage/detail/sections/ArmaGarchOperationSection.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

```tsx
import { useMemo, useState } from "react";
import type { GraphViewNode } from "../../api/graphViewTypes";
import { useRerun } from "../RerunContext";
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import {
  ArmaGarchControls,
  armaGarchValidationErrors,
  armaGarchValueFromModelOptions,
  buildArmaGarchModelOptions,
  createDefaultArmaGarchValue,
  type ArmaGarchControlValue,
} from "../../../runForm/ArmaGarchControls";

export function ArmaGarchOperationSection({ node }: { node: GraphViewNode }) {
  const rerun = useRerun();
  const resolved = useResolvedNodeOperationContext();
  const currentOptions =
    "modelOptions" in node && node.modelOptions ? (node.modelOptions as Record<string, unknown>) : {};
  const initial = useMemo(
    () => armaGarchValueFromModelOptions(currentOptions, createDefaultArmaGarchValue()),
    [currentOptions],
  );
  const [value, setValue] = useState<ArmaGarchControlValue>(initial);
  const [status, setStatus] = useState<"idle" | "submitting" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  if (!rerun || !resolved || !resolved.ok) return null;
  const errors = armaGarchValidationErrors(value);
  const dirty = JSON.stringify(value) !== JSON.stringify(initial);

  const onSubmit = async () => {
    setStatus("submitting");
    setError(null);
    try {
      await rerun.submitRerun({
        context: resolved.context,
        opOverrides: { model_options: buildArmaGarchModelOptions(value) },
      });
      setStatus("done");
    } catch (e) {
      setStatus("error");
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section aria-label="ARMA-GARCH operation" data-testid="arma-garch-operation-section" style={{ marginTop: 18 }}>
      <div className="ln-section-label" style={{ marginBottom: 6 }}>Operation</div>
      <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 8 }}>
        The current run stays unchanged. Confirming forks a new child model.
      </div>
      <ArmaGarchControls value={value} onChange={setValue} />
      <button
        type="button"
        data-testid="arma-garch-op-submit"
        disabled={!dirty || errors.length > 0 || status === "submitting"}
        onClick={onSubmit}
      >
        {status === "submitting" ? "Forking child…" : "Rerun as new child model"}
      </button>
      {status === "done" && <span data-testid="arma-garch-op-done"> Branch created</span>}
      {status === "error" && <span data-testid="arma-garch-op-error"> {error}</span>}
    </section>
  );
}
```

If `ArmaGarchControls` requires props beyond `value`/`onChange` (e.g. a column list), pass the node's known columns or an empty list; read the `Props` type at the top of `ArmaGarchControls.tsx` and supply exactly those.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lineage/detail/sections/ArmaGarchOperationSection.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/detail/sections/ArmaGarchOperationSection.tsx frontend/src/lineage/detail/sections/ArmaGarchOperationSection.test.tsx
git commit -m "feat(ts-graph): bespoke ARMA-GARCH node operation section"
```

---

### Task 3: Register the section and suppress the generic operation for ARMA-GARCH

**Files:**
- Modify: `frontend/src/workbench/registry/sectionRegistry.ts`
- Test: `frontend/src/workbench/registry/sectionRegistry.test.ts` (extend if present; else create)

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, test } from "vitest";
import { sectionRegistry } from "./sectionRegistry";

const tsModelNode = { kind: "model", stage: "model", isDraft: false, modelType: "time_series.arma_garch", editableSchema: [{ key: "model_options" }], decisions: [], trust: "ok", runs: [] } as never;
const olsModelNode = { kind: "model", stage: "model", isDraft: false, modelType: "ols", editableSchema: [{ key: "x" }], decisions: [], trust: "ok", runs: [] } as never;

test("ARMA-GARCH model node shows the bespoke operation, not the generic one", () => {
  const ids = sectionRegistry.filter((s) => s.shouldRender(tsModelNode)).map((s) => s.id);
  expect(ids).toContain("armaGarchOperation");
  expect(ids).not.toContain("operation");
});

test("OLS model node still shows the generic operation", () => {
  const ids = sectionRegistry.filter((s) => s.shouldRender(olsModelNode)).map((s) => s.id);
  expect(ids).toContain("operation");
  expect(ids).not.toContain("armaGarchOperation");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/workbench/registry/sectionRegistry.test.ts`
Expected: FAIL — no `armaGarchOperation` entry; generic `operation` renders for the TS node.

- [ ] **Step 3: Wire the registry**

In `frontend/src/workbench/registry/sectionRegistry.ts`:

1. Import: `import { ArmaGarchOperationSection } from "../../lineage/detail/sections/ArmaGarchOperationSection";`
2. Add a helper: `const isArmaGarch = (n: GraphViewNode) => "modelType" in n && n.modelType === "time_series.arma_garch";`
3. Change the generic `operation` entry's `shouldRender` to exclude ARMA-GARCH:
   `shouldRender: (n) => (n.editableSchema?.length ?? 0) > 0 && !isArmaGarch(n),`
4. Add a new entry (order 31, right after `operation`):
   ```ts
   {
     id: "armaGarchOperation",
     order: 31,
     shouldRender: (n) => (n.kind === "model" || n.stage === "model") && !n.isDraft && isArmaGarch(n),
     Component: ArmaGarchOperationSection,
   },
   ```

Confirm `GraphViewNode` carries `modelType`; if the field has a different name (e.g. `model_type`), use that name consistently in Task 2 and here.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/workbench/registry/sectionRegistry.test.ts`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workbench/registry/sectionRegistry.ts frontend/src/workbench/registry/sectionRegistry.test.ts
git commit -m "feat(ts-graph): route ARMA-GARCH nodes to the bespoke operation section"
```

---

### Task 4: Gate — typecheck + full frontend suite

- [ ] **Step 1: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (no errors).

- [ ] **Step 2: Full frontend suite**

Run: `cd frontend && npm test -- --run`
Expected: all pass (existing 1227 + the new tests).

- [ ] **Step 3: Commit (if any incidental fixes were needed)**

```bash
git add -A && git commit -m "test(ts-graph): slice A green — operable ARMA-GARCH node"
```

---

## Self-review

- **Spec coverage:** Implements spec §7 (structured, graph-native operation for the pack via a bespoke section) and the "nodes can't do time-series operations" problem in §2.2. Result dashboard (§6), compare node (§8), Table/Overview (§10–11), VIXCLS (§12) are explicitly deferred to Slices B/C/D.
- **Placeholder scan:** Steps carry real code; the two "read the peer/Props and match names" notes are verification instructions, not deferred work — the round-trip test (Task 1) and registry test (Task 3) fail loudly if a name is wrong.
- **Type consistency:** `ArmaGarchControlValue`, `buildArmaGarchModelOptions`, `armaGarchValidationErrors`, `createDefaultArmaGarchValue` are the real exports; `armaGarchValueFromModelOptions` is added in Task 1 and consumed in Task 2; `submitRerun({context, opOverrides})` matches `RerunArgs`; `sectionRegistry` entry shape matches existing entries.
- **Risk:** lowest of the four slices — frontend-only, no backend/contract/golden changes, reuses the tested rerun path.
