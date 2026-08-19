import { useRef, useState } from "react";
import {
  DATA_OPERATION_SOURCE_IDENTITY_FIELDS,
  DataOperationManifestError,
  type DataOperationDescriptor,
  type DataOperationFieldSchema,
  type DataOperationManifest,
  parseDataOperationManifest,
} from "../../dataOperationManifest";

export interface DataOperationSourceIdentity {
  source_run_id: string;
  source_node_id: string;
  source_artifact_id: string;
}

export type DataOperationAction = (
  projectRoot: string,
  descriptor: DataOperationDescriptor,
  request: Record<string, unknown>,
) => unknown | PromiseLike<unknown>;

export interface DataOperationsSectionProps {
  manifest: unknown;
  projectRoot: string;
  preview: DataOperationAction;
  confirm: DataOperationAction;
  sourceIdentity?: Partial<DataOperationSourceIdentity>;
  source_run_id?: string;
  source_node_id?: string;
  source_artifact_id?: string;
}

interface ResolvedSourceIdentity {
  source_run_id: string | undefined;
  source_node_id: string | undefined;
  source_artifact_id: string | undefined;
}

type OperationStatus = "idle" | "previewing" | "confirming" | "complete" | "error";

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

function readPreviewPayload(response: unknown): PreviewPayload | null {
  const candidate = isObject(response) && isObject(response.preview) ? response.preview : response;
  if (!isObject(candidate) || typeof candidate.status !== "string") return null;
  return candidate as PreviewPayload;
}

function isResponseLike(
  response: unknown,
): response is { ok?: unknown; status?: unknown; json: () => Promise<unknown> } {
  return isObject(response) && typeof response.json === "function";
}

async function readConfirmPayload(response: unknown): Promise<{
  payload: ConfirmPayload | null;
  httpStatus: number | null;
  httpOk: boolean | null;
  isHttpResponse: boolean;
}> {
  if (isResponseLike(response)) {
    const httpStatus = typeof response.status === "number" ? response.status : null;
    const httpOk = typeof response.ok === "boolean" ? response.ok : null;
    const body = await response.json();
    return {
      payload: isObject(body) && typeof body.status === "string" ? (body as ConfirmPayload) : null,
      httpStatus,
      httpOk,
      isHttpResponse: true,
    };
  }
  return {
    payload: isObject(response) && typeof response.status === "string" ? (response as ConfirmPayload) : null,
    httpStatus: null,
    httpOk: null,
    isHttpResponse: false,
  };
}

function confirmedPayloadError(
  payload: ConfirmPayload | null,
  operationId: string,
  previewFingerprint: string,
  sourceIdentity: ResolvedSourceIdentity,
): string | null {
  if (!payload || payload.status !== "completed") {
    return "CONFIRM_INVALID: confirmation did not return completed status.";
  }
  const responsePreview = payload.preview;
  if (
    !isObject(responsePreview) ||
    responsePreview.status !== "ready" ||
    responsePreview.fingerprint !== previewFingerprint ||
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
  const operation = payload.operation;
  if (
    !operation ||
    typeof operation.record_id !== "string" ||
    !operation.record_id.trim() ||
    operation.operation_id !== operationId ||
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
  for (const [field, value] of Object.entries(effect)) {
    if (!field.endsWith("_id") || typeof value !== "string") continue;
    if (bindings[field] !== value && !Object.values(bindings).includes(value)) {
      return "CONFIRM_INVALID: completed effect binding does not match the OperationRecord.";
    }
  }
  const outputs = operation.outputs;
  const ports = isObject(outputs) && isObject(outputs.ports) ? outputs.ports : null;
  const derived = ports && isObject(ports.derived) ? ports.derived : null;
  const operationRecordPort = ports && isObject(ports.operation_record) ? ports.operation_record : null;
  if (
    !derived ||
    derived.execution_key !== effect.execution_key ||
    derived.child_node_id !== effect.child_node_id ||
    (typeof effect.artifact_id === "string" && derived.artifact_id !== effect.artifact_id) ||
    !operationRecordPort ||
    operationRecordPort.record_id !== operation.record_id
  ) {
    return "CONFIRM_INVALID: typed output ports are not bound to the effect and record.";
  }
  const slots = isObject(outputs) && isObject(outputs.consumer_slots) ? outputs.consumer_slots : null;
  if (!slots) return "CONFIRM_INVALID: typed consumer slots are missing.";
  for (const slot of ["data.agent", "data.notebook", "data.report"]) {
    const value = slots[slot];
    if (!isObject(value) || value.record_id !== operation.record_id) {
      return "CONFIRM_INVALID: typed consumer slot is not bound to the OperationRecord.";
    }
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

function ParsedDataOperationsSection({
  manifest,
  projectRoot,
  preview,
  confirm,
  sourceIdentity,
}: {
  manifest: DataOperationManifest;
  projectRoot: string;
  preview: DataOperationAction;
  confirm: DataOperationAction;
  sourceIdentity: ResolvedSourceIdentity;
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
      const response = await preview(projectRoot, selectedOperation, request);
      if (requestRevision.current !== revision) return;
      const payload = readPreviewPayload(response);
      if (!payload) {
        setError("PREVIEW_INVALID: preview response is not a typed preview.");
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
        selectedOperation.operation_id,
        fingerprint,
        sourceIdentity,
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
            .filter(([name]) => !DATA_OPERATION_SOURCE_IDENTITY_FIELDS.includes(name as (typeof DATA_OPERATION_SOURCE_IDENTITY_FIELDS)[number]))
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
