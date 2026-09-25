import { Fragment, useEffect, useRef, useState } from "react";
import { apiUrl, readResponse } from "../api";
import { MAX_PAGE_BYTES, MAX_BUNDLE_BYTES, ResultPageAccumulatorV1 } from "./resultPages";
import { isResultDirectorySection, readResultSectionBundle, REPORT_LOCAL_POLICY, RESULT_SECTIONS_DIGEST, ResultReadError,
  type ReadResultSection, type ResolvedSectionContent, type ResultDirectoryAnchor } from "./reportEvidence";

const MAX_SECTION_BYTES = 1048576; // Same ceiling as the ordinary Report parser.
const MAX_READ_PAGES = 4096;
const IDENTITY_KEYS = ["actor_ref", "project_ref", "session_ref", "scope_ref", "run_id", "model_run_id", "confirmation_ref"];
const SOURCE_KEYS = ["artifact_ref", "commit_id", "envelope_digest"];
const encoder = new TextEncoder();
type Wire = Record<string, unknown>;
function check(ok: unknown, message: string, code = "RESULT_READ_INVALID"): asserts ok {
  if (!ok) throw new ResultReadError(code, message);
}
function object(v: unknown): asserts v is Wire { check(v !== null && typeof v === "object" && !Array.isArray(v), "Expected object"); }
function fields(v: unknown, keys: readonly string[]): asserts v is Wire {
  object(v); check(Object.keys(v).length === keys.length && keys.every(k => Object.prototype.hasOwnProperty.call(v, k)), "Unexpected wire fields");
}
function string(v: unknown): asserts v is string {
  check(typeof v === "string" && v.length > 0 && encoder.encode(v).length <= 4096 && !v.includes("\0"), "Invalid identity text");
}
function digest(v: unknown): asserts v is string { check(typeof v === "string" && /^[0-9a-f]{64}$/.test(v), "Invalid digest"); }
function count(v: unknown, max: number) { check(Number.isSafeInteger(v) && (v as number) >= 0 && (v as number) <= max, "Invalid budget", "RESULT_READ_LIMIT"); }

/** Receipt canonicalization is deliberately restricted to this wire's
 * strings/integers. Section/fact bytes are hashed by ResultPageAccumulatorV1. */
function canonical(value: unknown): string {
  let nodes = 0;
  const encode = (v: unknown, depth: number): string => {
    check(++nodes <= 20000 && depth <= 16, "Wire structure limit", "RESULT_READ_LIMIT");
    if (typeof v === "string") {
      check(!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(v), "Invalid Unicode");
      return JSON.stringify(v.normalize("NFC"));
    }
    if (v === null || typeof v === "boolean") return JSON.stringify(v);
    if (typeof v === "number") { check(Number.isSafeInteger(v), "Wire integers must be portable"); return JSON.stringify(v); }
    if (Array.isArray(v)) return `[${v.map(item => encode(item, depth + 1)).join(",")}]`;
    object(v);
    const entries = Object.entries(v).map(([key, item]) => [key.normalize("NFC"), item] as const);
    check(new Set(entries.map(([key]) => key)).size === entries.length, "Duplicate normalized fields");
    // Python sorts Unicode code points, not UTF-16 code units.
    entries.sort(([a], [b]) => {
      const x = Array.from(a, c => c.codePointAt(0)!), y = Array.from(b, c => c.codePointAt(0)!);
      for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
      return x.length - y.length;
    });
    return `{${entries.map(([key, item]) => `${encode(key, depth + 1)}:${encode(item, depth + 1)}`).join(",")}}`;
  };
  return encode(value, 0);
}
function equal(a: unknown, b: unknown) { return canonical(a) === canonical(b); }
async function hash(v: unknown) {
  check(globalThis.crypto?.subtle, "Web Crypto is required", "RESULT_PAGE_CRYPTO_UNAVAILABLE");
  const bytes = await crypto.subtle.digest("SHA-256", encoder.encode(canonical(v)));
  return Array.from(new Uint8Array(bytes), n => n.toString(16).padStart(2, "0")).join("");
}
async function verifyHash(v: Wire, field: string) {
  digest(v[field]); const rest = { ...v }; delete rest[field];
  check(await hash(rest) === v[field], "Receipt/delivery digest mismatch", "RESULT_READ_DIGEST_MISMATCH");
}
function local(v: Wire) {
  check(v.schema_version === 1 && v.authority === "server-owned" && v.consumer_id === "report" && v.destination === "local", "Expected version 1 report/local wire");
  for (const key of SOURCE_KEYS) string(v[key]); digest(v.envelope_digest);
}
function identity(v: unknown, keys = IDENTITY_KEYS): asserts v is Record<string, string> { fields(v, keys); keys.forEach(k => string(v[k])); }
function exactIdentity(v: unknown, expected: Readonly<Record<string, string>>, keys = IDENTITY_KEYS) {
  identity(v, keys);
  return keys.every(k => v[k] === expected[k]);
}

async function readDirectory(v: unknown, runId: string): Promise<ResultDirectoryAnchor> {
  fields(v, ["schema_version", "authority", "consumer_id", "destination", "identity", ...SOURCE_KEYS, "section_contract_digest",
    "read_completeness", "completion_scope", "sections", "directory_digest", "receipt"]);
  local(v); identity(v.identity);
  check(v.identity.run_id === runId, "Directory run differs from request", "RESULT_READ_IDENTITY_MISMATCH");
  check(v.section_contract_digest === RESULT_SECTIONS_DIGEST && v.read_completeness === "PARTIAL" && v.completion_scope === "run", "Invalid directory contract");
  check(Array.isArray(v.sections) && v.sections.length > 0 && v.sections.length <= 128 && v.sections.every(isResultDirectorySection), "Invalid section directory");
  check(new Set(v.sections.map(s => s.section_id)).size === v.sections.length, "Duplicate section");
  digest(v.directory_digest); check(await hash(v.sections) === v.directory_digest, "Directory digest mismatch", "RESULT_READ_DIGEST_MISMATCH");
  fields(v.receipt, ["schema_version", "kind", "wire_digest"]);
  check(v.receipt.schema_version === 1 && v.receipt.kind === "evidence.report.directory-receipt.v1", "Invalid directory receipt");
  digest(v.receipt.wire_digest);
  const { receipt, ...body } = v;
  check(await hash(body) === receipt.wire_digest, "Owner receipt mismatch", "RESULT_READ_DIGEST_MISMATCH");
  return v as unknown as ResultDirectoryAnchor;
}

async function readPage(v: unknown, anchor: ResultDirectoryAnchor, responseBytes: number): Promise<unknown> {
  fields(v, ["schema_version", "authority", "consumer_id", "destination", "identity", ...SOURCE_KEYS,
    "read_completeness", "completion_scope", "delivery", "audit", "receipt"]);
  local(v); identity(v.identity);
  check(exactIdentity(v.identity, anchor.identity) && SOURCE_KEYS.every(k => v[k] === anchor[k as keyof ResultDirectoryAnchor]), "Owner snapshot changed", "RESULT_READ_IDENTITY_MISMATCH");
  check(v.read_completeness === "PARTIAL" && v.completion_scope === "section", "Invalid page completeness");
  fields(v.audit, ["row_budget", "token_budget"]); count(v.audit.row_budget, 1024); count(v.audit.token_budget, 65536);
  const d = v.delivery;
  fields(d, ["schema_version", "authority", "source", "consumer_id", "destination", ...SOURCE_KEYS,
    "identity", "observed_sensitivity", "policy_ref", "audit", "page", "wire_digest"]);
  local(d); identity(d.identity, ["project_ref", "run_id", "scope_ref"]);
  check(Object.entries(d.identity).every(([k, value]) => anchor.identity[k] === value)
    && SOURCE_KEYS.every(k => d[k] === v[k]), "Delivery snapshot changed", "RESULT_READ_IDENTITY_MISMATCH");
  check(d.source === "persisted-typed-evidence-page" && ["public", "internal", "restricted", "unknown"].includes(d.observed_sensitivity as string)
    && equal(d.policy_ref, REPORT_LOCAL_POLICY), "Unexpected delivery declaration");
  fields(d.audit, ["row_budget", "token_budget", "envelope_reserve_bytes"]);
  count(d.audit.row_budget, 1024); count(d.audit.token_budget, 65536); count(d.audit.envelope_reserve_bytes, MAX_PAGE_BYTES);
  check(d.audit.row_budget === v.audit.row_budget, "Row charges differ");
  await verifyHash(d, "wire_digest");
  fields(v.receipt, ["schema_version", "kind", "identity", "provenance", "payload_digest", "wire_digest"]);
  const receipt = v.receipt;
  fields(receipt.provenance, SOURCE_KEYS);
  check(receipt.schema_version === 1 && receipt.kind === "evidence.report.page-receipt.v1"
    && exactIdentity(receipt.identity, anchor.identity) && SOURCE_KEYS.every(k => (receipt.provenance as Wire)[k] === v[k])
    && receipt.payload_digest === d.wire_digest, "Invalid owner receipt binding", "RESULT_READ_IDENTITY_MISMATCH");
  digest(receipt.wire_digest);
  const body = { ...v }; delete body.receipt;
  check(await hash(body) === receipt.wire_digest, "Owner receipt mismatch", "RESULT_READ_DIGEST_MISMATCH");
  check(Math.ceil(responseBytes / 4) <= (v.audit.token_budget as number), "Undercharged owner response", "RESULT_READ_LIMIT");
  return d.page;
}

/** Bound streamed bytes BEFORE shared readResponse parses JSON, even for error
 * responses or absent/false Content-Length. Never falls back to unbounded json(). */
async function request(path: string, signal: AbortSignal): Promise<{ value: unknown; bytes: number }> {
  const response = await fetch(apiUrl(path), { signal, credentials: "same-origin", redirect: "error" });
  const reader = response.body?.getReader();
  check(reader, "Response stream is unavailable");
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    const length = response.headers.get("Content-Length");
    if (length !== null) count(Number(length), MAX_PAGE_BYTES);
    while (true) {
      signal.throwIfAborted();
      const part = await reader.read();
      signal.throwIfAborted();
      if (part.done) break;
      size += part.value.byteLength;
      check(size <= MAX_PAGE_BYTES, "Response exceeds 262144 bytes", "RESULT_READ_LIMIT"); chunks.push(part.value);
    }
  } finally { await reader.cancel(); reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  const body = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  return { value: await readResponse(new Response(body, { status: response.status, headers: response.headers })), bytes: size };
}

/** Only receives contract-validated values. Arrays are displayed in explicit
 * 50-item windows; every item remains reachable without a large DOM mount. */
function TypedValue({ value }: { value: ResolvedSectionContent }) {
  const [start, setStart] = useState(0);
  if (value === null) return <span>null</span>;
  if (typeof value !== "object") return <span>{String(value)}</span>;
  const entries = Array.isArray(value) ? value.map((v, i) => [String(i), v] as const) : Object.entries(value);
  return <div><dl>{entries.slice(start, start + 50).map(([key, child]) => <Fragment key={key}>
    <dt>{key}</dt><dd><TypedValue value={child} /></dd></Fragment>)}</dl>
    {entries.length > 50 && <div>
      <span>Items {start + 1}–{Math.min(start + 50, entries.length)} of {entries.length}</span>
      <button type="button" disabled={start === 0} onClick={() => setStart(start - 50)}>Previous items</button>
      <button type="button" disabled={start + 50 >= entries.length} onClick={() => setStart(start + 50)}>Next items</button>
    </div>}
  </div>;
}

type SectionState = { accumulator?: ResultPageAccumulatorV1; received: number; total: number | null; result?: ReadResultSection; retry?: boolean };
/** A keyed inner mount prevents even a single render of the old scope. */
export function ResultEvidenceReader(props: { projectRoot: string; runId: string }) {
  return <ReaderSession key={JSON.stringify([props.projectRoot, props.runId])} {...props} />;
}
function ReaderSession({ projectRoot, runId }: { projectRoot: string; runId: string }) {
  const [anchor, setAnchor] = useState<ResultDirectoryAnchor | null>(null);
  const [sections, setSections] = useState<Record<string, SectionState>>({});
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [blocked, setBlocked] = useState(false);
  const [selected, setSelected] = useState<string | null>(null), [details, setDetails] = useState(false);
  const lifetime = useRef({ generation: 0, controller: null as AbortController | null, sections: new Map<string, SectionState>(), pages: 0, retained: 0 });
  function invalidate() {
    const current = lifetime.current; current.generation++; current.controller?.abort(); current.controller = null;
    current.sections.forEach(s => s.accumulator?.cancel()); current.sections.clear(); current.retained = 0;
  }
  useEffect(() => () => invalidate(), []);
  function reset() {
    invalidate(); lifetime.current.pages = 0; setAnchor(null); setSections({}); setBusy(false); setError(null); setBlocked(false); setSelected(null); setDetails(false);
  }
  async function read(sectionId?: string) {
    const state = lifetime.current;
    if (state.controller || blocked) return;
    const controller = new AbortController(), generation = state.generation;
    state.controller = controller; setBusy(true); setError(null);
    const timer = setTimeout(() => controller.abort(), 30000);
    const current = () => generation === state.generation && state.controller === controller;
    try {
      check(++state.pages <= MAX_READ_PAGES, "4096 request ceiling; reset to start a new reading", "RESULT_READ_LIMIT");
      const query = new URLSearchParams({ project_root: projectRoot });
      if (!sectionId) {
        const raw = await request(`/runs/${encodeURIComponent(runId)}/results/directory?${query}`, controller.signal);
        const directory = await readDirectory(raw.value, runId);
        if (current()) setAnchor(directory);
      } else {
        check(anchor, "Read a directory first");
        const previous = state.sections.get(sectionId) ?? { received: 0, total: null };
        const accumulator = previous.accumulator ?? new ResultPageAccumulatorV1({ source_ref: anchor.artifact_ref,
          source_digest: anchor.envelope_digest, section_id: sectionId, consumer_id: "report", destination: "local" }, { maxTotalBytes: MAX_SECTION_BYTES });
        const entry: SectionState = { ...previous, accumulator, retry: false }; state.sections.set(sectionId, entry);
        query.set("section_id", sectionId); query.set("offset", String(entry.received)); query.set("max_wire_bytes", String(MAX_PAGE_BYTES));
        const raw = await request(`/runs/${encodeURIComponent(runId)}/results/page?${query}`, controller.signal);
        const page = await readPage(raw.value, anchor, raw.bytes);
        if (!current()) return;
        object(page); count(page.total_bytes, MAX_SECTION_BYTES);
        const pendingBytes = [...state.sections.values()].reduce((sum, s) => sum + (s.accumulator?.state.totalBytes ?? 0), 0);
        check(state.retained + pendingBytes + (entry.total === null ? page.total_bytes as number : 0) <= MAX_BUNDLE_BYTES, "Local retained-data ceiling", "RESULT_READ_LIMIT");
        await accumulator.add(page);
        if (!current()) return;
        entry.received = accumulator.state.receivedBytes; entry.total = accumulator.state.totalBytes;
        if (accumulator.state.readCompleteness === "COMPLETE") {
          const result = readResultSectionBundle(accumulator.finish(), anchor, sectionId);
          const retained = encoder.encode(JSON.stringify(result)).length;
          check(state.retained + retained + pendingBytes <= MAX_BUNDLE_BYTES, "Local retained-data ceiling", "RESULT_READ_LIMIT");
          state.retained += retained; entry.result = result; accumulator.cancel(); entry.accumulator = undefined;
          setSelected(sectionId); setDetails(false);
        }
        setSections(Object.fromEntries(state.sections));
      }
    } catch (cause) {
      if (!current()) return;
      const code = cause instanceof Error && "code" in cause && typeof cause.code === "string" ? cause.code : null;
      const retryable = !code && (cause instanceof TypeError || controller.signal.aborted);
      setError(`${code ?? (retryable ? "RESULT_READ_INTERRUPTED" : "RESULT_READ_INVALID")}: ${cause instanceof Error ? cause.message : "Read failed"}`);
      if (retryable && sectionId) {
        const entry = state.sections.get(sectionId); if (entry) entry.retry = true;
        setSections(Object.fromEntries(state.sections));
      } else if (!retryable) {
        // A changed/tampered snapshot invalidates ALL completed reading claims.
        invalidate(); setSections({}); setSelected(null); setBlocked(true);
      }
    } finally {
      clearTimeout(timer);
      if (current()) { state.controller = null; setBusy(false); }
      else if (generation === state.generation - 1 && state.controller === null) setBusy(false);
    }
  }
  const complete = anchor !== null && anchor.sections.every(s => sections[s.section_id]?.result);
  const shown = selected ? sections[selected]?.result : undefined;
  return <section aria-label="Formal result reader" aria-busy={busy}>
    <h3>Formal result reader</h3>
    <p>Run {runId}. Local reading only; no bulk content is sent to the writer.</p>
    <p>Identity is admitted by the local backend. Hashes check consistency, not independent authentication.</p>
    <p>COMPLETE means all directory sections were read from this snapshot, not statistical validation or current-source revalidation.</p>
    <p role="status" data-testid="run-read-completeness">Run reading: {complete ? "COMPLETE" : "PARTIAL"}</p>
    <button type="button" disabled={busy || blocked || !!anchor || !projectRoot || !runId} onClick={() => void read()}>Read directory</button>
    <button type="button" onClick={reset}>Reset reading</button>
    {error && <p role="alert">{error}</p>}
    {anchor && <><p>Artifact {anchor.artifact_ref} · Commit {anchor.commit_id} · Envelope {anchor.envelope_digest}</p>
      <ul>{anchor.sections.map(s => {
        const entry = sections[s.section_id];
        return <li key={s.section_id}>
          <span>{s.section_id} · {s.section_type} · {s.status} {s.reason_codes.join(" · ")}</span>
          <p data-testid={`section-read-${s.section_id}`}>Section reading: {entry?.result ? "COMPLETE" : "PARTIAL"} · {entry?.received ?? 0}/{entry?.total ?? "?"} bytes</p>
          {entry?.result ? <button type="button" onClick={() => { setSelected(s.section_id); setDetails(false); }}>Show {s.section_id}</button>
            : <button type="button" disabled={busy || blocked} onClick={() => void read(s.section_id)}>
              {entry?.retry ? "Resume" : entry?.received ? "Load next" : "Read"} {s.section_id}</button>}
        </li>;
      })}</ul></>}
    {shown && <section aria-label={`Result section ${shown.section.sectionId}`}>
      <h4>{shown.section.sectionType} · {shown.section.status}</h4>
      <TypedValue key={selected} value={shown.section.content} />
      <button type="button" aria-expanded={details} onClick={() => setDetails(!details)}>Facts, references and provenance</button>
      {details && <TypedValue key={`${selected}-details`} value={{ facts: shown.facts, dependencies: shown.dependencies,
        metadata: shown.metadata, resultIdentity: shown.resultIdentity, structuredSection: shown.structuredSection }} />}
    </section>}
  </section>;
}
