export interface ManualRerunPatch {
  patch_id: string;
  patch_source: "MANUAL_EDIT";
  source_context_fingerprint: string;
  editable_schema_version: string;
  target: { owner_run_id: string; op_node_id: string; node_hash: string };
  changes: Array<{ field_id: string; old_value: unknown; new_value: unknown }>;
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
