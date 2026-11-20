type EngineProvenance = {
  requested: string;
  used: string;
  reason?: string;
  bit_identical_to_reference?: boolean;
  build_identity_sha256?: string;
};

/** One unknown boundary shared by result views; never inspect the full build. */
export function parseEngineProvenance(value: unknown): EngineProvenance | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.requested !== "string" || !record.requested || typeof record.used !== "string" || !record.used) return null;
  const provenance: EngineProvenance = {requested: record.requested.slice(0, 128), used: record.used.slice(0, 128)};
  if (typeof record.reason === "string" && record.reason) {
    provenance.reason = record.reason.slice(0, 500) + (record.reason.length > 500 ? "…" : "");
  }
  if (typeof record.bit_identical_to_reference === "boolean") provenance.bit_identical_to_reference = record.bit_identical_to_reference;
  if (typeof record.build_identity_sha256 === "string" && /^[0-9a-f]{64}$/i.test(record.build_identity_sha256)) {
    provenance.build_identity_sha256 = record.build_identity_sha256;
  }
  return provenance;
}

export function EngineProvenanceNotice({modelId, value}: {modelId: string; value: unknown}) {
  const provenance = parseEngineProvenance(value);
  if (!provenance) return null;
  return <aside aria-label={`Estimation engine for ${modelId}`} style={{display: "flex", flexDirection: "column", gap: 4, minWidth: 0, fontSize: 12, color: "var(--label-secondary)", overflowWrap: "anywhere"}}>
    <div className="engine-provenance-notice__row">
      <strong>Model: {modelId}</strong>
      <p>Requested engine: {provenance.requested}</p>
      <p>Actual engine: {provenance.used}</p>
    </div>
    <div className="engine-provenance-notice__row">
      {provenance.reason && <p>{provenance.reason}</p>}
      {provenance.bit_identical_to_reference !== undefined && <p>Bit-identical to reference: {provenance.bit_identical_to_reference ? "yes" : "no"}</p>}
      {provenance.build_identity_sha256 && <details><summary>Build identity SHA256</summary><code>{provenance.build_identity_sha256}</code></details>}
      {provenance.requested === "fast" && <p>Experimental fast IV; resource acceptance pending.</p>}
    </div>
  </aside>;
}
