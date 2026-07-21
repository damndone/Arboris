import type { CSSProperties } from "react";
import { useMemo } from "react";

export interface LlmContextSummaryProps {
  packet?: unknown;
  contextWindowTokens?: number | null;
  supports1m?: boolean | null;
}

type RecordValue = Record<string, unknown>;

type PacketDiagnostics = {
  packetRecord: RecordValue | null;
  visibilityNotice: RecordValue | null;
  artifacts: unknown[];
  redactedArtifacts: RecordValue[];
  packetChars: number | null;
  packetBytes: number | null;
  nodeKind: string | null;
  nodeStage: string | null;
  contextFingerprint: string | null;
  upstreamIncluded: boolean | null;
  upstreamCount: number | null;
  visibilityStatus: string;
  previewBudget: number | null;
  packetContextWindowTokens: number | null;
  packetSupports1m: boolean | null;
};

const mutedStyle: CSSProperties = {
  color: "var(--label-tertiary)",
  fontSize: 11,
};

export function LlmContextSummary({
  packet,
  contextWindowTokens,
  supports1m,
}: LlmContextSummaryProps) {
  const diagnostics = useMemo<PacketDiagnostics>(() => {
    const packetRecord = asRecord(packet);
    const visibilityNotice = asRecord(packetRecord?.context_visibility_notice);
    const artifacts = Array.isArray(packetRecord?.artifacts)
      ? packetRecord.artifacts
      : [];
    const redactedArtifacts = artifacts
      .map((artifact) => asRecord(artifact))
      .filter((artifact): artifact is RecordValue => {
        return (
          artifact !== null &&
          Array.isArray(artifact.redactions) &&
          artifact.redactions.some((reason) => typeof reason === "string")
        );
      });
    const serializedPacket = serializePacket(packet);
    const packetBytes =
      serializedPacket === null ? null : utf8ByteLength(serializedPacket);
    const selection = asRecord(packetRecord?.selection);
    const packetScope = asRecord(packetRecord?.packet_scope);
    const lineageSummary = asRecord(packetRecord?.lineage_summary);
    const upstreamPath = Array.isArray(lineageSummary?.upstream_path)
      ? lineageSummary.upstream_path
      : null;
    const visibilityStatus = getVisibilityStatus(
      visibilityNotice,
      redactedArtifacts,
    );
    const previewBudget = readFiniteNumber(
      visibilityNotice?.max_total_preview_chars,
    );
    const packetContextWindowTokens = readFiniteNumber(
      packetRecord?.context_window_tokens,
    );
    const packetSupports1m = readBoolean(packetRecord?.supports_1m);

    return {
      packetRecord,
      visibilityNotice,
      artifacts,
      redactedArtifacts,
      packetChars: serializedPacket === null ? null : serializedPacket.length,
      packetBytes,
      nodeKind: readString(selection?.kind),
      nodeStage: readString(selection?.stage),
      contextFingerprint: readString(packetRecord?.context_fingerprint),
      upstreamIncluded: readBoolean(packetScope?.includes_upstream_path),
      upstreamCount: upstreamPath?.length ?? null,
      visibilityStatus,
      previewBudget,
      packetContextWindowTokens,
      packetSupports1m,
    };
  }, [packet]);

  const {
    packetRecord,
    visibilityNotice,
    artifacts,
    redactedArtifacts,
    packetChars,
    packetBytes,
    nodeKind,
    nodeStage,
    contextFingerprint,
    upstreamIncluded,
    upstreamCount,
    visibilityStatus,
    previewBudget,
    packetContextWindowTokens,
    packetSupports1m,
  } = diagnostics;

  return (
    <details
      data-testid="llm-context-summary"
      style={{ marginTop: 4, fontSize: 11 }}
    >
      <summary style={{ cursor: "pointer", fontSize: 11 }}>
        Context summary
      </summary>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          marginTop: 6,
          padding: "6px 8px",
          border: "1px solid var(--separator)",
          borderRadius: 6,
        }}
      >
        <div>
          {/* "Unavailable" read as a fault and prompted "is the key broken?".
              A null here means only that the provider never declared a context
              window -- the environment-variable provider does not -- so say
              that, and say where it can be set. Filling in a token count we
              cannot verify would be worse: the app would display a capacity
              that is simply made up. */}
          Model context capacity: {formatTokens(
            contextWindowTokens ?? packetContextWindowTokens,
            { absent: "not declared by this provider" },
          )}
        </div>
        <div>Supports 1M: {formatBoolean(supports1m ?? packetSupports1m)}</div>
        <div>
          Packet version: {readString(packetRecord?.packet_version) ??
            "Unavailable"}
        </div>
        <div>Node kind/stage: {nodeKind ?? "Unavailable"} / {nodeStage ?? "Unavailable"}</div>
        <div>Context fingerprint: {contextFingerprint ?? "Unavailable"}</div>
        <div>
          Upstream path: {upstreamIncluded === true
            ? `included (${upstreamCount ?? 0} nodes)`
            : upstreamIncluded === false
              ? "not included"
              : "Unavailable"}
        </div>
        <div>
          Packet JSON characters: {packetChars === null
            ? "Unavailable"
            : packetChars.toLocaleString("en-US")}
        </div>
        <div>
          Packet size: {packetBytes === null
            ? "Unavailable"
            : `${packetBytes.toLocaleString("en-US")} bytes`}
        </div>
        <div>
          Preview budget: {previewBudget === null
            ? "Unavailable"
            : `${previewBudget.toLocaleString("en-US")} characters`}
        </div>
        <div>Artifacts: {artifacts.length.toLocaleString("en-US")}</div>
        <div>Visibility/truncation: {visibilityStatus}</div>
        <div>Visibility notice: {formatVisibilityNotice(visibilityNotice)}</div>
        <div>
          Redacted artifacts: {redactedArtifacts.length.toLocaleString("en-US")}
        </div>
        {redactedArtifacts.length > 0 ? (
          <ul style={{ ...mutedStyle, margin: "0 0 0 18px", padding: 0 }}>
            {redactedArtifacts.map((artifact, index) => (
              <li key={`${readString(artifact.name) ?? "artifact"}-${index}`}>
                {readString(artifact.name) ?? "Unnamed artifact"}
              </li>
            ))}
          </ul>
        ) : (
          <div style={mutedStyle}>No redacted artifacts reported.</div>
        )}
      </div>
    </details>
  );
}

function asRecord(value: unknown): RecordValue | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as RecordValue)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
}

function readFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function serializePacket(packet: unknown): string | null {
  try {
    const serialized = JSON.stringify(packet);
    return typeof serialized === "string" ? serialized : null;
  } catch {
    return null;
  }
}

function utf8ByteLength(value: string): number {
  const Encoder = globalThis.TextEncoder;
  if (typeof Encoder === "function") {
    try {
      return new Encoder().encode(value).byteLength;
    } catch {
      // Fall through to the capability-independent implementation.
    }
  }

  let byteLength = 0;
  for (let index = 0; index < value.length; index += 1) {
    let codePoint = value.charCodeAt(index);
    if (codePoint >= 0xd800 && codePoint <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        codePoint = 0x10000 + ((codePoint - 0xd800) << 10) + (next - 0xdc00);
        index += 1;
      } else {
        codePoint = 0xfffd;
      }
    } else if (codePoint >= 0xdc00 && codePoint <= 0xdfff) {
      codePoint = 0xfffd;
    }

    byteLength +=
      codePoint <= 0x7f
        ? 1
        : codePoint <= 0x7ff
          ? 2
          : codePoint <= 0xffff
            ? 3
            : 4;
  }
  return byteLength;
}

function formatTokens(
  value: number | null | undefined,
  options: { absent?: string } = {},
): string {
  const tokens = readFiniteNumber(value);
  return tokens === null
    ? (options.absent ?? "Unavailable")
    : `${tokens.toLocaleString("en-US")} tokens`;
}

function formatBoolean(value: boolean | null | undefined): string {
  return value === true ? "Yes" : value === false ? "No" : "Unknown";
}

function getVisibilityStatus(
  notice: RecordValue | null,
  redactedArtifacts: RecordValue[],
): string {
  if (hasExplicitTruncation(notice, redactedArtifacts)) return "truncated";
  if (!notice && redactedArtifacts.length === 0) return "not reported";
  const restrictedFields = [
    "full_datasets_included",
    "full_reports_included",
    "binary_artifacts_included",
  ];
  if (
    restrictedFields.some((field) => notice?.[field] === false) ||
      notice?.artifact_policy === "metadata_and_safe_preview_only"
  ) {
    return "restricted/safe previews";
  }
  return "reported";
}

function hasExplicitTruncation(
  notice: RecordValue | null,
  redactedArtifacts: RecordValue[],
): boolean {
  const noticeIndicatesTruncation = Object.entries(notice ?? {}).some(
    ([key, value]) => {
      if (!key.toLowerCase().includes("truncat")) return false;
      return value === true || (typeof value === "string" && value.trim() !== "");
    },
  );
  if (noticeIndicatesTruncation) return true;

  return redactedArtifacts.some((artifact) =>
    (Array.isArray(artifact.redactions) ? artifact.redactions : []).some(
      (reason) =>
        typeof reason === "string" && reason.toLowerCase().includes("truncat"),
    ),
  );
}

function formatVisibilityNotice(notice: RecordValue | null): string {
  if (!notice) return "Unavailable";
  if (
    notice.artifact_policy === "metadata_and_safe_preview_only" ||
    notice.full_datasets_included === false ||
    notice.full_reports_included === false ||
    notice.binary_artifacts_included === false
  ) {
    return "safe previews only; full datasets, reports, and binaries excluded";
  }
  return "reported";
}
