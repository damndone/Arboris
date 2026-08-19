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
  for (const operation of manifest.operations) {
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
  const [status, setStatus] = useState<OperationStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const requestRevision = useRef(0);

  const selectedOperation = manifest.operations.find(
    (operation) => operation.operation_id === selectedOperationId,
  );

  function invalidatePreview() {
    requestRevision.current += 1;
    setPreviewPayload(null);
    setError(null);
    setStatus("idle");
  }

  function selectOperation(operationId: string) {
    requestRevision.current += 1;
    setSelectedOperationId(operationId);
    setValues({});
    setPreviewPayload(null);
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
    setStatus("confirming");
    try {
      await confirm(projectRoot, selectedOperation, request);
      if (requestRevision.current !== revision) return;
      setStatus("complete");
    } catch (reason: unknown) {
      if (requestRevision.current !== revision) return;
      setError(reason instanceof Error ? reason.message : String(reason));
      setStatus("error");
    }
  }

  return (
    <section aria-label="Data operations" data-testid="data-operations-section">
      <label htmlFor="data-operation-select">
        Data operation
        <select
          id="data-operation-select"
          aria-label="Data operation"
          value={selectedOperationId}
          onChange={(event) => selectOperation(event.target.value)}
        >
          <option value="">Select operation</option>
          {manifest.operations.map((operation) => (
            <option key={operation.operation_id} value={operation.operation_id}>
              {operation.operation_id}
            </option>
          ))}
        </select>
      </label>

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
