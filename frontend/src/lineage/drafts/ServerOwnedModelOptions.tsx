import type { ReactElement } from "react";

export type ServerOwnedSchemaProperty = {
  type?: "string" | "integer" | "number" | "boolean" | "array" | "object";
  enum?: unknown[];
  column_options?: string[];
  minimum?: number;
  maximum?: number;
  nullable?: boolean;
  server_owned?: boolean;
  required?: string[];
  properties?: Record<string, ServerOwnedSchemaProperty>;
  items?: ServerOwnedSchemaProperty;
};

export type ServerOwnedObjectSchema = {
  type: "object";
  required?: string[];
  properties?: Record<string, ServerOwnedSchemaProperty>;
  additionalProperties?: boolean;
};

export type ServerOwnedObjectControl = {
  key: string;
  kind: "object";
  label?: string;
  required?: boolean;
  value?: unknown;
  schema?: ServerOwnedObjectSchema;
};

type Props = {
  control: ServerOwnedObjectControl;
  value: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  disabled?: boolean;
};

function isNullAllowed(property: ServerOwnedSchemaProperty): boolean {
  return property.nullable === true
    || (Array.isArray(property.enum) && property.enum.some((value) => value === null));
}

function isPresent(property: ServerOwnedSchemaProperty | undefined, value: unknown): boolean {
  if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {
    return false;
  }
  return value !== null || Boolean(property && isNullAllowed(property));
}

function isObjectComplete(
  schema: ServerOwnedObjectSchema | ServerOwnedSchemaProperty,
  value: Record<string, unknown>,
): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const properties = schema.properties ?? {};
  return (schema.required ?? []).every((key) => {
    const property = properties[key];
    // A server-owned field is filled by the Draft boundary from the pinned
    // source. It is deliberately not a client completion condition.
    if (property?.server_owned) return true;
    if (!isPresent(property, value[key])) return false;
    if (property?.type === "object" || property?.properties) {
      return isObjectComplete(property, value[key] as Record<string, unknown>);
    }
    return true;
  });
}

export function isServerOwnedObjectComplete(
  control: ServerOwnedObjectControl,
  value: Record<string, unknown>,
): boolean {
  if (!control.required) return true;
  return Boolean(control.schema && isObjectComplete(control.schema, value));
}

function encodeOption(value: unknown): string {
  if (value === null) return "__server_null__";
  return JSON.stringify(value);
}

function decodeOption(value: string, options: unknown[]): unknown {
  if (value === "__server_null__") return null;
  const parsed = JSON.parse(value) as unknown;
  return options.find((option) => Object.is(option, parsed)) ?? parsed;
}

function displayOption(value: unknown): string {
  if (value === null) return "(none)";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function PropertyEditor({
  name,
  property,
  value,
  onChange,
  disabled,
}: {
  name: string;
  property: ServerOwnedSchemaProperty;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled?: boolean;
}): ReactElement {
  if (property.server_owned) {
    return <span className="ios-hint">{value == null ? "(server bound)" : String(value)}</span>;
  }

  if (property.type === "object" || property.properties) {
    const nestedValue = value && typeof value === "object" && !Array.isArray(value)
      ? value as Record<string, unknown>
      : {};
    return (
      <fieldset className="ios-group" style={{ marginTop: 8 }}>
        <legend>{name}</legend>
        <ObjectProperties
          schema={property}
          value={nestedValue}
          onChange={(key, next) => onChange({ ...nestedValue, [key]: next })}
          disabled={disabled}
        />
      </fieldset>
    );
  }

  const enumValues = Array.isArray(property.enum) ? property.enum : null;
  if (enumValues) {
    const encoded = value === undefined ? "" : encodeOption(value);
    return (
      <select
        aria-label={name}
        value={encoded}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value === "" ? undefined : decodeOption(event.target.value, enumValues))}
      >
        <option value="">(select)</option>
        {enumValues.map((option) => (
          <option key={encodeOption(option)} value={encodeOption(option)}>
            {displayOption(option)}
          </option>
        ))}
      </select>
    );
  }

  if (Array.isArray(property.column_options)) {
    return (
      <select
        aria-label={name}
        value={typeof value === "string" ? value : ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value || undefined)}
      >
        <option value="">(select column)</option>
        {property.column_options.map((column) => (
          <option key={column} value={column}>
            {column}
          </option>
        ))}
      </select>
    );
  }

  if (property.type === "boolean") {
    return (
      <input
        aria-label={name}
        type="checkbox"
        checked={value === true}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
    );
  }

  if (property.type === "integer" || property.type === "number") {
    return (
      <input
        aria-label={name}
        type="number"
        min={property.minimum}
        max={property.maximum}
        step={property.type === "integer" ? 1 : "any"}
        value={typeof value === "number" ? String(value) : typeof value === "string" ? value : ""}
        disabled={disabled}
        onChange={(event) => {
          const raw = event.target.value;
          if (raw === "") {
            onChange("");
            return;
          }
          const parsed = Number(raw);
          onChange(Number.isFinite(parsed) ? parsed : raw);
        }}
      />
    );
  }

  if (property.type === "array") {
    const serialized = Array.isArray(value) ? JSON.stringify(value) : typeof value === "string" ? value : "";
    return (
      <input
        aria-label={name}
        type="text"
        value={serialized}
        disabled={disabled}
        onChange={(event) => {
          const raw = event.target.value;
          try {
            const parsed = JSON.parse(raw) as unknown;
            onChange(Array.isArray(parsed) ? parsed : raw);
          } catch {
            onChange(raw);
          }
        }}
      />
    );
  }

  return (
    <input
      aria-label={name}
      type="text"
      value={typeof value === "string" ? value : value == null ? "" : String(value)}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function ObjectProperties({
  schema,
  value,
  onChange,
  disabled,
}: {
  schema: ServerOwnedObjectSchema | ServerOwnedSchemaProperty;
  value: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
  disabled?: boolean;
}): ReactElement {
  const properties = schema.properties ?? {};
  return (
    <>
      {Object.entries(properties).map(([name, property]) => (
        <label className="ios-field" key={name}>
          <span>
            {name}
            {property.server_owned ? " · server-bound" : (schema.required ?? []).includes(name) ? " *" : ""}
          </span>
          <PropertyEditor
            name={name}
            property={property}
            value={value[name]}
            disabled={disabled}
            onChange={(next) => onChange(name, next)}
          />
        </label>
      ))}
    </>
  );
}

export function ServerOwnedModelOptions({
  control,
  value,
  onChange,
  disabled = false,
}: Props): ReactElement {
  return (
    <div className="ios-group" data-testid="server-owned-model-options">
      <p className="ios-hint" style={{ marginTop: 0 }}>
        {control.label ?? control.key} · server-owned schema
      </p>
      <ObjectProperties
        schema={control.schema ?? { type: "object", properties: {} }}
        value={value}
        onChange={onChange}
        disabled={disabled}
      />
    </div>
  );
}
