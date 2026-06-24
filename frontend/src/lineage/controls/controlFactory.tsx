// frontend/src/lineage/controls/controlFactory.tsx
//
// v1.6.1 (2C.2) — control_factory: the SINGLE entry point that turns an
// `editable_schema` control descriptor into a rendered React control.
//
// Hard constraints (spec §8):
//   - Renders via a REGISTRY lookup (`CONTROL_REGISTRY[kind]`), never a `switch (kind)`.
//     Consumers (OperationSection) call `renderControl(...)` and stay kind-agnostic.
//   - Every EditableControl kind is registered, so a new backend kind can't crash the UI.
//   - `visible_when` is preserved on the descriptor (forward-compat) but NOT enforced day-1.
//   - Day-1 only `select` + `columns` are functional (the data sources are in hand);
//     the rest register structural placeholders (render, but read-only).

import type { ReactElement } from "react";
import type { EditableControl } from "../api/graphViewTypes";

export type ControlChange = (key: string, value: unknown) => void;

export interface ControlProps {
  control: EditableControl;
  onChange: ControlChange;
}

export type ControlKind = EditableControl["kind"];

export const CONTROL_KINDS: readonly ControlKind[] = [
  "select",
  "columns",
  "radio",
  "multiselect",
  "slider",
  "text",
  "textarea",
  "toggle",
] as const;

/** Kinds that are fully interactive day-1; others render read-only placeholders. */
export const ENABLED_CONTROL_KINDS: ReadonlySet<ControlKind> = new Set([
  "select",
  "columns",
]);

// ── option normalisation ───────────────────────────────────────
interface NormOption {
  value: string;
  label: string;
}

function normalizeOptions(control: EditableControl): NormOption[] {
  return (control.options ?? []).map((opt) =>
    typeof opt === "string"
      ? { value: opt, label: opt }
      : { value: String(opt.value), label: opt.label },
  );
}

// ── day-1 functional controls ──────────────────────────────────

function SelectControl({ control, onChange }: ControlProps): ReactElement {
  const options = normalizeOptions(control);
  return (
    <select
      data-testid="control-select"
      aria-label={control.label}
      value={String(control.value ?? "")}
      onChange={(e) => onChange(control.key, e.target.value)}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

function ColumnsControl({ control, onChange }: ControlProps): ReactElement {
  const options = normalizeOptions(control);
  const selected = Array.isArray(control.value)
    ? (control.value as unknown[]).map(String)
    : [];
  const toggle = (value: string) => {
    const next = selected.includes(value)
      ? selected.filter((v) => v !== value)
      : [...selected, value];
    onChange(control.key, next);
  };
  return (
    <fieldset data-testid="control-columns" aria-label={control.label}>
      {options.map((o) => (
        <label key={o.value}>
          <input
            type="checkbox"
            aria-label={o.label}
            checked={selected.includes(o.value)}
            onChange={() => toggle(o.value)}
          />
          {o.label}
        </label>
      ))}
    </fieldset>
  );
}

// ── structural placeholders (registered, read-only until enabled) ──

function makePlaceholder(kind: ControlKind) {
  function Placeholder({ control }: ControlProps): ReactElement {
    return (
      <span data-testid={`control-${kind}`} data-control-kind={kind} aria-disabled="true">
        {control.label}
        {control.value !== undefined ? `: ${String(control.value)}` : ""}
      </span>
    );
  }
  Placeholder.displayName = `PlaceholderControl(${kind})`;
  return Placeholder;
}

// ── registry (NO switch anywhere) ──────────────────────────────

export const CONTROL_REGISTRY: Record<
  ControlKind,
  (props: ControlProps) => ReactElement
> = {
  select: SelectControl,
  columns: ColumnsControl,
  radio: makePlaceholder("radio"),
  multiselect: makePlaceholder("multiselect"),
  slider: makePlaceholder("slider"),
  text: makePlaceholder("text"),
  textarea: makePlaceholder("textarea"),
  toggle: makePlaceholder("toggle"),
};

/** The single render entry point. Looks up the registry by kind — never switches. */
export function renderControl(
  control: EditableControl,
  onChange: ControlChange,
): ReactElement {
  const Control = CONTROL_REGISTRY[control.kind] ?? makePlaceholder(control.kind);
  return <Control control={control} onChange={onChange} />;
}
