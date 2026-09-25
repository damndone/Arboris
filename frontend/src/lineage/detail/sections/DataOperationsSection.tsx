import { useRef, useState } from "react";
import {
  DATA_OPERATION_SOURCE_IDENTITY_FIELDS,
  DataOperationManifestError,
  type DataOperationDescriptor,
  type DataOperationFieldSchema,
  type DataOperationManifest,
  parseDataOperationManifest,
} from "../../dataOperationManifest";
import type {
  DataMetadataUpdateV1,
  DataProfileV1,
  DataProfileVariableV1,
} from "../../dataOperations";

export interface DataOperationSourceIdentity {
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
}

export type DataOperationAction = (
  projectRoot: string,
  descriptor: DataOperationDescriptor,
  request: Record<string, unknown>,
) => Response | PromiseLike<Response>;

export interface DataOperationsSectionProps {
  manifest: unknown;
  projectRoot: string;
  preview: DataOperationAction;
  confirm: DataOperationAction;
  sourceIdentity?: Partial<DataOperationSourceIdentity>;
  source_run_id?: string;
  source_node_id?: string;
  source_artifact_id?: string;
  profile?: unknown;
  profileStatus?: DataProfileStatus;
}

interface ResolvedSourceIdentity {
  source_run_id: string | undefined;
  source_node_id: string | undefined;
  source_artifact_id: string | undefined;
}

type OperationStatus = "idle" | "previewing" | "confirming" | "complete" | "error";
type DataProfileStatus = "loading" | "available" | "unavailable" | "degraded";

interface PreviewPayload {
  status: string;
  fingerprint?: string;
  [key: string]: unknown;
}

interface ConfirmPayload {
  status: string;
  effect?: Record<string, unknown>;
  operation?: Record<string, unknown>;
  reason_code?: string;
  message?: string;
  [key: string]: unknown;
}

const EMPTY_VALUE = "";

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function safeProfileValue(value: unknown): value is string | number | boolean | null {
  return value === null || ["string", "number", "boolean"].includes(typeof value);
}

function boundedDataProfile(value: unknown): DataProfileV1 | null {
  if (!isObject(value) || value.schema_version !== "data-profile.v1") return null;
  const source = isObject(value.source) ? value.source : null;
  const variables = Array.isArray(value.variables) ? value.variables : null;
  if (
    !source ||
    typeof source.run_id !== "string" ||
    typeof source.node_id !== "string" ||
    typeof source.artifact_id !== "string" ||
    !variables
  ) {
    return null;
  }
  const normalized: DataProfileVariableV1[] = [];
  for (const candidate of variables) {
    if (!isObject(candidate) || typeof candidate.name !== "string" || !candidate.name.trim()) {
      return null;
    }
    const missingness = isObject(candidate.missingness) ? candidate.missingness : null;
    const count = finiteNumber(missingness?.count);
    const rate = finiteNumber(missingness?.rate);
    const valueLabels = isObject(candidate.value_labels) ? candidate.value_labels : {};
    const userMissingValues = Array.isArray(candidate.user_missing_values)
      ? candidate.user_missing_values.filter(safeProfileValue)
      : [];
    const sampleValues = Array.isArray(candidate.sample_values)
      ? candidate.sample_values.filter(safeProfileValue)
      : [];
    const labels = Object.fromEntries(
      Object.entries(valueLabels).filter(([, label]) => typeof label === "string"),
    ) as Record<string, string>;
    const optionalTextFields = ["missing_policy", "role", "sensitivity"] as const;
    const optionalText = Object.fromEntries(
      optionalTextFields.map((field) => {
        const value = candidate[field];
        return [field, value === null || value === undefined ? null : typeof value === "string" ? value : null];
      }),
    );
    if (
      optionalTextFields.some(
        (field) => candidate[field] !== undefined && candidate[field] !== null && typeof candidate[field] !== "string",
      )
    ) {
      return null;
    }
    if (count === null || rate === null) return null;
    normalized.push({
      name: candidate.name,
      label: typeof candidate.label === "string" ? candidate.label : null,
      measurement_level:
        typeof candidate.measurement_level === "string" ? candidate.measurement_level : null,
      missing_policy: optionalText.missing_policy,
      role: optionalText.role,
      sensitivity: optionalText.sensitivity,
      missingness: { count, rate },
      user_missing_values: userMissingValues,
      value_labels: labels,
      sample_values: sampleValues,
    });
  }
  return {
    schema_version: "data-profile.v1",
    source: {
      run_id: source.run_id,
      node_id: source.node_id,
      artifact_id: source.artifact_id,
    },
    variables: normalized,
  };
}

function profileMatchesSource(
  profile: DataProfileV1,
  identity: ResolvedSourceIdentity,
): boolean {
  return (
    profile.source.run_id === identity.source_run_id &&
    profile.source.node_id === identity.source_node_id &&
    profile.source.artifact_id === identity.source_artifact_id
  );
}

function profileValueText(value: unknown): string {
  if (value === null) return "null";
  return String(value);
}

function profileMetadata(profile: DataProfileV1): DataMetadataUpdateV1 {
  return Object.fromEntries(
    profile.variables.map((variable) => {
      const declaration: DataMetadataUpdateV1[string] = {
        user_missing_values: [...variable.user_missing_values],
        value_labels: { ...variable.value_labels },
      };
      if (variable.label) declaration.variable_label = variable.label;
      if (variable.measurement_level) declaration.measurement_level = variable.measurement_level;
      if (variable.missing_policy) declaration.missing_policy = variable.missing_policy;
      if (variable.role) declaration.role = variable.role;
      if (variable.sensitivity) declaration.sensitivity = variable.sensitivity;
      return [variable.name, declaration];
    }),
  );
}

function profileMissingness(variable: DataProfileVariableV1): string {
  const percent = Number((variable.missingness.rate * 100).toFixed(2));
  return `${variable.missingness.count} (${percent}%)`;
}

function ProfilePanel({
  rawProfile,
  status,
  canEdit,
  onEdit,
}: {
  rawProfile: unknown;
  status: DataProfileStatus;
  canEdit: boolean;
  onEdit: () => void;
}) {
  if (status === "loading") {
    return <p data-testid="data-profile-status">LOADING: bounded data profile.</p>;
  }
  const profile = boundedDataProfile(rawProfile);
  if (status === "unavailable") {
    return <p data-testid="data-profile-status">UNAVAILABLE: bounded data profile.</p>;
  }
  if (!profile) {
    return <p data-testid="data-profile-status">DEGRADED: bounded data profile is not trusted.</p>;
  }
  if (status === "degraded") {
    return <p data-testid="data-profile-status">DEGRADED: bounded data profile is not trusted.</p>;
  }
  return (
    <section aria-label="Data profile" data-testid="data-profile">
      <h4>Data profile</h4>
      {profile.variables.map((variable) => (
        <div key={variable.name} data-testid={`data-profile-variable-${variable.name}`}>
          <strong>{variable.name}</strong>
          <dl>
            <dt>Label</dt>
            <dd>{variable.label || "UNAVAILABLE"}</dd>
            <dt>Measurement level</dt>
            <dd>{variable.measurement_level || "UNAVAILABLE"}</dd>
            <dt>Missingness</dt>
            <dd>{profileMissingness(variable)}</dd>
            <dt>User missing values</dt>
            <dd>{variable.user_missing_values.map(profileValueText).join(", ") || "UNAVAILABLE"}</dd>
            <dt>Value labels</dt>
            <dd>
              {Object.entries(variable.value_labels)
                .map(([value, label]) => `${value} → ${label}`)
                .join(", ") || "UNAVAILABLE"}
            </dd>
            <dt>Bounded sample values</dt>
            <dd>{variable.sample_values.map(profileValueText).join(", ") || "UNAVAILABLE"}</dd>
          </dl>
          {canEdit && (
            <button type="button" onClick={onEdit}>
              Edit metadata
            </button>
          )}
        </div>
      ))}
    </section>
  );
}

function resolveSourceIdentity(props: DataOperationsSectionProps): ResolvedSourceIdentity {
  return {
    source_run_id: props.sourceIdentity?.source_run_id ?? props.source_run_id,
    source_node_id: props.sourceIdentity?.source_node_id ?? props.source_node_id,
    source_artifact_id: props.sourceIdentity?.source_artifact_id ?? props.source_artifact_id,
  };
}

function assertSourceIdentity(
  manifest: DataOperationManifest,
  identity: ResolvedSourceIdentity,
): void {
  for (const operation of manifest.operations.filter(
    (candidate) => candidate.availability?.status !== "unavailable",
  )) {
    const properties = operation.request_schema.properties;
    for (const field of DATA_OPERATION_SOURCE_IDENTITY_FIELDS) {
      const identityValue = identity[field];
      if (!properties[field] || typeof identityValue !== "string" || !identityValue.trim()) {
        throw new DataOperationManifestError(
          "SOURCE_IDENTITY_MISSING",
          `Source identity ${field} is required by ${operation.operation_id}.`,
          `operations.${operation.operation_id}.request_schema.properties.${field}`,
        );
      }
    }
  }
}

async function readPreviewPayload(response: unknown): Promise<PreviewPayload | null> {
  if (typeof Response === "undefined" || !(response instanceof Response)) return null;
  if (!response.ok || response.status < 200 || response.status >= 300) return null;
  const body = await response.json();
  const candidate = isObject(body) && isObject(body.preview) ? body.preview : null;
  if (!candidate || typeof candidate.status !== "string") return null;
  return candidate as PreviewPayload;
}

function isRealResponse(response: unknown): response is Response {
  return typeof Response !== "undefined" && response instanceof Response;
}

async function readConfirmPayload(response: unknown): Promise<{
  payload: ConfirmPayload | null;
  httpStatus: number | null;
  httpOk: boolean | null;
  isHttpResponse: boolean;
}> {
  if (isRealResponse(response)) {
    const httpStatus = response.status;
    const httpOk = response.ok;
    const body = await response.json();
    return {
      payload: isObject(body) && typeof body.status === "string" ? (body as ConfirmPayload) : null,
      httpStatus,
      httpOk,
      isHttpResponse: true,
    };
  }
  return { payload: null, httpStatus: null, httpOk: null, isHttpResponse: false };
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  if (isObject(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

async function requestSha256(request: Record<string, unknown>): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(canonicalJson(request)),
  );
  return Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, "0")).join("");
}

async function optionsSha256(request: Record<string, unknown>): Promise<string> {
  const {
    source_run_id: _run,
    source_node_id: _node,
    source_artifact_id: _artifact,
    ...options
  } = request;
  return requestSha256(options);
}

function exactIdentityBindings(effect: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(effect).filter(
      ([field, value]) => field.endsWith("_id") && typeof value === "string" && value.trim(),
    ),
  ) as Record<string, string>;
}

function confirmedPayloadError(
  payload: ConfirmPayload | null,
  descriptor: DataOperationDescriptor,
  operationId: string,
  previewFingerprint: string,
  requestDigest: string,
  optionsDigest: string,
  sourceIdentity: ResolvedSourceIdentity,
  catalogDigest: string,
): string | null {
  if (!payload || payload.status !== "completed") {
    return "CONFIRM_INVALID: confirmation did not return completed status.";
  }
  const responsePreview = payload.preview;
  if (
    !isObject(responsePreview) ||
    responsePreview.status !== "ready" ||
    responsePreview.fingerprint !== previewFingerprint ||
    responsePreview.request_sha256 !== requestDigest ||
    responsePreview.options_sha256 !== optionsDigest ||
    responsePreview.catalog_digest !== catalogDigest ||
    responsePreview.source_run_id !== sourceIdentity.source_run_id ||
    responsePreview.source_node_id !== sourceIdentity.source_node_id ||
    responsePreview.source_artifact_id !== sourceIdentity.source_artifact_id
  ) {
    return "CONFIRM_INVALID: completed preview identity is stale or mismatched.";
  }
  const effect = payload.effect;
  if (
    !effect ||
    typeof effect.execution_key !== "string" ||
    !effect.execution_key.trim() ||
    typeof effect.child_node_id !== "string" ||
    !effect.child_node_id.trim() ||
    !(
      (typeof effect.artifact_id === "string" && effect.artifact_id.trim()) ||
      (typeof effect.metadata_artifact_id === "string" && effect.metadata_artifact_id.trim())
    )
  ) {
    return "CONFIRM_INVALID: completed effect is missing typed identity.";
  }
  // The typed OperationRecord is authoritative. Keep the legacy `operation`
  // field as a migration fallback for older server responses only.
  const operation = isObject(payload.operation_record)
    ? payload.operation_record
    : payload.operation;
  if (
    !operation ||
    typeof operation.record_id !== "string" ||
    !operation.record_id.trim() ||
    operation.operation_id !== operationId ||
    operation.operation_version !== descriptor.operation_version ||
    operation.status !== "completed"
  ) {
    return "CONFIRM_INVALID: completed operation identity is not server-verified.";
  }
  const target = operation.target;
  if (
    !isObject(target) ||
    target.run_id !== sourceIdentity.source_run_id ||
    target.node_ref !== sourceIdentity.source_node_id ||
    target.artifact_id !== sourceIdentity.source_artifact_id
  ) {
    return "CONFIRM_INVALID: completed operation target does not match the request.";
  }
  const execution = operation.execution;
  if (!isObject(execution) || execution.execution_key !== effect.execution_key) {
    return "CONFIRM_INVALID: completed execution identity does not match the effect.";
  }
  const bindings = execution.bindings;
  if (!isObject(bindings)) {
    return "CONFIRM_INVALID: completed execution bindings are missing.";
  }
  const expectedBindings = exactIdentityBindings(effect);
  if (
    JSON.stringify(Object.keys(bindings).sort()) !==
    JSON.stringify(Object.keys(expectedBindings).sort())
  ) {
    return "CONFIRM_INVALID: completed effect bindings are not field-exact.";
  }
  for (const [field, value] of Object.entries(expectedBindings)) {
    if (bindings[field] !== value) {
      return "CONFIRM_INVALID: completed effect binding does not match the OperationRecord.";
    }
  }
  const outputs = operation.outputs;
  const ports = isObject(outputs) && isObject(outputs.ports) ? outputs.ports : null;
  const expectedPortNames = descriptor.output_ports.map((port) => port.name).sort();
  if (
    !ports ||
    JSON.stringify(Object.keys(ports).sort()) !== JSON.stringify(expectedPortNames)
  ) {
    return "CONFIRM_INVALID: completed output ports do not match the descriptor.";
  }
  const derived = ports && isObject(ports.derived) ? ports.derived : null;
  const operationRecordPort = ports && isObject(ports.operation_record) ? ports.operation_record : null;
  if (
    !derived ||
    derived.execution_key !== effect.execution_key ||
    derived.child_node_id !== effect.child_node_id ||
    Object.entries(effect).some(([field, value]) => derived[field] !== value) ||
    !operationRecordPort ||
    operationRecordPort.record_id !== operation.record_id ||
    operationRecordPort.operation_id !== operation.operation_id ||
    operationRecordPort.operation_version !== descriptor.operation_version
  ) {
    return "CONFIRM_INVALID: typed output ports are not bound to the effect and record.";
  }
  const slots = isObject(outputs) && isObject(outputs.consumer_slots) ? outputs.consumer_slots : null;
  const expectedSlots: Record<string, string> = {
    "data.agent": "derived",
    "data.notebook": "derived",
    "data.report": "evidence",
  };
  if (
    !slots ||
    JSON.stringify(Object.keys(slots).sort()) !== JSON.stringify(Object.keys(expectedSlots).sort())
  ) {
    return "CONFIRM_INVALID: typed consumer slots are incomplete.";
  }
  for (const [slot, expectedPort] of Object.entries(expectedSlots)) {
    const value = slots[slot];
    if (
      !isObject(value) ||
      value.record_id !== operation.record_id ||
      value.port !== expectedPort
    ) {
      return "CONFIRM_INVALID: typed consumer slot is not bound to the OperationRecord.";
    }
  }
  const evidence = ports && isObject(ports.evidence) ? ports.evidence : null;
  if (
    !evidence ||
    typeof evidence.method !== "string" ||
    !evidence.method.trim() ||
    evidence.record_id !== operation.record_id ||
    evidence.operation_id !== operationId ||
    evidence.execution_key !== effect.execution_key ||
    evidence.child_node_id !== effect.child_node_id
  ) {
    return "CONFIRM_INVALID: typed evidence is not bound to the effect and record.";
  }
  const expectedMethod =
    typeof responsePreview.evidence_method === "string"
      ? responsePreview.evidence_method
      : typeof responsePreview.method === "string"
        ? responsePreview.method
        : operationId;
  if (evidence.method !== expectedMethod) {
    return "CONFIRM_INVALID: evidence method is stale or mismatched.";
  }
  const expectedEvidence: Record<string, unknown> = {
    record_id: operation.record_id,
    operation_id: operationId,
    execution_key: effect.execution_key,
    ...expectedBindings,
  };
  if (isObject(responsePreview.evidence)) {
    Object.assign(expectedEvidence, responsePreview.evidence);
  }
  for (const [field, value] of Object.entries(expectedEvidence)) {
    if (evidence[field] !== value) {
      return "CONFIRM_INVALID: evidence payload is stale or mismatched.";
    }
  }
  if (!isObject(outputs) || outputs.catalog_digest !== catalogDigest) {
    return "CONFIRM_INVALID: catalog digest is stale or mismatched.";
  }
  return null;
}

function confirmResultText(payload: ConfirmPayload): string {
  return [payload.status, payload.reason_code, payload.message]
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .join(" — ");
}

function readyFingerprint(preview: PreviewPayload | null): string | null {
  if (
    preview?.status !== "ready" ||
    typeof preview.fingerprint !== "string" ||
    !preview.fingerprint.trim()
  ) {
    return null;
  }
  return preview.fingerprint;
}

function schemaTypes(schema: DataOperationFieldSchema): string[] {
  if (Array.isArray(schema.type)) return schema.type;
  return typeof schema.type === "string" ? [schema.type] : [];
}

function initialValue(schema: DataOperationFieldSchema): unknown {
  if (Array.isArray(schema.enum) && schema.enum.length > 0) return EMPTY_VALUE;
  const type = schemaTypes(schema)[0];
  if (type === "boolean") return false;
  return EMPTY_VALUE;
}

function jsonValue(value: unknown): string {
  if (value === EMPTY_VALUE || value === undefined) return EMPTY_VALUE;
  try {
    return JSON.stringify(value);
  } catch {
    return EMPTY_VALUE;
  }
}

function requestHasValue(value: unknown): boolean {
  if (typeof value === "string") return value.trim().length > 0;
  return value !== undefined && value !== null;
}

function requestFor(
  identity: ResolvedSourceIdentity,
  values: Record<string, unknown>,
): Record<string, unknown> {
  return {
    source_run_id: identity.source_run_id,
    source_node_id: identity.source_node_id,
    source_artifact_id: identity.source_artifact_id,
    ...values,
  };
}

function OperationField({
  name,
  schema,
  value,
  onChange,
}: {
  name: string;
  schema: DataOperationFieldSchema;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const fieldId = `data-operation-field-${name}`;
  const types = schemaTypes(schema);
  const type = types[0];

  if (Array.isArray(schema.enum)) {
    return (
      <label htmlFor={fieldId}>
        {name}
        <select
          id={fieldId}
          aria-label={name}
          value={typeof value === "string" ? value : EMPTY_VALUE}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">Select {name}</option>
          {schema.enum.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      </label>
    );
  }

  if (type === "boolean") {
    return (
      <label htmlFor={fieldId}>
        {name}
        <input
          id={fieldId}
          aria-label={name}
          type="checkbox"
          checked={value === true}
          onChange={(event) => onChange(event.target.checked)}
        />
      </label>
    );
  }

  if (type === "number" || type === "integer") {
    return (
      <label htmlFor={fieldId}>
        {name}
        <input
          id={fieldId}
          aria-label={name}
          type="number"
          value={typeof value === "number" ? value : EMPTY_VALUE}
          onChange={(event) =>
            onChange(event.target.value === EMPTY_VALUE ? EMPTY_VALUE : Number(event.target.value))
          }
        />
      </label>
    );
  }

  if (type === "string" || types.length === 0) {
    return (
      <label htmlFor={fieldId}>
        {name}
        <input
          id={fieldId}
          aria-label={name}
          type="text"
          value={typeof value === "string" ? value : EMPTY_VALUE}
          onChange={(event) => onChange(event.target.value)}
        />
      </label>
    );
  }

  return (
    <label htmlFor={fieldId}>
      {name}
      <textarea
        id={fieldId}
        aria-label={name}
        value={jsonValue(value)}
        onChange={(event) => {
          const raw = event.target.value;
          if (raw.trim() === EMPTY_VALUE) {
            onChange(EMPTY_VALUE);
            return;
          }
          try {
            onChange(JSON.parse(raw) as unknown);
          } catch {
            onChange(raw);
          }
        }}
      />
    </label>
  );
}

function parseMetadataList(value: string): unknown[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const numeric = Number(item);
      return item !== "" && Number.isFinite(numeric) ? numeric : item;
    });
}

function MetadataEditor({
  profile,
  metadata,
  onChange,
}: {
  profile: DataProfileV1;
  metadata: DataMetadataUpdateV1;
  onChange: (metadata: DataMetadataUpdateV1) => void;
}) {
  const [newValueKeys, setNewValueKeys] = useState<Record<string, string>>({});
  const [newValueLabels, setNewValueLabels] = useState<Record<string, string>>({});

  function update(variable: DataProfileVariableV1, field: string, value: unknown) {
    onChange({
      ...metadata,
      [variable.name]: {
        ...(metadata[variable.name] ?? {}),
        [field]: value,
      },
    });
  }

  function addValueLabel(variable: DataProfileVariableV1, labels: Record<string, unknown>) {
    const value = (newValueKeys[variable.name] ?? "").trim();
    const label = (newValueLabels[variable.name] ?? "").trim();
    if (!value || !label || Object.prototype.hasOwnProperty.call(labels, value)) return;
    update(variable, "value_labels", { ...labels, [value]: label });
    setNewValueKeys((current) => ({ ...current, [variable.name]: "" }));
    setNewValueLabels((current) => ({ ...current, [variable.name]: "" }));
  }

  return (
    <section aria-label="Metadata editor" data-testid="data-metadata-editor">
      <h4>Metadata editor</h4>
      {profile.variables.map((variable) => {
        const current = metadata[variable.name] ?? {};
        const label =
          typeof current.variable_label === "string" ? current.variable_label : variable.label ?? "";
        const measurementLevel =
          typeof current.measurement_level === "string"
            ? current.measurement_level
            : variable.measurement_level ?? "unknown";
        const missingPolicy =
          typeof current.missing_policy === "string"
            ? current.missing_policy
            : variable.missing_policy ?? "unknown";
        const role = typeof current.role === "string" ? current.role : variable.role ?? "unknown";
        const sensitivity =
          typeof current.sensitivity === "string"
            ? current.sensitivity
            : variable.sensitivity ?? "unknown";
        const missing = Array.isArray(current.user_missing_values)
          ? current.user_missing_values.map(profileValueText).join(", ")
          : variable.user_missing_values.map(profileValueText).join(", ");
        const labels = isObject(current.value_labels)
          ? current.value_labels
          : variable.value_labels;
        return (
          <fieldset key={variable.name}>
            <legend>{variable.name}</legend>
            <label>
              {variable.name} label
              <input
                aria-label={`${variable.name} label`}
                value={label}
                onChange={(event) => update(variable, "variable_label", event.target.value)}
              />
            </label>
            <label>
              {variable.name} measurement level
              <select
                aria-label={`${variable.name} measurement level`}
                value={measurementLevel}
                onChange={(event) => update(variable, "measurement_level", event.target.value)}
              >
                {[
                  ["unknown", "Unknown"],
                  ["nominal", "Nominal"],
                  ["ordinal", "Ordinal"],
                  ["scale", "Scale"],
                  ["time", "Time"],
                ].map(([value, text]) => (
                  <option key={value} value={value}>
                    {text}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {variable.name} missing policy
              <input
                aria-label={`${variable.name} missing policy`}
                value={missingPolicy}
                onChange={(event) => update(variable, "missing_policy", event.target.value)}
              />
            </label>
            <label>
              {variable.name} role
              <input
                aria-label={`${variable.name} role`}
                value={role}
                onChange={(event) => update(variable, "role", event.target.value)}
              />
            </label>
            <label>
              {variable.name} sensitivity
              <select
                aria-label={`${variable.name} sensitivity`}
                value={sensitivity}
                onChange={(event) => update(variable, "sensitivity", event.target.value)}
              >
                {["unknown", "public", "internal", "restricted"].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              {variable.name} user missing values
              <input
                aria-label={`${variable.name} user missing values`}
                value={missing}
                onChange={(event) => update(variable, "user_missing_values", parseMetadataList(event.target.value))}
              />
            </label>
            {Object.entries(labels).map(([value, currentLabel]) => (
              <label key={value}>
                {variable.name} value label {value}
                <input
                  aria-label={`${variable.name} value label ${value}`}
                  value={typeof currentLabel === "string" ? currentLabel : ""}
                  onChange={(event) =>
                    update(variable, "value_labels", {
                      ...labels,
                      [value]: event.target.value,
                    })
                  }
                />
              </label>
            ))}
            <label>
              {variable.name} value label key
              <input
                aria-label={`${variable.name} value label key`}
                value={newValueKeys[variable.name] ?? ""}
                onChange={(event) =>
                  setNewValueKeys((current) => ({ ...current, [variable.name]: event.target.value }))
                }
              />
            </label>
            <label>
              {variable.name} value label text
              <input
                aria-label={`${variable.name} value label text`}
                value={newValueLabels[variable.name] ?? ""}
                onChange={(event) =>
                  setNewValueLabels((current) => ({ ...current, [variable.name]: event.target.value }))
                }
              />
            </label>
            <button type="button" onClick={() => addValueLabel(variable, labels)}>
              Add value label for {variable.name}
            </button>
          </fieldset>
        );
      })}
    </section>
  );
}

function ParsedDataOperationsSection({
  manifest,
  projectRoot,
  preview,
  confirm,
  sourceIdentity,
  profile,
  profileStatus,
}: {
  manifest: DataOperationManifest;
  projectRoot: string;
  preview: DataOperationAction;
  confirm: DataOperationAction;
  sourceIdentity: ResolvedSourceIdentity;
  profile: unknown;
  profileStatus: DataProfileStatus;
}) {
  const [selectedOperationId, setSelectedOperationId] = useState("");
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [previewPayload, setPreviewPayload] = useState<PreviewPayload | null>(null);
  const [confirmPayload, setConfirmPayload] = useState<ConfirmPayload | null>(null);
  const [status, setStatus] = useState<OperationStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const requestRevision = useRef(0);

  const selectedOperation = manifest.operations.find(
    (operation) =>
      operation.operation_id === selectedOperationId &&
      operation.availability?.status !== "unavailable",
  );
  const availableOperations = manifest.operations.filter(
    (operation) => operation.availability?.status !== "unavailable",
  );
  const unavailableOperations = [
    ...(manifest.unavailable ?? []),
    ...manifest.operations.filter((operation) => operation.availability?.status === "unavailable"),
  ];
  const parsedProfile = boundedDataProfile(profile);
  const normalizedProfile =
    profileStatus === "available" && parsedProfile && profileMatchesSource(parsedProfile, sourceIdentity)
      ? parsedProfile
      : null;
  const effectiveProfileStatus =
    profileStatus === "available" && normalizedProfile === null ? "degraded" : profileStatus;
  const metadataOperation = availableOperations.find(
    (operation) => operation.operation_id === "data.metadata.update",
  );

  function invalidatePreview() {
    requestRevision.current += 1;
    setPreviewPayload(null);
    setConfirmPayload(null);
    setError(null);
    setStatus("idle");
  }

  function selectOperation(operationId: string) {
    requestRevision.current += 1;
    setSelectedOperationId(operationId);
    setValues({});
    setPreviewPayload(null);
    setConfirmPayload(null);
    setError(null);
    setStatus("idle");
  }

  function editProfileMetadata() {
    if (!metadataOperation || !normalizedProfile) return;
    setSelectedOperationId(metadataOperation.operation_id);
    setValues({ metadata: profileMetadata(normalizedProfile) });
    setPreviewPayload(null);
    setConfirmPayload(null);
    setError(null);
    setStatus("idle");
    requestRevision.current += 1;
  }

  function changeValue(name: string, value: unknown) {
    setValues((current) => ({ ...current, [name]: value }));
    invalidatePreview();
  }

  async function handlePreview() {
    if (!selectedOperation) return;
    const request = requestFor(sourceIdentity, values);
    const requiredFields = selectedOperation.request_schema.required ?? [];
    const missingField = requiredFields.find((field) => !requestHasValue(request[field]));
    if (missingField) {
      setError(`REQUEST_FIELD_MISSING: ${missingField}`);
      setStatus("error");
      return;
    }

    const revision = requestRevision.current;
    setPreviewPayload(null);
    setConfirmPayload(null);
    setError(null);
    setStatus("previewing");
    try {
      const requestDigest = await requestSha256(request);
      const response = await preview(projectRoot, selectedOperation, request);
      if (requestRevision.current !== revision) return;
      const payload = await readPreviewPayload(response);
      if (!payload) {
        setError("PREVIEW_INVALID: preview response is not a typed preview.");
        setStatus("error");
        return;
      }
      if (payload.request_sha256 !== requestDigest) {
        setError("PREVIEW_INVALID: preview request digest is stale or mismatched.");
        setStatus("error");
        return;
      }
      setPreviewPayload(payload);
      setStatus("idle");
    } catch (reason: unknown) {
      if (requestRevision.current !== revision) return;
      setError(reason instanceof Error ? reason.message : String(reason));
      setStatus("error");
    }
  }

  async function handleConfirm() {
    const fingerprint = readyFingerprint(previewPayload);
    if (!selectedOperation || !fingerprint) return;
    const request = {
      ...requestFor(sourceIdentity, values),
      preview_fingerprint: fingerprint,
    };
    const requestWithoutFingerprint = requestFor(sourceIdentity, values);
    const revision = requestRevision.current;
    setError(null);
    setConfirmPayload(null);
    setStatus("confirming");
    try {
      const response = await confirm(projectRoot, selectedOperation, request);
      if (requestRevision.current !== revision) return;
      const result = await readConfirmPayload(response);
      if (requestRevision.current !== revision) return;
      setConfirmPayload(result.payload);
      const httpFailed =
        !result.isHttpResponse ||
        result.httpStatus === null ||
        result.httpStatus < 200 ||
        result.httpStatus >= 300 ||
        result.httpOk !== true;
      if (httpFailed) {
        setError(
          result.isHttpResponse
            ? `HTTP ${result.httpStatus}: ${result.payload ? confirmResultText(result.payload) : "typed confirmation response unavailable."}`
            : "CONFIRM_INVALID: confirmation must be a successful HTTP response.",
        );
        setStatus("error");
        return;
      }
      const invalid = confirmedPayloadError(
        result.payload,
        selectedOperation,
        selectedOperation.operation_id,
        fingerprint,
        await requestSha256(requestWithoutFingerprint),
        await optionsSha256(requestWithoutFingerprint),
        sourceIdentity,
        typeof previewPayload?.catalog_digest === "string" ? previewPayload.catalog_digest : "",
      );
      if (invalid) {
        if (result.payload && result.payload.status !== "completed") {
          setStatus("error");
          return;
        }
        setError(invalid);
        setStatus("error");
        return;
      }
      setStatus("complete");
    } catch (reason: unknown) {
      if (requestRevision.current !== revision) return;
      setError(reason instanceof Error ? reason.message : String(reason));
      setStatus("error");
    }
  }

  return (
    <section aria-label="Data operations" data-testid="data-operations-section">
      <ProfilePanel
        rawProfile={normalizedProfile}
        status={effectiveProfileStatus}
        canEdit={metadataOperation !== undefined}
        onEdit={editProfileMetadata}
      />
      {unavailableOperations.map((operation) => (
        <div key={operation.operation_id} data-testid="data-operation-unavailable">
          {operation.operation_id}: {"availability" in operation && isObject(operation.availability)
            ? `${String(operation.availability.reason_code)} — ${String(operation.availability.message)}`
            : `${String(operation.reason_code)} — ${String(operation.message)}`}
        </div>
      ))}

      {availableOperations.length > 0 && (
        <label htmlFor="data-operation-select">
          Data operation
          <select
            id="data-operation-select"
            aria-label="Data operation"
            value={selectedOperationId}
            onChange={(event) => selectOperation(event.target.value)}
          >
            <option value="">Select operation</option>
            {availableOperations.map((operation) => (
              <option key={operation.operation_id} value={operation.operation_id}>
                {operation.operation_id}
              </option>
            ))}
          </select>
        </label>
      )}

      {selectedOperation && (
        <div data-testid="data-operation-fields">
          {Object.entries(selectedOperation.request_schema.properties)
            .filter(([name]) =>
              !DATA_OPERATION_SOURCE_IDENTITY_FIELDS.includes(name as (typeof DATA_OPERATION_SOURCE_IDENTITY_FIELDS)[number]) &&
              !(selectedOperation.operation_id === "data.metadata.update" && name === "metadata"),
            )
            .map(([name, schema]) => (
              <OperationField
                key={name}
                name={name}
                schema={schema}
                value={values[name] ?? initialValue(schema)}
                onChange={(value) => changeValue(name, value)}
              />
            ))}
        </div>
      )}

      {selectedOperation?.operation_id === "data.metadata.update" && normalizedProfile && (
        <MetadataEditor
          profile={normalizedProfile}
          metadata={
            isObject(values.metadata)
              ? (values.metadata as DataMetadataUpdateV1)
              : profileMetadata(normalizedProfile)
          }
          onChange={(metadata) => changeValue("metadata", metadata)}
        />
      )}

      {selectedOperation && (
        <div>
          <button
            type="button"
            data-testid="data-operation-preview"
            disabled={status === "previewing" || status === "confirming"}
            onClick={() => void handlePreview()}
          >
            {status === "previewing" ? "Previewing…" : "Preview operation"}
          </button>
          {readyFingerprint(previewPayload) && (
            <button
              type="button"
              data-testid="data-operation-confirm"
              disabled={status === "confirming"}
              onClick={() => void handleConfirm()}
            >
              {status === "confirming" ? "Confirming…" : "Confirm operation"}
            </button>
          )}
        </div>
      )}

      {readyFingerprint(previewPayload) && (
        <div data-testid="data-operation-preview-ready">
          Preview ready: {readyFingerprint(previewPayload)}
        </div>
      )}
      {previewPayload && previewPayload.status !== "ready" && (
        <div data-testid="data-operation-preview-result">{previewPayload.status}</div>
      )}
      {confirmPayload && confirmPayload.status !== "completed" && (
        <div data-testid="data-operation-result">{confirmResultText(confirmPayload)}</div>
      )}
      {error && <div data-testid="data-operation-error">{error}</div>}
      {status === "complete" && (
        <div data-testid="data-operation-complete">completed</div>
      )}
    </section>
  );
}

export function DataOperationsSection(props: DataOperationsSectionProps) {
  const sourceIdentity = resolveSourceIdentity(props);

  try {
    const manifest = parseDataOperationManifest(props.manifest);
    assertSourceIdentity(manifest, sourceIdentity);
    return (
      <ParsedDataOperationsSection
        manifest={manifest}
        projectRoot={props.projectRoot}
        preview={props.preview}
        confirm={props.confirm}
        sourceIdentity={sourceIdentity}
        profile={props.profile}
        profileStatus={props.profileStatus ?? (props.profile ? "available" : "unavailable")}
      />
    );
  } catch (reason: unknown) {
    const error =
      reason instanceof DataOperationManifestError
        ? reason
        : new Error(reason instanceof Error ? reason.message : String(reason));
    const code = reason instanceof DataOperationManifestError ? reason.code : "MANIFEST_INVALID";
    return (
      <section aria-label="Data operations">
        <div role="alert" data-testid="data-operations-error">
          {code}: {error.message}
        </div>
      </section>
    );
  }
}
