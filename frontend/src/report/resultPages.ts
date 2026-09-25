/** Lossless transport only: hashes/coverage are not source authority, section
 * validation, or run completeness. Callers must retain their own UI/schema cap. */
export const MAX_PAGE_BYTES = 262144;
export const MAX_BUNDLE_BYTES = 16 * 1024 * 1024;

export interface ResultPageBindingV1 {
  readonly source_ref: string;
  readonly source_digest: string;
  readonly section_id: string;
  readonly consumer_id: string;
  readonly destination: "local" | "remote";
}

export interface ResultPageV1 {
  readonly schema_version: 1;
  readonly binding: ResultPageBindingV1;
  readonly bundle_digest: string;
  readonly offset: number;
  readonly total_bytes: number;
  readonly next_offset: number | null;
  readonly payload_base64: string;
  readonly page_digest: string;
}

export interface ResultPageProgressV1 {
  readonly readCompleteness: "PARTIAL" | "COMPLETE";
  readonly receivedBytes: number;
  readonly totalBytes: number | null;
}

export class ResultPageError extends Error {
  constructor(readonly code: string, message: string) {
    super(`${code}: ${message}`);
    this.name = "ResultPageError";
  }
}

function fail(message: string, code = "RESULT_PAGE_INVALID"): never {
  throw new ResultPageError(code, message);
}

const encoder = new TextEncoder();
const bindingKeys = ["source_ref", "source_digest", "section_id", "consumer_id", "destination"] as const;
const pageKeys = ["schema_version", "binding", "bundle_digest", "offset", "total_bytes",
  "next_offset", "payload_base64", "page_digest"] as const;

function exactFields(value: unknown, keys: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail("expected a JSON object");
  const ownKeys = Reflect.ownKeys(value);
  if (ownKeys.length !== keys.length || ownKeys.some(key => typeof key !== "string" || !keys.includes(key))) {
    fail("fields differ from the versioned declaration");
  }
  // Snapshot plain data before any await; do not retain input/getter references.
  const copy: Record<string, unknown> = {};
  for (const key of keys) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor || !("value" in descriptor)) fail("page fields must be data properties");
    copy[key] = descriptor.value;
  }
  return copy;
}

function integer(value: unknown, minimum: number, maximum: number): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) {
    fail("integer is outside the declared range");
  }
  return value;
}

function digest(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) fail("expected a canonical SHA-256 digest");
  return value;
}

function bindingValue(value: unknown): ResultPageBindingV1 {
  const fields = exactFields(value, bindingKeys);
  const normalized: Record<string, string> = {};
  for (const key of bindingKeys) {
    const text = fields[key];
    if (typeof text !== "string" || !text || text.length > 4096 || text.includes("\0")) fail("binding text is invalid");
    for (const char of text) {
      const point = char.codePointAt(0)!;
      if (point >= 0xd800 && point <= 0xdfff) fail("binding contains invalid Unicode");
    }
    if (encoder.encode(text).byteLength > 4096) fail("binding text exceeds its byte limit");
    normalized[key] = text.normalize("NFC");
  }
  digest(fields.source_digest);
  if (normalized.destination !== "local" && normalized.destination !== "remote") fail("unknown page destination");
  return Object.freeze({ source_ref: normalized.source_ref, source_digest: normalized.source_digest,
    section_id: normalized.section_id, consumer_id: normalized.consumer_id, destination: normalized.destination });
}

/** Canonical JSON v1 for this exact, fixed-key string/integer-only schema.
 * No general statistical JSON parser or serializer is introduced here. */
function canonicalPage(page: ResultPageV1, withDigest: boolean): string {
  const b = page.binding;
  return JSON.stringify({
    binding: { consumer_id: b.consumer_id, destination: b.destination, section_id: b.section_id,
      source_digest: b.source_digest, source_ref: b.source_ref },
    bundle_digest: page.bundle_digest, next_offset: page.next_offset, offset: page.offset,
    ...(withDigest ? { page_digest: page.page_digest } : {}),
    payload_base64: page.payload_base64, schema_version: 1, total_bytes: page.total_bytes,
  });
}

function preparePage(value: unknown, limit = MAX_BUNDLE_BYTES) {
  const fields = exactFields(value, pageKeys);
  if (fields.schema_version !== 1) fail("unknown page version", "UNSUPPORTED_VERSION");
  const binding = bindingValue(fields.binding);
  const total = integer(fields.total_bytes, 1, MAX_BUNDLE_BYTES);
  if (total > limit) fail("declared bundle exceeds the receiver ceiling");
  const offset = integer(fields.offset, 0, total - 1);
  const next = fields.next_offset === null ? null : integer(fields.next_offset, 1, total - 1);
  const payload = fields.payload_base64;
  if (typeof payload !== "string" || !payload || payload.length > MAX_PAGE_BYTES
      || payload.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(payload)) fail("invalid base64 payload");
  const page: ResultPageV1 = Object.freeze({ schema_version: 1, binding,
    bundle_digest: digest(fields.bundle_digest), offset, total_bytes: total, next_offset: next,
    payload_base64: payload, page_digest: digest(fields.page_digest) });
  if (encoder.encode(canonicalPage(page, true)).byteLength > MAX_PAGE_BYTES) fail("page exceeds the transport ceiling");
  let binary: string;
  try { binary = atob(payload); } catch { fail("invalid base64 payload"); }
  if (btoa(binary) !== payload) fail("noncanonical base64 payload");
  const end = offset + binary.length;
  if (!binary.length || end > total || next !== (end === total ? null : end)) fail("continuation differs from the exact byte interval");
  return { page, payload: Uint8Array.from(binary, char => char.charCodeAt(0)) };
}

async function sha256(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const browserCrypto = globalThis.crypto;
  if (!browserCrypto?.subtle) fail("browser Web Crypto is required", "RESULT_PAGE_CRYPTO_UNAVAILABLE");
  const result = await browserCrypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(result), byte => byte.toString(16).padStart(2, "0")).join("");
}

async function verifyPage(page: ResultPageV1): Promise<void> {
  if (await sha256(encoder.encode(canonicalPage(page, false))) !== page.page_digest) fail("page digest mismatch");
}

export async function parseResultPageV1(value: unknown): Promise<ResultPageV1> {
  const { page } = preparePage(value);
  await verifyPage(page);
  return page;
}

/** One bounded section snapshot. Concurrent add is rejected (not queued).
 * reset/cancel invalidate pending digest work; Web Crypto itself is not abortable.
 * finish returns defensive bytes, never decoded or statistically validated data. */
export class ResultPageAccumulatorV1 {
  #binding: ResultPageBindingV1;
  readonly #limit: number;
  #data: Uint8Array<ArrayBuffer> | null = null;
  #received = 0;
  #total: number | null = null;
  #digest: string | null = null;
  #complete = false;
  #busy = false;
  #cancelled = false;
  #generation = 0;

  constructor(binding: unknown, options: { readonly maxTotalBytes: number }) {
    this.#binding = bindingValue(binding);
    this.#limit = integer(options?.maxTotalBytes, 1, MAX_BUNDLE_BYTES);
  }

  get state(): ResultPageProgressV1 {
    return Object.freeze({ readCompleteness: this.#complete ? "COMPLETE" : "PARTIAL",
      receivedBytes: this.#received, totalBytes: this.#total });
  }

  async add(value: unknown): Promise<void> {
    if (this.#cancelled) fail("receiver is cancelled", "RESULT_PAGE_CANCELLED");
    if (this.#busy) fail("await the active add before adding another page", "RESULT_PAGE_BUSY");
    if (this.#complete) fail("transport is already complete");
    const generation = this.#generation;
    this.#busy = true;
    try {
      const { page, payload } = preparePage(value, this.#limit);
      if (bindingKeys.some(key => page.binding[key] !== this.#binding[key]) || page.offset !== this.#received) {
        fail("mixed binding, duplicate or noncontiguous page");
      }
      if (this.#total !== null && (page.total_bytes !== this.#total || page.bundle_digest !== this.#digest)) {
        fail("bundle identity changed between pages");
      }
      await verifyPage(page);
      this.#assertGeneration(generation);
      const data = this.#data ?? new Uint8Array(page.total_bytes);
      data.set(payload, page.offset);
      if (page.next_offset === null) {
        const checksum = await sha256(data);
        this.#assertGeneration(generation);
        if (checksum !== page.bundle_digest) fail("complete byte coverage has a different bundle digest");
      }
      this.#data = data;
      this.#received = page.offset + payload.length;
      this.#total = page.total_bytes;
      this.#digest = page.bundle_digest;
      this.#complete = page.next_offset === null;
    } finally {
      // A cancelled older operation cannot unlock a newer in-flight add.
      if (generation === this.#generation) this.#busy = false;
    }
  }

  finish(): Uint8Array {
    if (this.#cancelled) fail("receiver is cancelled", "RESULT_PAGE_CANCELLED");
    if (!this.#complete || this.#busy || this.#data === null || this.#received !== this.#total) {
      fail("transport coverage is partial", "RESULT_PAGE_INCOMPLETE");
    }
    return this.#data.slice();
  }

  cancel(): void {
    this.#clear();
    this.#cancelled = true;
  }

  reset(binding: unknown): void {
    const next = bindingValue(binding);
    this.#clear();
    this.#binding = next;
    this.#cancelled = false;
  }

  #assertGeneration(generation: number): void {
    if (generation !== this.#generation) fail("snapshot was reset or cancelled", "RESULT_PAGE_CANCELLED");
  }

  #clear(): void {
    this.#generation += 1;
    this.#data = null;
    this.#received = 0;
    this.#total = null;
    this.#digest = null;
    this.#complete = false;
    this.#busy = false;
  }
}
