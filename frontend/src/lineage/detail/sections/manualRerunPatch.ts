export interface ManualRerunPatch {
  patch_id: string;
  patch_source: "MANUAL_EDIT";
  source_context_fingerprint: string;
  editable_schema_version: string;
  target: { owner_run_id: string; op_node_id: string; node_hash: string };
  changes: Array<{ field_id: string; old_value: unknown; new_value: unknown }>;
}

/**
 * Build an idempotency key for one exact edit.
 *
 * The source context and changed field names alone are not sufficient: a user
 * may legitimately change `logit -> probit` and then `logit -> glm:binomial`
 * on the same source node. Those are different requests and must not collide
 * in the server's manual-patch index.
 */
export function buildManualRerunPatchId(
  sourceContextFingerprint: string,
  initialValues: Record<string, unknown>,
  currentValues: Record<string, unknown>,
): string {
  const canonical = Object.keys(currentValues)
    .sort()
    .flatMap((key) => {
      const oldValue = initialValues[key];
      const newValue = currentValues[key];
      return normalizeForCompare(oldValue) === normalizeForCompare(newValue)
        ? []
        : [[key, normalizeForCompare(oldValue), normalizeForCompare(newValue)]];
    });
  let hash = 2166136261;
  for (const char of JSON.stringify(canonical)) {
    hash ^= char.charCodeAt(0);
    hash = Math.imul(hash, 16777619) >>> 0;
  }
  return `patch_${sourceContextFingerprint}_${hash.toString(16)}`;
}

export function buildManualRerunPatch(input: {
  patchId: string;
  sourceContextFingerprint: string;
  editableSchemaVersion: string;
  target: ManualRerunPatch["target"];
  initialValues: Record<string, unknown>;
  currentValues: Record<string, unknown>;
}): ManualRerunPatch | null {
  const changes = Object.keys(input.currentValues)
    .sort()
    .flatMap((key) => {
      const oldValue = input.initialValues[key];
      const newValue = input.currentValues[key];
      return normalizeForCompare(oldValue) === normalizeForCompare(newValue)
        ? []
        : [{ field_id: key, old_value: oldValue, new_value: newValue }];
    });
  if (changes.length === 0) return null;
  return {
    patch_id: input.patchId,
    patch_source: "MANUAL_EDIT",
    source_context_fingerprint: input.sourceContextFingerprint,
    editable_schema_version: input.editableSchemaVersion,
    target: input.target,
    changes,
  };
}

export function normalizeForCompare(value: unknown): string {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort()) {
      out[key] = (value as Record<string, unknown>)[key];
    }
    return JSON.stringify(out);
  }
  return JSON.stringify(value);
}
