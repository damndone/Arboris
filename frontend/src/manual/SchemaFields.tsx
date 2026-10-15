// A form for any declared operation, generated from its JSON schema, so the
// manual path covers every operation without a hand-written form and nobody
// types JSON. Labels read as words ("column_bindings" → "Column bindings"); a
// field with a single allowed value is not a decision and is not shown; a list
// of names is edited as chips, with the dataset's columns one click away.
// Numerical validation stays with the server.

import { useId, useState, type KeyboardEvent } from "react";
import { resolveSchema, seedValue, validateValue, valueType, variants, type JsonSchema } from "./schemaModel";
export { initialValue, type JsonSchema } from "./schemaModel";

type Props = {
  schema: JsonSchema;
  value: unknown;
  onChange: (value: unknown) => void;
  label: string;
  required?: boolean;
  columns?: string[];
  root?: JsonSchema;
  depth?: number;
  /** The outermost object of a step: its fields without a frame of their own. */
  flat?: boolean;
};

const anyTypes: JsonSchema[] = [
  { type: "string", title: "Text" },
  { type: "number", title: "Number" },
  { type: "boolean", title: "Yes / No" },
  { type: "null", title: "Missing (null)" },
  { type: "array", title: "List" },
  { type: "object", title: "Fields" },
];

const TYPE_NAMES: Record<string, string> = {
  string: "Text",
  number: "Number",
  integer: "Whole number",
  boolean: "Yes / No",
  null: "Missing (null)",
  array: "List",
  object: "Fields",
};

/** "Step 1.column_bindings" → "Column bindings"; "Step 1.rules[2]" → "Rules 2". */
export function caption(label: string, schema: JsonSchema): string {
  if (schema.title) return schema.title;
  const last = label.split(".").pop() ?? label;
  const words = last.replace(/\[(\d+)\]/g, " $1").replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : label;
}

const mark = (required?: boolean) => (required ? " *" : "");

/** A required field with exactly one allowed value carries no choice. */
function settled(schema: JsonSchema): boolean {
  return schema.const !== undefined || schema.enum?.length === 1;
}

function variantName(branch: JsonSchema, index: number): string {
  if (branch.title) return branch.title;
  if (branch.const !== undefined) return String(branch.const);
  if (branch.enum) return branch.enum.map(String).join(" / ");
  if (typeof branch.type === "string") return TYPE_NAMES[branch.type] ?? branch.type;
  return `Variant ${index + 1}`;
}

function VariantField({ branches, ...props }: Props & { branches: JsonSchema[] }) {
  const root = props.root ?? props.schema;
  const [selected, setSelected] = useState<number | null>(null);
  const resolved = branches.map((branch) => resolveSchema(branch, root));
  const exact = props.value === undefined ? -1 : resolved.findIndex((branch) => validateValue(branch, props.value, root).length === 0);
  const shape = resolved.findIndex(
    (branch) => branch.type === valueType(props.value) || (branch.type === "integer" && typeof props.value === "number"),
  );
  const index = exact >= 0 ? exact : selected ?? (shape >= 0 ? shape : -1);
  return (
    <fieldset>
      <legend>{caption(props.label, props.schema)}{mark(props.required)}</legend>
      <label className="manual-field">
        Value type
        <select
          aria-label={`${props.label} value type`}
          value={index}
          onChange={(event) => {
            const next = Number(event.target.value);
            setSelected(next);
            props.onChange(seedValue(resolved[next], root));
          }}
        >
          <option value={-1} disabled>Choose a value type…</option>
          {resolved.map((branch, i) => (
            <option key={i} value={i}>{variantName(branch, i)}</option>
          ))}
        </select>
      </label>
      {index >= 0 && <FieldControl key={index} {...props} schema={resolved[index]} required />}
    </fieldset>
  );
}

function ObjectField(props: Props) {
  const { schema, value, onChange, label, flat } = props;
  const root = props.root ?? schema;
  const record = value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
  const [keyDraft, setKeyDraft] = useState("");
  const properties = schema.properties ?? {};
  const known = (key: string) => Object.prototype.hasOwnProperty.call(properties, key);
  const present = (key: string) => Object.prototype.hasOwnProperty.call(record, key);
  const update = (key: string, next: unknown) => onChange({ ...record, [key]: next });
  const remove = (key: string) => onChange(Object.fromEntries(Object.entries(record).filter(([name]) => name !== key)));
  const optional = Object.keys(properties).filter((key) => !schema.required?.includes(key) && !present(key));
  const keys = [...new Set([...(schema.required ?? []), ...Object.keys(record)])].filter(
    (key) => !(known(key) && schema.required?.includes(key) && settled(resolveSchema(properties[key], root))),
  );
  const extraSchema = typeof schema.additionalProperties === "object" ? schema.additionalProperties : {};
  const extraAllowed = schema.additionalProperties !== false;
  const body = (
    <>
      {keys.map((key) => (
        <div key={key} className="manual-object-row">
          <SchemaField
            {...props}
            flat={false}
            depth={(props.depth ?? 0) + 1}
            schema={known(key) ? properties[key] : extraSchema}
            value={record[key]}
            label={`${label}.${key}`}
            required
            onChange={(next) => update(key, next)}
          />
          {!schema.required?.includes(key) && (
            <button type="button" className="manual-remove" onClick={() => remove(key)} aria-label={`Remove ${label}.${key}`}>
              Remove field
            </button>
          )}
        </div>
      ))}
      {optional.length > 0 && (
        <label className="manual-field manual-add">
          Add a setting
          <select
            aria-label={`${label} optional field`}
            value=""
            onChange={(event) => {
              const key = event.target.value;
              if (key) update(key, seedValue(properties[key], root));
            }}
          >
            <option value="">Choose…</option>
            {optional.map((key) => (
              <option key={key} value={key}>{caption(key, properties[key])}</option>
            ))}
          </select>
        </label>
      )}
      {extraAllowed && (
        <div className="manual-map-add">
          <label className="manual-field">
            Field name
            <input aria-label={`${label} new field name`} value={keyDraft} onChange={(event) => setKeyDraft(event.target.value)} />
          </label>
          <button
            type="button"
            disabled={!keyDraft.trim() || present(keyDraft) || known(keyDraft)}
            onClick={() => {
              update(keyDraft, seedValue(extraSchema, root));
              setKeyDraft("");
            }}
            aria-label={`Add ${label} field`}
          >
            Add field
          </button>
          {(present(keyDraft) || known(keyDraft)) && <small role="alert">This field already exists or is declared above.</small>}
        </div>
      )}
      {!keys.length && !optional.length && !extraAllowed && <small>Nothing to set.</small>}
    </>
  );
  if (flat) return <div className="manual-object">{body}</div>;
  return (
    <fieldset>
      <legend>{caption(label, schema)}{mark(props.required)}</legend>
      {body}
    </fieldset>
  );
}

/** A list of names (columns, levels, labels) as chips. */
function ChipsField(props: Props) {
  const { schema, value, onChange, label, columns = [] } = props;
  const id = useId();
  const items = Array.isArray(value) ? (value as string[]) : [];
  const [draft, setDraft] = useState("");
  const full = schema.maxItems !== undefined && items.length >= schema.maxItems;
  const add = (name: string) => {
    const next = name.trim();
    if (!next || full || (schema.uniqueItems !== false && items.includes(next))) return;
    onChange([...items, next]);
    setDraft("");
  };
  const toggle = (name: string) => (items.includes(name) ? onChange(items.filter((item) => item !== name)) : add(name));
  const onKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      add(draft);
    } else if (event.key === "Backspace" && !draft && items.length) {
      onChange(items.slice(0, -1));
    }
  };
  return (
    <fieldset className="manual-chips">
      <legend>{caption(label, schema)}{mark(props.required)}</legend>
      <div className="manual-chips__box">
        {items.map((item, index) => (
          <span key={`${item}:${index}`} className="manual-chip">
            {item}
            <button type="button" aria-label={`Remove ${label} item ${index + 1}`} onClick={() => onChange(items.filter((_, i) => i !== index))}>
              ×
            </button>
          </span>
        ))}
        <input
          aria-label={`${label} new item`}
          list={columns.length ? id : undefined}
          value={draft}
          disabled={full}
          placeholder={items.length ? "" : columns.length ? "Type or pick a column" : "Type a value, then Enter"}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKey}
          onBlur={() => add(draft)}
        />
        {columns.length > 0 && (
          <datalist id={id}>
            {columns.map((column) => <option key={column} value={column} />)}
          </datalist>
        )}
      </div>
      {schema.minItems !== undefined && schema.minItems > 0 && <small>At least {schema.minItems}</small>}
      {columns.length > 0 && columns.length <= 40 && (
        <div className="manual-chips__columns" role="group" aria-label={`Columns in this dataset for ${caption(label, schema)}`}>
          {columns.map((column) => (
            <button key={column} type="button" aria-pressed={items.includes(column)} disabled={full && !items.includes(column)} onClick={() => toggle(column)}>
              {column}
            </button>
          ))}
        </div>
      )}
    </fieldset>
  );
}

function ArrayField(props: Props) {
  const { schema, value, onChange, label } = props;
  const items = Array.isArray(value) ? value : [];
  const move = (index: number, delta: number) => {
    const next = [...items];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    onChange(next);
  };
  return (
    <fieldset>
      <legend>{caption(label, schema)}{mark(props.required)}</legend>
      {schema.minItems !== undefined && <small>At least {schema.minItems}</small>}
      {items.map((item, index) => (
        <div key={index} className="manual-array-row">
          <SchemaField
            {...props}
            depth={(props.depth ?? 0) + 1}
            schema={schema.items ?? {}}
            value={item}
            label={`${label}[${index + 1}]`}
            required
            onChange={(next) => onChange(items.map((v, i) => (i === index ? next : v)))}
          />
          <div className="manual-actions">
            <button type="button" disabled={index === 0} onClick={() => move(index, -1)} aria-label={`Move ${label} item ${index + 1} up`}>
              Move up
            </button>
            <button type="button" disabled={index === items.length - 1} onClick={() => move(index, 1)} aria-label={`Move ${label} item ${index + 1} down`}>
              Move down
            </button>
            <button type="button" onClick={() => onChange(items.filter((_, i) => i !== index))} aria-label={`Remove ${label} item ${index + 1}`}>
              Remove item
            </button>
          </div>
        </div>
      ))}
      <button
        type="button"
        disabled={schema.maxItems !== undefined && items.length >= schema.maxItems}
        onClick={() => onChange([...items, seedValue(schema.items ?? {}, props.root ?? schema)])}
        aria-label={`Add ${label} item`}
      >
        Add item
      </button>
    </fieldset>
  );
}

function isNameList(schema: JsonSchema, root: JsonSchema): boolean {
  if (schema.type !== "array" || !schema.items) return false;
  const items = resolveSchema(schema.items, root);
  return items.type === "string" && !items.enum && !variants(items);
}

function FieldControl(props: Props) {
  const { schema: s, value, onChange, label, required, columns = [] } = props;
  const id = useId();
  const root = props.root ?? s;
  const name = caption(label, s);
  const branches = variants(s);
  if (branches) return <VariantField {...props} branches={branches} />;
  if (s.const !== undefined) return <p>{name}: <strong>{String(s.const)}</strong></p>;
  if (s.enum) {
    return (
      <label className="manual-field">
        {name}{mark(required)}
        <select
          aria-label={label}
          required={required}
          value={value === undefined ? "" : JSON.stringify(value)}
          onChange={(event) => onChange(event.target.value === "" ? undefined : JSON.parse(event.target.value))}
        >
          <option value="">Choose…</option>
          {s.enum.map((v) => <option key={JSON.stringify(v)} value={JSON.stringify(v)}>{String(v)}</option>)}
        </select>
      </label>
    );
  }
  if (s.type === "object" || s.properties) return <ObjectField {...props} />;
  if (isNameList(s, root)) return <ChipsField {...props} />;
  if (s.type === "array") return <ArrayField {...props} />;
  if (s.type === "null") return <p>{name}: Missing (null)</p>;
  if (s.type === "boolean") {
    return (
      <label className="manual-field">
        {name}
        <select
          aria-label={label}
          required={required}
          value={value === undefined ? "" : String(value)}
          onChange={(event) => onChange(event.target.value === "" ? undefined : event.target.value === "true")}
        >
          <option value="">Choose…</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </label>
    );
  }
  if (s.type === "number" || s.type === "integer") {
    return (
      <label className="manual-field">
        {name}{mark(required)}
        <input
          aria-label={label}
          type="number"
          step={s.type === "integer" ? 1 : "any"}
          min={s.minimum}
          max={s.maximum}
          required={required}
          value={value === undefined ? "" : String(value)}
          onChange={(event) => onChange(event.target.value === "" ? undefined : Number(event.target.value))}
        />
      </label>
    );
  }
  if (s.type === "string") {
    return (
      <label className="manual-field">
        {name}{mark(required)}
        <input
          aria-label={label}
          required={required}
          minLength={s.minLength}
          maxLength={s.maxLength}
          value={String(value ?? "")}
          list={columns.length ? id : undefined}
          onChange={(event) => onChange(event.target.value)}
        />
        {columns.length > 0 && <datalist id={id}>{columns.map((c) => <option key={c} value={c} />)}</datalist>}
      </label>
    );
  }
  return <VariantField {...props} branches={anyTypes} />;
}

export function SchemaField({ root, depth = 0, ...props }: Props) {
  const base = root ?? props.schema;
  let schema: JsonSchema;
  try {
    schema = resolveSchema(props.schema, base);
  } catch (error) {
    return <p role="alert">{String(error)}</p>;
  }
  if (depth > 30) return <p role="alert">{props.label}: nesting exceeds the supported form depth.</p>;
  return (
    <div className="manual-field">
      <FieldControl {...props} schema={schema} root={base} depth={depth} />
      {schema.description && !props.flat && <small>{schema.description}</small>}
    </div>
  );
}
