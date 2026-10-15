/** Form semantics shared by every declared operation; numerical validation stays server-owned. */
export type JsonSchema = {
  type?: string | string[]; title?: string; description?: string; enum?: unknown[];
  default?: unknown; const?: unknown; properties?: Record<string, JsonSchema>;
  required?: string[]; items?: JsonSchema; additionalProperties?: boolean | JsonSchema;
  anyOf?: JsonSchema[]; oneOf?: JsonSchema[]; nullable?: boolean;
  minimum?: number; maximum?: number; exclusiveMinimum?: number;
  minLength?: number; maxLength?: number; minItems?: number; maxItems?: number;
  uniqueItems?: boolean; minProperties?: number; $ref?: string; $defs?: Record<string, JsonSchema>;
};
export function resolveSchema(schema: JsonSchema, root: JsonSchema): JsonSchema {
  if (!schema.$ref) return schema;
  if (!schema.$ref.startsWith('#/')) throw new Error(`Unsupported schema reference: ${schema.$ref}`);
  let result: unknown = root;
  for (const token of schema.$ref.slice(2).split('/')) {
    result = (result as Record<string, unknown>)?.[token.replace(/~1/g, '/').replace(/~0/g, '~')];
  }
  if (!result || typeof result !== 'object') throw new Error(`Missing schema reference: ${schema.$ref}`);
  return {...result, ...schema, $ref: undefined} as JsonSchema;
}
export const valueType = (value: unknown): string => value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;
export function variants(schema: JsonSchema): JsonSchema[] | undefined {
  const declared = schema.oneOf ?? schema.anyOf;
  const choices = declared ?? (Array.isArray(schema.type) ? schema.type.map(type => ({...schema, type})) : undefined);
  if (schema.nullable) return [...(choices ?? [schema]).map(s => ({...s, nullable: false})), {type: 'null'}];
  return choices;
}
export function initialValue(schema: JsonSchema, root = schema, depth = 0): unknown {
  if (depth > 30) return undefined;
  const s = resolveSchema(schema, root);
  if (s.default !== undefined) return structuredClone(s.default);
  if (s.const !== undefined) return s.const;
  if (s.enum?.length === 1) return s.enum[0];
  if (variants(s)) return undefined;
  if (s.type === 'object' || s.properties) return Object.fromEntries((s.required ?? []).map(key => [key, initialValue(s.properties?.[key] ?? {}, root, depth + 1)]));
  if (s.type === 'array') return [];
  if (s.type === 'null') return null;
  return undefined;
}
export function seedValue(schema: JsonSchema, root: JsonSchema): unknown {
  const s = resolveSchema(schema, root);
  if (s.enum?.length) return s.enum[0];
  const initial = initialValue(s, root);
  if (initial !== undefined) return initial;
  return s.type === 'string' ? '' : s.type === 'number' || s.type === 'integer' ? 0 : s.type === 'boolean' ? false : undefined;
}
function equal(a: unknown, b: unknown): boolean { return JSON.stringify(a) === JSON.stringify(b); }
export function validateValue(schema: JsonSchema, value: unknown, root = schema, path = 'Parameters', required = true, depth = 0): string[] {
  if (value === undefined) return required ? [`${path}: a value is required.`] : [];
  if (depth > 30) return [`${path}: nesting exceeds the supported form depth.`];
  const s = resolveSchema(schema, root);
  const branches = variants(s);
  if (branches) {
    const matches = branches.filter(b => validateValue(b, value, root, path, true, depth + 1).length === 0);
    return (s.oneOf ? matches.length === 1 : matches.length > 0) ? [] : [`${path}: choose and complete a valid value variant.`];
  }
  if (s.const !== undefined && !equal(value, s.const)) return [`${path}: must equal ${String(s.const)}.`];
  if (s.enum && !s.enum.some(v => equal(v, value))) return [`${path}: choose a declared option.`];
  const type = valueType(value);
  if (s.type && s.type !== type && !(s.type === 'integer' && type === 'number' && Number.isInteger(value))) return [`${path}: expected ${s.type}.`];
  const errors: string[] = [];
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) errors.push(`${path}: enter a finite number.`);
    if (s.minimum !== undefined && value < s.minimum) errors.push(`${path}: minimum ${s.minimum}.`);
    if (s.exclusiveMinimum !== undefined && value <= s.exclusiveMinimum) errors.push(`${path}: must exceed ${s.exclusiveMinimum}.`);
    if (s.maximum !== undefined && value > s.maximum) errors.push(`${path}: maximum ${s.maximum}.`);
  }
  if (typeof value === 'string') {
    if (s.minLength !== undefined && value.length < s.minLength) errors.push(`${path}: at least ${s.minLength} characters.`);
    if (s.maxLength !== undefined && value.length > s.maxLength) errors.push(`${path}: at most ${s.maxLength} characters.`);
  }
  if (Array.isArray(value)) {
    if (s.minItems !== undefined && value.length < s.minItems) errors.push(`${path}: add at least ${s.minItems} items.`);
    if (s.maxItems !== undefined && value.length > s.maxItems) errors.push(`${path}: at most ${s.maxItems} items.`);
    if (s.uniqueItems && new Set(value.map(v => JSON.stringify(v))).size !== value.length) errors.push(`${path}: items must be unique.`);
    value.forEach((v, i) => errors.push(...validateValue(s.items ?? {}, v, root, `${path}[${i + 1}]`, true, depth + 1)));
  } else if (value !== null && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    if (s.minProperties !== undefined && Object.keys(record).length < s.minProperties) errors.push(`${path}: add at least ${s.minProperties} fields.`);
    for (const key of s.required ?? []) if (record[key] === undefined) errors.push(`${path}.${key}: a value is required.`);
    for (const [key, v] of Object.entries(record)) {
      const known = s.properties && Object.prototype.hasOwnProperty.call(s.properties, key);
      if (!known && s.additionalProperties === false) errors.push(`${path}.${key}: field is not declared.`);
      else errors.push(...validateValue(known ? s.properties![key] : typeof s.additionalProperties === 'object' ? s.additionalProperties : {}, v, root, `${path}.${key}`, true, depth + 1));
    }
  }
  return errors;
}
