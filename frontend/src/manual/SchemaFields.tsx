import { useEffect, useRef, useState } from "react";
export type JsonSchema = {
    type?: string;
    title?: string;
    description?: string;
    enum?: unknown[];
    default?: unknown;
    const?: unknown;
    properties?: Record<string, JsonSchema>;
    required?: string[];
    items?: JsonSchema;
    anyOf?: JsonSchema[];
    oneOf?: JsonSchema[];
    minimum?: number;
    maximum?: number;
    minLength?: number;
    minItems?: number;
    $ref?: string;
    $defs?: Record<string, JsonSchema>;
};
export function initialValue(s: JsonSchema): unknown {
    if (s.default !== undefined)
        return s.default;
    if (s.const !== undefined)
        return s.const;
    if (s.enum?.length === 1)
        return s.enum[0];
    if (s.type === "object")
        return Object.fromEntries((s.required ?? []).flatMap(k => {
            const v = initialValue(s.properties?.[k] ?? {});
            return v === undefined ? [] : [[k, v]];
        }));
    if (s.type === "array")
        return [];
    return undefined;
}
function JsonInput({ label, value, onChange }: {
    label: string;
    value: unknown;
    onChange: (v: unknown) => void;
}) {
    const [text, setText] = useState(value === undefined ? "" : JSON.stringify(value, null, 2));
    const [error, setError] = useState("");
    const input = useRef<HTMLTextAreaElement>(null);
    const serialized = JSON.stringify(value);
    useEffect(() => { setText(value === undefined ? "" : JSON.stringify(value, null, 2)); setError(""); input.current?.setCustomValidity(""); }, [serialized]);
    return <><small>JSON value</small><textarea ref={input} aria-label={label} value={text} rows={4} onChange={e => {
            const next = e.target.value;
            setText(next);
            try {
                onChange(next.trim() ? JSON.parse(next) : undefined);
                setError("");
                e.target.setCustomValidity("");
            }
            catch {
                setError("Enter valid JSON before previewing.");
                e.target.setCustomValidity("Invalid JSON");
            }
        }}/>{error && <span role="alert">{error}</span>}</>;
}
export function SchemaField({ schema, value, onChange, label, required = false, columns = [], root = schema, depth = 0 }: {
    schema: JsonSchema;
    value: unknown;
    onChange: (v: unknown) => void;
    label: string;
    required?: boolean;
    columns?: string[];
    root?: JsonSchema;
    depth?: number;
}) {
    const ref = schema.$ref?.split('/').pop();
    const s = ref && root.$defs?.[ref] ? root.$defs[ref] : schema;
    if (depth > 12)
        return <JsonInput label={label} value={value} onChange={onChange}/>;
    const changeKey = (key: string, v: unknown) => { const next = { ...(value as Record<string, unknown> ?? {}) }; if (v === undefined)
        delete next[key];
    else
        next[key] = v; onChange(next); };
    let control;
    if (s.enum)
        control = <select aria-label={label} required={required} value={value === undefined ? "" : JSON.stringify(value)} onChange={e => onChange(e.target.value === "" ? undefined : JSON.parse(e.target.value))}><option value="">Choose…</option>{s.enum.map(v => <option key={JSON.stringify(v)} value={JSON.stringify(v)}>{String(v)}</option>)}</select>;
    else if (s.type === "object" && s.properties)
        control = <fieldset><legend>{label}</legend>{Object.entries(s.properties).map(([key, child]) => <SchemaField key={key} label={`${label}.${key}`} schema={child} root={root} depth={depth + 1} required={s.required?.includes(key)} columns={columns} value={(value as Record<string, unknown>)?.[key]} onChange={v => changeKey(key, v)}/>)}</fieldset>;
    else if (s.type === "array" && s.items) {
        const items = Array.isArray(value) ? value : [];
        control = <fieldset><legend>{label}</legend>{items.map((v, i) => <div key={i}><SchemaField schema={s.items!} root={root} depth={depth + 1} label={`${label}[${i + 1}]`} value={v} columns={columns} required onChange={next => onChange(items.map((old, j) => i === j ? next : old))}/><button type="button" onClick={() => onChange(items.filter((_, j) => j !== i))}>Remove {label} item {i + 1}</button></div>)}<button type="button" onClick={() => onChange([...items, initialValue(s.items!)])}>Add {label} item</button></fieldset>;
    }
    else if (s.type === "boolean")
        control = <select aria-label={label} value={value === undefined ? "" : String(value)} required={required} onChange={e => onChange(e.target.value === "" ? undefined : e.target.value === "true")}><option value="">Default</option><option value="true">Yes</option><option value="false">No</option></select>;
    else if (s.type === "number" || s.type === "integer")
        control = <input aria-label={label} type="number" step={s.type === "integer" ? 1 : "any"} min={s.minimum} max={s.maximum} required={required} value={value === undefined ? "" : String(value)} onChange={e => onChange(e.target.value === "" ? undefined : Number(e.target.value))}/>;
    else if (s.type === "string")
        control = <><input aria-label={label} required={required} minLength={s.minLength} value={String(value ?? "")} list={`${label}-columns`} onChange={e => onChange(e.target.value || undefined)}/>{columns.length > 0 && <datalist id={`${label}-columns`}>{columns.map(c => <option key={c} value={c}/>)}</datalist>}</>;
    else
        control = <JsonInput label={label} value={value} onChange={onChange}/>;
    return <div className="manual-field">{!(s.properties || s.items) && <label>{label}{required ? " *" : ""}</label>}{control}{s.description && <small>{s.description}</small>}</div>;
}
