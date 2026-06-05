// frontend/src/lineage/detail/sections/OperationSection.tsx
//
// V1.5.2 P5 — EditableOps placeholder. Plan §14.
//
// Only renders when `node.editableSchema` is present. V1.5.2 makes no
// partial rerun calls — the schema is treated as read-only metadata
// showing what the ops *will* be editable to in V1.5.3. Submit+rerun
// lands then.

import type {
  EditableControl,
  GraphViewNode,
} from "../../api/graphViewTypes";

export function OperationSection({ node }: { node: GraphViewNode }) {
  const schema = node.editableSchema;
  if (!schema || schema.length === 0) return null;

  return (
    <section
      aria-label="Operation"
      data-testid="operation-section"
      style={{ marginTop: 18 }}
    >
      <div
        className="ln-section-label"
        style={{ marginBottom: 6, display: "flex", alignItems: "center" }}
      >
        <span>Operation</span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            color: "var(--label-tertiary)",
            fontStyle: "italic",
          }}
        >
          Editable in V1.5.3
        </span>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          padding: 10,
          background: "var(--bg-card-2, rgba(255,255,255,0.04))",
          borderRadius: 8,
          fontSize: 12,
        }}
      >
        {schema.map((control) => (
          <ReadOnlyControlRow key={control.key} control={control} />
        ))}
      </div>
    </section>
  );
}

function ReadOnlyControlRow({ control }: { control: EditableControl }) {
  const value =
    typeof control.value === "object"
      ? JSON.stringify(control.value)
      : String(control.value ?? "—");
  return (
    <div
      data-testid={`operation-control-${control.key}`}
      style={{ display: "flex", gap: 8, alignItems: "baseline" }}
    >
      <span
        style={{
          minWidth: 120,
          color: "var(--label-tertiary)",
          fontSize: 11,
        }}
      >
        {control.label}
      </span>
      <span
        style={{
          color: "var(--label)",
          fontFamily: "var(--font-mono, monospace)",
          fontSize: 12,
        }}
      >
        {value}
        {control.unit ? ` ${control.unit}` : ""}
      </span>
    </div>
  );
}
