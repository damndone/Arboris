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
//   - v1.8.12: the kinds are the backend's (generated). column/integer/number/
//     object/json render as read-only placeholders, as they always did here.

import type { ReactElement } from "react";
import type { EditableControl } from "../api/graphViewTypes";

export type ControlChange = (key: string, value: unknown) => void;

export interface ControlProps {
  control: EditableControl;
  onChange: ControlChange;
}

export type ControlKind = EditableControl["kind"];

/** Every kind the backend emits (generated from its ControlKind). */
export const CONTROL_KINDS: readonly ControlKind[] = [
  "select",
  "multiselect",
  "column",
  "columns",
  "text",
  "integer",
  "number",
  "toggle",
  "object",
  "json",
] as const;

/** Kinds edited in place. The rest (a single column, numbers, structured
 *  values) are shown read-only here; the run form edits them. */
export const ENABLED_CONTROL_KINDS: ReadonlySet<ControlKind> = new Set<ControlKind>([
  "select",
  "multiselect",
  "columns",
  "text",
  "toggle",
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
    <fieldset
      data-testid={testid}
      aria-label={control.label}
      style={{
        border: 0,
        display: "grid",
        gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
        gap: "6px 10px",
        margin: 0,
        maxHeight: 180,
        minWidth: 0,
        overflowY: "auto",
        padding: 0,
      }}
    >
      {options.map((o) => (
        <label
          key={o.value}
          title={o.label}
          style={{
            alignItems: "center",
            color: "var(--label-secondary)",
            display: "flex",
            fontSize: 11,
            fontWeight: 500,
            gap: 6,
            lineHeight: "18px",
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          <input
            type="checkbox"
            aria-label={o.label}
            checked={selected.includes(o.value)}
            onChange={() => toggle(o.value)}
            style={{
              accentColor: "var(--tint)",
              flex: "0 0 auto",
              height: 14,
              margin: 0,
              minHeight: 0,
              padding: 0,
              width: 14,
            }}
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

// ── v1.6.6 interactive controls (toggle/text) ──

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

// ── structural placeholder (fallback only, for unknown backend kinds) ──

function makePlaceholder(kind: ControlKind) {
  function Placeholder({ control }: ControlProps): ReactElement {
    return (
      <span data-testid={`control-${kind}`} data-control-kind={kind} aria-disabled="true">
        {control.label}
        {control.value !== undefined ? `: ${typeof control.value === "object" ? JSON.stringify(control.value) : String(control.value)}` : ""}
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
  multiselect: MultiselectControl,
  column: makePlaceholder("column"),
  columns: ColumnsControl,
  text: TextControl,
  integer: makePlaceholder("integer"),
  number: makePlaceholder("number"),
  toggle: ToggleControl,
  object: makePlaceholder("object"),
  json: makePlaceholder("json"),
};

/** The single render entry point. Looks up the registry by kind — never switches. */
export function renderControl(
  control: EditableControl,
  onChange: ControlChange,
): ReactElement {
  const Control = CONTROL_REGISTRY[control.kind] ?? makePlaceholder(control.kind);
  return <Control control={control} onChange={onChange} />;
}
