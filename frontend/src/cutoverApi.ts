import { apiUrl, readResponse } from "./api";

const IDENTITY_SCHEMA = "agent-notebook-cutover-identity.v1" as const;
const PREVIEW_SCHEMA = "cutover-compilation-preview.v1" as const;
const BINDING_SCHEMA = "server-proposal-binding.v1" as const;
const CONFIRMATION_SCHEMA = "server-confirmation-receipt.v1" as const;
const RESULT_SCHEMA = "cutover-execution-result.v1" as const;
const SHA256_PATTERN = /^[0-9a-f]{64}$/i;
const CLARIFICATION_CODES = new Set([
  "missing_required_information",
  "ambiguous_request",
  "unsafe_instruction",
  "no_eligible_capability",
  "stale_source",
]);

export interface CutoverIdentityV1 {
  schema_version: typeof IDENTITY_SCHEMA;
  actor_ref: string;
  session_ref: string;
  project_ref: string;
}

export interface CutoverPreviewV1 {
  schema_version: typeof PREVIEW_SCHEMA;
  entrypoint: "agent" | "notebook";
  operation_id: string | null;
  compilation_record_id: string | null;
  record_digest: string | null;
  semantic_plan_hash: string | null;
  server_execution_identity: string | null;
  preview_fingerprint: string | null;
  plan_diff: Record<string, unknown>;
  clarifications: CutoverClarificationV1[];
}

export interface CutoverClarificationV1 {
  code: string;
  field: string;
  message: string;
  allowed_values: string[];
}

export interface CutoverBindingV1 {
  schema_version: typeof BINDING_SCHEMA;
  proposal_id: string;
  proposal_revision: number;
  proposal_fingerprint: string;
  semantic_plan_hash: string;
  actor_ref: string;
  session_ref: string;
  project_ref: string;
  confirmation_id: string;
  compilation_record_id: string;
}

export interface CutoverCompileResponseV1 {
  preview: CutoverPreviewV1;
  binding?: CutoverBindingV1;
}

export interface CutoverConfirmationV1 {
  schema_version: typeof CONFIRMATION_SCHEMA;
  confirmation_id: string;
  confirmation_digest: string;
  compilation_record_id: string;
  proposal_id: string;
  proposal_revision: number;
  proposal_fingerprint: string;
  semantic_plan_hash: string;
  actor_ref: string;
  session_ref: string;
  project_ref: string;
}

export interface CutoverExecutionResultV1 {
  schema_version: typeof RESULT_SCHEMA;
  operation_id: string;
  compilation_record_id: string;
  execution_instance_hash: string;
  status: string;
  result: Record<string, unknown>;
  evidence_refs: string[];
}

export class CutoverContractError extends Error {
  readonly code: "UNSUPPORTED_VERSION" | "CUTOVER_CONTRACT_INVALID";

  constructor(
    code: "UNSUPPORTED_VERSION" | "CUTOVER_CONTRACT_INVALID",
    message: string,
  ) {
    super(message);
    this.name = "CutoverContractError";
    this.code = code;
  }
}

function invalid(message: string): never {
  throw new CutoverContractError("CUTOVER_CONTRACT_INVALID", message);
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    invalid(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function schema(value: Record<string, unknown>, expected: string, label: string): void {
  const actual = value.schema_version;
  if (actual !== expected) {
    if (typeof actual === "string") {
      throw new CutoverContractError(
        "UNSUPPORTED_VERSION",
        `${label} uses unsupported schema ${actual}`,
      );
    }
    invalid(`${label}.schema_version is required`);
  }
}

function stringField(value: Record<string, unknown>, field: string, label: string): string {
  const candidate = value[field];
  if (
    typeof candidate !== "string"
    || candidate.length === 0
    || candidate !== candidate.trim()
    || candidate.includes("\0")
  ) invalid(`${label}.${field} must be a non-empty canonical string`);
  return candidate;
}

function nullableStringField(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string | null {
  if (value[field] === null) return null;
  return stringField(value, field, label);
}

function integerField(value: Record<string, unknown>, field: string, label: string): number {
  const candidate = value[field];
  if (!Number.isInteger(candidate) || Number(candidate) <= 0) {
    invalid(`${label}.${field} must be a positive integer`);
  }
  return Number(candidate);
}

function digestField(value: Record<string, unknown>, field: string, label: string): string {
  const candidate = stringField(value, field, label);
  if (!SHA256_PATTERN.test(candidate)) invalid(`${label}.${field} must be a SHA-256 digest`);
  return candidate;
}

function nullableDigestField(
  value: Record<string, unknown>,
  field: string,
  label: string,
): string | null {
  if (value[field] === null) return null;
  return digestField(value, field, label);
}

function stringArrayField(value: Record<string, unknown>, field: string, label: string): string[] {
  const candidate = value[field];
  if (!Array.isArray(candidate)) invalid(`${label}.${field} must be an array`);
  return candidate.map((item, index) => {
    if (typeof item !== "string" || !item.trim() || item !== item.trim() || item.includes("\0")) {
      invalid(`${label}.${field}[${index}] must be a non-empty canonical string`);
    }
    return item;
  });
}

function parseClarification(value: unknown, index: number): CutoverClarificationV1 {
  const label = `preview.clarifications[${index}]`;
  const source = record(value, label);
  const code = stringField(source, "code", label);
  if (!CLARIFICATION_CODES.has(code)) invalid(`${label}.code is not in the v1 vocabulary`);
  const allowedValues = stringArrayField(source, "allowed_values", label);
  if (new Set(allowedValues).size !== allowedValues.length) {
    invalid(`${label}.allowed_values must not contain duplicates`);
  }
  return {
    code,
    field: stringField(source, "field", label),
    message: stringField(source, "message", label),
    allowed_values: allowedValues,
  };
}

function parseIdentity(value: unknown): CutoverIdentityV1 {
  const source = record(value, "identity");
  schema(source, IDENTITY_SCHEMA, "identity");
  return {
    schema_version: IDENTITY_SCHEMA,
    actor_ref: stringField(source, "actor_ref", "identity"),
    session_ref: stringField(source, "session_ref", "identity"),
    project_ref: stringField(source, "project_ref", "identity"),
  };
}

function parsePreview(value: unknown, expectedEntrypoint: "agent" | "notebook"): CutoverPreviewV1 {
  const source = record(value, "preview");
  schema(source, PREVIEW_SCHEMA, "preview");
  if (source.entrypoint !== expectedEntrypoint) invalid(`preview.entrypoint must be ${expectedEntrypoint}`);
  const planDiff = record(source.plan_diff, "preview.plan_diff");
  if (!Array.isArray(source.clarifications)) invalid("preview.clarifications must be an array");
  const clarifications = source.clarifications.map(parseClarification);
  const preview: CutoverPreviewV1 = {
    schema_version: PREVIEW_SCHEMA,
    entrypoint: expectedEntrypoint,
    operation_id: nullableStringField(source, "operation_id", "preview"),
    compilation_record_id: nullableStringField(source, "compilation_record_id", "preview"),
    record_digest: nullableDigestField(source, "record_digest", "preview"),
    semantic_plan_hash: nullableDigestField(source, "semantic_plan_hash", "preview"),
    server_execution_identity: nullableStringField(source, "server_execution_identity", "preview"),
    preview_fingerprint: nullableDigestField(source, "preview_fingerprint", "preview"),
    plan_diff: planDiff,
    clarifications,
  };
  const executableFields = [
    preview.operation_id,
    preview.compilation_record_id,
    preview.record_digest,
    preview.semantic_plan_hash,
    preview.server_execution_identity,
    preview.preview_fingerprint,
  ];
  if (clarifications.length > 0 && executableFields.some((item) => item !== null)) {
    invalid("a clarification preview cannot expose executable identity fields");
  }
  if (clarifications.length === 0 && executableFields.some((item) => item === null)) {
    invalid("a preview without clarifications must expose complete executable identity");
  }
  return preview;
}

function parseBinding(value: unknown): CutoverBindingV1 {
  const source = record(value, "binding");
  schema(source, BINDING_SCHEMA, "binding");
  return {
    schema_version: BINDING_SCHEMA,
    proposal_id: stringField(source, "proposal_id", "binding"),
    proposal_revision: integerField(source, "proposal_revision", "binding"),
    proposal_fingerprint: digestField(source, "proposal_fingerprint", "binding"),
    semantic_plan_hash: digestField(source, "semantic_plan_hash", "binding"),
    actor_ref: stringField(source, "actor_ref", "binding"),
    session_ref: stringField(source, "session_ref", "binding"),
    project_ref: stringField(source, "project_ref", "binding"),
    confirmation_id: stringField(source, "confirmation_id", "binding"),
    compilation_record_id: stringField(source, "compilation_record_id", "binding"),
  };
}

function parseConfirmation(value: unknown): CutoverConfirmationV1 {
  const source = record(value, "confirmation");
  schema(source, CONFIRMATION_SCHEMA, "confirmation");
  return {
    schema_version: CONFIRMATION_SCHEMA,
    confirmation_id: stringField(source, "confirmation_id", "confirmation"),
    confirmation_digest: digestField(source, "confirmation_digest", "confirmation"),
    compilation_record_id: stringField(source, "compilation_record_id", "confirmation"),
    proposal_id: stringField(source, "proposal_id", "confirmation"),
    proposal_revision: integerField(source, "proposal_revision", "confirmation"),
    proposal_fingerprint: digestField(source, "proposal_fingerprint", "confirmation"),
    semantic_plan_hash: digestField(source, "semantic_plan_hash", "confirmation"),
    actor_ref: stringField(source, "actor_ref", "confirmation"),
    session_ref: stringField(source, "session_ref", "confirmation"),
    project_ref: stringField(source, "project_ref", "confirmation"),
  };
}

function parseExecutionResult(value: unknown): CutoverExecutionResultV1 {
  const source = record(value, "result");
  schema(source, RESULT_SCHEMA, "result");
  const status = stringField(source, "status", "result");
  if (status !== "completed") invalid("result.status must be completed");
  const evidenceRefs = stringArrayField(source, "evidence_refs", "result");
  if (evidenceRefs.length === 0) invalid("a completed result requires evidence references");
  if (new Set(evidenceRefs).size !== evidenceRefs.length) {
    invalid("result.evidence_refs must not contain duplicates");
  }
  return {
    schema_version: RESULT_SCHEMA,
    operation_id: stringField(source, "operation_id", "result"),
    compilation_record_id: stringField(source, "compilation_record_id", "result"),
    execution_instance_hash: digestField(source, "execution_instance_hash", "result"),
    status,
    result: record(source.result, "result.result"),
    evidence_refs: evidenceRefs,
  };
}

function assertIdentityBinding(binding: CutoverBindingV1, identity: CutoverIdentityV1): void {
  if (
    binding.actor_ref !== identity.actor_ref
    || binding.session_ref !== identity.session_ref
    || binding.project_ref !== identity.project_ref
  ) invalid("binding scope does not match the server identity");
}

function parseCompileResponse(
  value: unknown,
  identity: CutoverIdentityV1,
  expectedEntrypoint: "agent" | "notebook",
): CutoverCompileResponseV1 {
  const source = record(value, "compile response");
  const preview = parsePreview(source.preview, expectedEntrypoint);
  const binding = source.binding === undefined ? undefined : parseBinding(source.binding);
  if (preview.compilation_record_id === null) {
    if (
      preview.operation_id !== null
      || preview.record_digest !== null
      || preview.semantic_plan_hash !== null
      || preview.server_execution_identity !== null
      || preview.preview_fingerprint !== null
      || binding !== undefined
    ) invalid("a clarification-only preview cannot expose executable identity or binding");
    return { preview };
  }
  if (
    preview.operation_id === null
    || preview.record_digest === null
    || preview.semantic_plan_hash === null
    || preview.server_execution_identity === null
    || preview.preview_fingerprint === null
  ) invalid("an executable preview is missing server-owned identity fields");
  if (!binding) invalid("an executable preview requires a server proposal binding");
  assertIdentityBinding(binding, identity);
  if (
    binding.compilation_record_id !== preview.compilation_record_id
    || binding.semantic_plan_hash !== preview.semantic_plan_hash
  ) invalid("preview and binding identify different compilations");
  return { preview, binding };
}

function assertConfirmationBinding(
  confirmation: CutoverConfirmationV1,
  binding: CutoverBindingV1,
  identity: CutoverIdentityV1,
): void {
  assertIdentityBinding(binding, identity);
  const equal = (
    confirmation.confirmation_id === binding.confirmation_id
    && confirmation.compilation_record_id === binding.compilation_record_id
    && confirmation.proposal_id === binding.proposal_id
    && confirmation.proposal_revision === binding.proposal_revision
    && confirmation.proposal_fingerprint === binding.proposal_fingerprint
    && confirmation.semantic_plan_hash === binding.semantic_plan_hash
    && confirmation.actor_ref === identity.actor_ref
    && confirmation.session_ref === identity.session_ref
    && confirmation.project_ref === identity.project_ref
  );
  if (!equal) invalid("confirmation does not match the displayed server proposal binding");
}

function projectQuery(projectRoot: string): string {
  return `?project_root=${encodeURIComponent(projectRoot)}`;
}

function identityBody(identity: CutoverIdentityV1) {
  return {
    actor_ref: identity.actor_ref,
    session_ref: identity.session_ref,
    project_ref: identity.project_ref,
  };
}

async function request(url: string, init?: RequestInit): Promise<unknown> {
  return readResponse<unknown>(await fetch(url, init));
}

export async function getCutoverIdentity(
  projectRoot: string,
  projectRef?: string,
): Promise<CutoverIdentityV1> {
  const query = new URLSearchParams({ project_root: projectRoot });
  if (projectRef) query.set("project_ref", projectRef);
  return parseIdentity(await request(apiUrl(`/agent/cutover/identity?${query.toString()}`)));
}

export async function compileAgentCutover(
  text: string,
  identity: CutoverIdentityV1,
  normalizedFields?: Record<string, unknown>,
): Promise<CutoverCompileResponseV1> {
  const selectedIdentity = parseIdentity(identity);
  const response = await request(apiUrl("/agent/cutover/compile"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      ...identityBody(selectedIdentity),
      entrypoint: "agent",
      ...(normalizedFields ? { normalized_fields: normalizedFields } : {}),
    }),
  });
  return parseCompileResponse(response, selectedIdentity, "agent");
}

export async function compileNotebookCutover(
  projectRoot: string,
  notebookId: string,
  text: string,
  identity: CutoverIdentityV1,
  normalizedFields?: Record<string, unknown>,
): Promise<CutoverCompileResponseV1> {
  const selectedIdentity = parseIdentity(identity);
  const response = await request(
    apiUrl(`/notebooks/${encodeURIComponent(notebookId)}/cutover/compile${projectQuery(projectRoot)}`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        ...identityBody(selectedIdentity),
        ...(normalizedFields ? { normalized_fields: normalizedFields } : {}),
      }),
    },
  );
  return parseCompileResponse(response, selectedIdentity, "notebook");
}

export async function confirmCutover(
  binding: CutoverBindingV1,
  identity: CutoverIdentityV1,
): Promise<{ confirmation: CutoverConfirmationV1 }> {
  const selectedIdentity = parseIdentity(identity);
  const selectedBinding = parseBinding(binding);
  assertIdentityBinding(selectedBinding, selectedIdentity);
  const response = record(await request(
    apiUrl(`/agent/cutover/${encodeURIComponent(selectedBinding.compilation_record_id)}/confirm`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(identityBody(selectedIdentity)),
    },
  ), "confirmation response");
  const confirmation = parseConfirmation(response.confirmation);
  assertConfirmationBinding(confirmation, selectedBinding, selectedIdentity);
  return { confirmation };
}

export async function executeCutover(
  binding: CutoverBindingV1,
  identity: CutoverIdentityV1,
  confirmation: CutoverConfirmationV1,
  options: {
    current_data_snapshot_digest?: string;
    expected_operation_id: string;
  },
): Promise<{ result: CutoverExecutionResultV1 }> {
  const selectedIdentity = parseIdentity(identity);
  const selectedBinding = parseBinding(binding);
  const selectedConfirmation = parseConfirmation(confirmation);
  const expectedOperationId = stringField(
    { expected_operation_id: options.expected_operation_id },
    "expected_operation_id",
    "execution options",
  );
  assertConfirmationBinding(selectedConfirmation, selectedBinding, selectedIdentity);
  const response = record(await request(
    apiUrl(`/agent/cutover/${encodeURIComponent(selectedBinding.compilation_record_id)}/execute`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...identityBody(selectedIdentity),
        confirmation_id: selectedConfirmation.confirmation_id,
        ...(options.current_data_snapshot_digest
          ? { current_data_snapshot_digest: options.current_data_snapshot_digest }
          : {}),
      }),
    },
  ), "execution response");
  const result = parseExecutionResult(response.result);
  if (result.compilation_record_id !== selectedBinding.compilation_record_id) {
    invalid("execution result identifies another compilation record");
  }
  if (result.operation_id !== expectedOperationId) {
    invalid("execution result identifies another operation");
  }
  return { result };
}

export function isRetryableCutoverError(error: unknown): boolean {
  const candidate = error as { code?: unknown; status?: unknown } | null;
  if (
    candidate?.code === "UNSUPPORTED_VERSION"
    || candidate?.code === "CUTOVER_CONTRACT_INVALID"
  ) return false;
  if (typeof candidate?.status === "number") {
    return [408, 429, 502, 503, 504].includes(candidate.status);
  }
  return error instanceof TypeError;
}
