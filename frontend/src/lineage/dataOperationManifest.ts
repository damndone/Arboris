export const DATA_OPERATION_MANIFEST_VERSION = "data-operation-manifest.v1" as const;

export type DataOperationManifestErrorCode =
  | "MANIFEST_NOT_OBJECT"
  | "MANIFEST_FIELD_UNKNOWN"
  | "SCHEMA_VERSION_INVALID"
  | "OPERATIONS_INVALID"
  | "DESCRIPTOR_NOT_OBJECT"
  | "DESCRIPTOR_FIELD_MISSING"
  | "DESCRIPTOR_FIELD_INVALID"
  | "OPERATION_ID_DUPLICATE"
  | "REQUEST_SCHEMA_INVALID"
  | "REQUEST_SCHEMA_FIELD_TYPE_UNSUPPORTED"
  | "REQUEST_SCHEMA_DIGEST_INVALID"
  | "PORT_INVALID"
  | "REPLAY_INVALID"
  | "CLARIFICATION_INVALID"
  | "SOURCE_IDENTITY_MISSING";

export class DataOperationManifestError extends Error {
  readonly code: DataOperationManifestErrorCode;
  readonly path?: string;

  constructor(code: DataOperationManifestErrorCode, message: string, path?: string) {
    super(message);
    this.name = "DataOperationManifestError";
    this.code = code;
    this.path = path;
    Object.setPrototypeOf(this, DataOperationManifestError.prototype);
  }
}

export type DataOperationSchemaType =
  | "string"
  | "number"
  | "integer"
  | "boolean"
  | "object"
  | "array"
  | "null";

export interface DataOperationFieldSchema {
  type?: DataOperationSchemaType | DataOperationSchemaType[];
  enum?: unknown[];
  properties?: Record<string, DataOperationFieldSchema>;
  items?: DataOperationFieldSchema | DataOperationFieldSchema[];
  [key: string]: unknown;
}

export interface DataOperationRequestSchema extends DataOperationFieldSchema {
  type: "object";
  properties: Record<string, DataOperationFieldSchema>;
  required?: string[];
}

export interface DataOperationDescriptor {
  operation_id: string;
  operation_version: string;
  effect_level: string;
  risk_level: string;
  confirmation_policy: string;
  executor_key: string;
  reconciler_key: string;
  validator_key: string;
  request_schema: DataOperationRequestSchema;
  input_ports: DataOperationPort[];
  output_ports: DataOperationPort[];
  metadata_effect: string;
  metadata_risk: string;
  output_kind: string;
  preview_ref: string;
  confirm_ref: string;
  confirm_requires: string[];
  replay: DataOperationReplay;
  clarification_requirements: string[];
  request_schema_digest: string;
  availability?: DataOperationAvailability;
  [key: string]: unknown;
}

export interface DataOperationAvailability {
  status: "available" | "unavailable";
  reason_code: string;
  message: string;
}

export interface DataOperationPort {
  name: string;
  port_type: "dataset";
  dataset_kind: string | null;
  cardinality: "one" | "many";
  required: boolean;
  identity_fields: string[];
}

export interface DataOperationReplay {
  recipe_kind: string;
  request_identity_fields: string[];
  source_fingerprint_field: string;
  request_digest_field: string;
}

export interface DataOperationManifest {
  schema_version: typeof DATA_OPERATION_MANIFEST_VERSION;
  operations: DataOperationDescriptor[];
  unavailable?: DataOperationUnavailable[];
}

export interface DataOperationUnavailable {
  operation_id: string;
  operation_version: string;
  status: "unavailable";
  reason_code: string;
  message: string;
}

const SUPPORTED_SCHEMA_TYPES: ReadonlySet<DataOperationSchemaType> = new Set([
  "string",
  "number",
  "integer",
  "boolean",
  "object",
  "array",
  "null",
]);

const DESCRIPTOR_REQUIRED_FIELDS = [
  "operation_id",
  "operation_version",
  "effect_level",
  "risk_level",
  "confirmation_policy",
  "executor_key",
  "reconciler_key",
  "validator_key",
  "request_schema",
  "input_ports",
  "output_ports",
  "metadata_effect",
  "metadata_risk",
  "output_kind",
  "preview_ref",
  "confirm_ref",
  "confirm_requires",
  "replay",
  "clarification_requirements",
  "request_schema_digest",
] as const;

const SHA256_PATTERN = /^[0-9a-f]{64}$/;

const IDENTITY_FIELDS = [
  "source_run_id",
  "source_node_id",
  "source_artifact_id",
] as const;

type JsonObject = Record<string, unknown>;

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOwn(value: JsonObject, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function manifestError(
  code: DataOperationManifestErrorCode,
  message: string,
  path?: string,
): DataOperationManifestError {
  return new DataOperationManifestError(code, message, path);
}

function validateSchemaType(value: unknown, path: string): void {
  const types = Array.isArray(value) ? value : [value];
  if (
    types.length === 0 ||
    types.some(
      (type) => typeof type !== "string" || !SUPPORTED_SCHEMA_TYPES.has(type as DataOperationSchemaType),
    )
  ) {
    throw manifestError(
      "REQUEST_SCHEMA_FIELD_TYPE_UNSUPPORTED",
      `Unsupported request-schema field type at ${path}.`,
      path,
    );
  }
}

function validateSchema(value: unknown, path: string, stack: WeakSet<object>): void {
  if (!isObject(value)) {
    throw manifestError("REQUEST_SCHEMA_INVALID", `Request schema at ${path} must be an object.`, path);
  }
  if (stack.has(value)) {
    throw manifestError("REQUEST_SCHEMA_INVALID", `Request schema at ${path} is circular.`, path);
  }

  stack.add(value);
  try {
    if (hasOwn(value, "type")) validateSchemaType(value.type, `${path}.type`);

    if (hasOwn(value, "enum") && !Array.isArray(value.enum)) {
      throw manifestError("REQUEST_SCHEMA_INVALID", `Enum at ${path}.enum must be an array.`, `${path}.enum`);
    }

    if (hasOwn(value, "required")) {
      const required = value.required;
      if (
        !Array.isArray(required) ||
        required.some((field) => !nonEmptyString(field)) ||
        new Set(required).size !== required.length
      ) {
        throw manifestError(
          "REQUEST_SCHEMA_INVALID",
          `Required fields at ${path}.required must be unique non-empty strings.`,
          `${path}.required`,
        );
      }
    }

    if (hasOwn(value, "properties")) {
      if (!isObject(value.properties)) {
        throw manifestError(
          "REQUEST_SCHEMA_INVALID",
          `Properties at ${path}.properties must be an object.`,
          `${path}.properties`,
        );
      }
      for (const [fieldName, fieldSchema] of Object.entries(value.properties)) {
        validateSchema(fieldSchema, `${path}.properties.${fieldName}`, stack);
      }
    }

    if (hasOwn(value, "items")) {
      const items = value.items;
      if (Array.isArray(items)) {
        items.forEach((item, index) => validateSchema(item, `${path}.items[${index}]`, stack));
      } else {
        validateSchema(items, `${path}.items`, stack);
      }
    }

    if (hasOwn(value, "additionalProperties") && typeof value.additionalProperties !== "boolean") {
      validateSchema(value.additionalProperties, `${path}.additionalProperties`, stack);
    }

    for (const keyword of ["oneOf", "anyOf", "allOf"] as const) {
      if (!hasOwn(value, keyword)) continue;
      const alternatives = value[keyword];
      if (!Array.isArray(alternatives)) {
        throw manifestError(
          "REQUEST_SCHEMA_INVALID",
          `${keyword} at ${path}.${keyword} must be an array.`,
          `${path}.${keyword}`,
        );
      }
      alternatives.forEach((item, index) => validateSchema(item, `${path}.${keyword}[${index}]`, stack));
    }

    for (const keyword of ["not", "if", "then", "else"] as const) {
      if (hasOwn(value, keyword)) validateSchema(value[keyword], `${path}.${keyword}`, stack);
    }
  } finally {
    stack.delete(value);
  }
}

function validateRequestSchema(value: unknown, operationIndex: number): asserts value is DataOperationRequestSchema {
  const path = `operations[${operationIndex}].request_schema`;
  if (!isObject(value)) {
    throw manifestError(
      "REQUEST_SCHEMA_INVALID",
      `Request schema at ${path} must be an object schema with properties.`,
      path,
    );
  }
  if (hasOwn(value, "type") && value.type !== "object") {
    validateSchemaType(value.type, `${path}.type`);
  }
  if (value.type !== "object" || !isObject(value.properties)) {
    throw manifestError(
      "REQUEST_SCHEMA_INVALID",
      `Request schema at ${path} must be an object schema with properties.`,
      path,
    );
  }
  if (value.additionalProperties !== false) {
    throw manifestError(
      "REQUEST_SCHEMA_INVALID",
      `Request schema at ${path} must reject additional properties.`,
      `${path}.additionalProperties`,
    );
  }
  validateSchema(value, path, new WeakSet<object>());
}

function validatePort(value: unknown, path: string): asserts value is DataOperationPort {
  if (!isObject(value)) {
    throw manifestError("PORT_INVALID", `Port at ${path} must be an object.`, path);
  }
  if (
    !nonEmptyString(value.name) ||
    value.port_type !== "dataset" ||
    !(value.dataset_kind === null || nonEmptyString(value.dataset_kind)) ||
    (value.cardinality !== "one" && value.cardinality !== "many") ||
    typeof value.required !== "boolean" ||
    !Array.isArray(value.identity_fields) ||
    value.identity_fields.some((field) => !nonEmptyString(field)) ||
    new Set(value.identity_fields).size !== value.identity_fields.length
  ) {
    throw manifestError("PORT_INVALID", `Port at ${path} is not a closed dataset port.`, path);
  }
}

function validateReplay(value: unknown, path: string): asserts value is DataOperationReplay {
  if (!isObject(value)) {
    throw manifestError("REPLAY_INVALID", `Replay contract at ${path} must be an object.`, path);
  }
  if (
    !nonEmptyString(value.recipe_kind) ||
    !Array.isArray(value.request_identity_fields) ||
    value.request_identity_fields.length === 0 ||
    value.request_identity_fields.some((field) => !nonEmptyString(field)) ||
    new Set(value.request_identity_fields).size !== value.request_identity_fields.length ||
    !nonEmptyString(value.source_fingerprint_field) ||
    !nonEmptyString(value.request_digest_field)
  ) {
    throw manifestError("REPLAY_INVALID", `Replay contract at ${path} is invalid.`, path);
  }
}

function validateDescriptor(value: unknown, operationIndex: number): asserts value is DataOperationDescriptor {
  const path = `operations[${operationIndex}]`;
  if (!isObject(value)) {
    throw manifestError("DESCRIPTOR_NOT_OBJECT", `Descriptor at ${path} must be an object.`, path);
  }

  for (const field of DESCRIPTOR_REQUIRED_FIELDS) {
    if (!hasOwn(value, field)) {
      throw manifestError(
        "DESCRIPTOR_FIELD_MISSING",
        `Descriptor at ${path} is missing ${field}.`,
        `${path}.${field}`,
      );
    }
  }

  for (const field of ["operation_id", "preview_ref", "confirm_ref"] as const) {
    if (!nonEmptyString(value[field])) {
      throw manifestError(
        "DESCRIPTOR_FIELD_INVALID",
        `Descriptor field ${path}.${field} must be a non-empty string.`,
        `${path}.${field}`,
      );
    }
  }

  for (const field of [
    "operation_version",
    "effect_level",
    "risk_level",
    "confirmation_policy",
    "executor_key",
    "reconciler_key",
    "validator_key",
    "metadata_effect",
    "metadata_risk",
    "output_kind",
  ] as const) {
    if (!nonEmptyString(value[field])) {
      throw manifestError(
        "DESCRIPTOR_FIELD_INVALID",
        `Descriptor field ${path}.${field} must be a non-empty string.`,
        `${path}.${field}`,
      );
    }
  }

  const confirmRequires = value.confirm_requires;
  if (
    !Array.isArray(confirmRequires) ||
    confirmRequires.some((item) => !nonEmptyString(item)) ||
    new Set(confirmRequires).size !== confirmRequires.length
  ) {
    throw manifestError(
      "DESCRIPTOR_FIELD_INVALID",
      `Descriptor field ${path}.confirm_requires must be an array of unique strings.`,
      `${path}.confirm_requires`,
    );
  }

  for (const field of ["input_ports", "output_ports"] as const) {
    if (!Array.isArray(value[field]) || value[field].length === 0) {
      throw manifestError(
        "PORT_INVALID",
        `Descriptor field ${path}.${field} must be a non-empty array.`,
        `${path}.${field}`,
      );
    }
    value[field].forEach((port, index) => validatePort(port, `${path}.${field}[${index}]`));
  }
  validateReplay(value.replay, `${path}.replay`);
  if (
    !Array.isArray(value.clarification_requirements) ||
    value.clarification_requirements.length === 0 ||
    value.clarification_requirements.some((item) => !nonEmptyString(item))
  ) {
    throw manifestError(
      "CLARIFICATION_INVALID",
      `Descriptor field ${path}.clarification_requirements must be a non-empty string array.`,
      `${path}.clarification_requirements`,
    );
  }
  if (
    typeof value.request_schema_digest !== "string" ||
    !SHA256_PATTERN.test(value.request_schema_digest)
  ) {
    throw manifestError(
      "REQUEST_SCHEMA_DIGEST_INVALID",
      `Descriptor field ${path}.request_schema_digest must be a lowercase SHA-256 digest.`,
      `${path}.request_schema_digest`,
    );
  }

  validateRequestSchema(value.request_schema, operationIndex);

  if (hasOwn(value, "availability")) {
    if (!isObject(value.availability)) {
      throw manifestError(
        "DESCRIPTOR_FIELD_INVALID",
        `Descriptor availability at ${path}.availability must be an object.`,
        `${path}.availability`,
      );
    }
    if (
      (value.availability.status !== "available" && value.availability.status !== "unavailable") ||
      !nonEmptyString(value.availability.reason_code) ||
      !nonEmptyString(value.availability.message)
    ) {
      throw manifestError(
        "DESCRIPTOR_FIELD_INVALID",
        `Descriptor availability at ${path}.availability is invalid.`,
        `${path}.availability`,
      );
    }
  }
}

function validateUnavailable(value: unknown, index: number): asserts value is DataOperationUnavailable {
  const path = `unavailable[${index}]`;
  if (!isObject(value)) {
    throw manifestError("DESCRIPTOR_NOT_OBJECT", `Unavailable operation at ${path} must be an object.`, path);
  }
  if (
    !nonEmptyString(value.operation_id) ||
    !nonEmptyString(value.operation_version) ||
    value.status !== "unavailable" ||
    !nonEmptyString(value.reason_code) ||
    !nonEmptyString(value.message)
  ) {
    throw manifestError("DESCRIPTOR_FIELD_INVALID", `Unavailable operation at ${path} is invalid.`, path);
  }
}

/**
 * Parse the server-owned manifest at the wire boundary. The parser intentionally
 * retains descriptor metadata while validating every schema-bearing branch so a
 * renderer cannot silently accept an unknown field type.
 */
export function parseDataOperationManifest(value: unknown): DataOperationManifest {
  if (!isObject(value)) {
    throw manifestError("MANIFEST_NOT_OBJECT", "Data-operation manifest must be an object.");
  }

  const unknownFields = Object.keys(value).filter(
    (field) => field !== "schema_version" && field !== "operations" && field !== "unavailable",
  );
  if (unknownFields.length > 0) {
    throw manifestError(
      "MANIFEST_FIELD_UNKNOWN",
      `Data-operation manifest contains unknown field(s): ${unknownFields.join(", ")}.`,
    );
  }

  if (value.schema_version !== DATA_OPERATION_MANIFEST_VERSION) {
    throw manifestError(
      "SCHEMA_VERSION_INVALID",
      `Expected schema_version ${DATA_OPERATION_MANIFEST_VERSION}.`,
      "schema_version",
    );
  }
  if (!Array.isArray(value.operations) || value.operations.length === 0) {
    throw manifestError(
      "OPERATIONS_INVALID",
      "Data-operation manifest operations must be a non-empty array.",
      "operations",
    );
  }

  const operationIds = new Set<string>();
  value.operations.forEach((operation, index) => {
    validateDescriptor(operation, index);
    if (operationIds.has(operation.operation_id)) {
      throw manifestError(
        "OPERATION_ID_DUPLICATE",
        `Duplicate operation_id ${operation.operation_id}.`,
        `operations[${index}].operation_id`,
      );
    }
    operationIds.add(operation.operation_id);
  });

  let unavailable: DataOperationUnavailable[] | undefined;
  if (hasOwn(value, "unavailable")) {
    if (!Array.isArray(value.unavailable)) {
      throw manifestError("OPERATIONS_INVALID", "Data-operation manifest unavailable must be an array.", "unavailable");
    }
    unavailable = value.unavailable.map((item, index) => {
      validateUnavailable(item, index);
      return item;
    });
  }

  return {
    schema_version: DATA_OPERATION_MANIFEST_VERSION,
    operations: value.operations as DataOperationDescriptor[],
    unavailable,
  };
}

export const DATA_OPERATION_SOURCE_IDENTITY_FIELDS = IDENTITY_FIELDS;
