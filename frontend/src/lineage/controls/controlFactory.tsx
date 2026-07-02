// frontend/src/lineage/controls/controlFactory.tsx
//
// v1.6.1 (2C.2) — control_factory: the SINGLE entry point that turns an
// `editable_schema` control descriptor into a rendered React control.
//
// Hard constraints (spec §8):
//   - Renders via a REGISTRY lookup (`CONTROL_REGISTRY[kind]`), never a `switch (kind)`.
//     Consumers (OperationSection) call `renderControl(...)` and stay kind-agnostic.
//   - Every EditableControl kind is registered, so a new backend kind can't crash the UI.
//   - `visible_when` is preserved on the descriptor (forward-compat) but NOT enforced.
//   - v1.6.6: ALL kinds are now interactive. `makePlaceholder` survives only as the
//     defensive fallback for an unrecognised backend kind (so a new kind can't crash).

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

/** Kinds that are fully interactive. v1.6.6 promoted the remaining five
 *  (radio/slider/text/textarea/toggle) from read-only placeholders, so every
 *  kind is now interactive — the set equals CONTROL_KINDS. */
export const ENABLED_CONTROL_KINDS: ReadonlySet<ControlKind> = new Set(
  CONTROL_KINDS,
);

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

/** Shared checkbox-list control body. `columns` and `multiselect` are the
 *  same interaction (toggle membership in a string[] value); they differ only
 *  in semantic intent and test id. */
function CheckboxListControl(
  { control, onChange }: ControlProps,
  testid: string,
): ReactElement {
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
    <fieldset data-testid={testid} aria-label={control.label}>
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

function ColumnsControl(props: ControlProps): ReactElement {
  return CheckboxListControl(props, "control-columns");
}

// v1.6.5 — multiselect is now functional (role layer focal_x picker). Same
// checkbox-list interaction as `columns`, distinct test id / intent.
function MultiselectControl(props: ControlProps): ReactElement {
  return CheckboxListControl(props, "control-multiselect");
}

// ── v1.6.6 interactive controls (radio/toggle/slider/text/textarea) ──

function RadioControl({ control, onChange }: ControlProps): ReactElement {
  const options = normalizeOptions(control);
  const current = String(control.value ?? "");
  return (
    <fieldset data-testid="control-radio" aria-label={control.label}>
      {options.map((o) => (
        <label key={o.value}>
          <input
            type="radio"
            name={control.key}
            aria-label={o.label}
            checked={current === o.value}
            onChange={() => onChange(control.key, o.value)}
          />
          {o.label}
        </label>
      ))}
    </fieldset>
  );
}

function ToggleControl({ control, onChange }: ControlProps): ReactElement {
  const checked = control.value === true;
  return (
    <input
      type="checkbox"
      role="checkbox"
      data-testid="control-toggle"
      aria-label={control.label}
      checked={checked}
      onChange={() => onChange(control.key, !checked)}
    />
  );
}

function SliderControl({ control, onChange }: ControlProps): ReactElement {
  const value = control.value === undefined ? "" : String(control.value);
  return (
    <input
      type="range"
      data-testid="control-slider"
      aria-label={control.label}
      value={value}
      min={control.min}
      max={control.max}
      step={control.step}
      onChange={(e) => onChange(control.key, Number(e.target.value))}
    />
  );
}

function TextControl({ control, onChange }: ControlProps): ReactElement {
  return (
    <input
      type="text"
      data-testid="control-text"
      aria-label={control.label}
      value={String(control.value ?? "")}
      onChange={(e) => onChange(control.key, e.target.value)}
    />
  );
}

function TextareaControl({ control, onChange }: ControlProps): ReactElement {
  return (
    <textarea
      data-testid="control-textarea"
      aria-label={control.label}
      value={String(control.value ?? "")}
      onChange={(e) => onChange(control.key, e.target.value)}
    />
  );
}

// ── structural placeholder (fallback only, for unknown backend kinds) ──

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
  radio: RadioControl,
  multiselect: MultiselectControl,
  slider: SliderControl,
  text: TextControl,
  textarea: TextareaControl,
  toggle: ToggleControl,
};

/** The single render entry point. Looks up the registry by kind — never switches. */
export function renderControl(
  control: EditableControl,
  onChange: ControlChange,
): ReactElement {
  const Control = CONTROL_REGISTRY[control.kind] ?? makePlaceholder(control.kind);
  return <Control control={control} onChange={onChange} />;
}
