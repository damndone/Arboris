import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MAX_BUNDLE_BYTES, MAX_PAGE_BYTES, ResultPageAccumulatorV1, parseResultPageV1,
} from "./resultPages";

// Real Python pack_result_page output, not a JS recreation:
// raw = 'A🧪é尾'.encode('utf-8'); source_ref = '源:e\u0301'
// pack_result_page(raw, binding=binding, offset=0, max_wire_bytes=440)
// pack_result_page(raw, binding=binding, offset=3, max_wire_bytes=1024)
const binding = {
  source_ref: "源:é", source_digest: "a".repeat(64), section_id: "统计🧪",
  consumer_id: "report", destination: "local",
};
const pythonPages = [
  { schema_version: 1, binding, bundle_digest: "d358379da219f90f843b9fe2e29363bb1d650e99504cbee1a35a81196915544f",
    offset: 0, total_bytes: 10, next_offset: 3, payload_base64: "QfCf",
    page_digest: "5b7e94331e74135d05e74463e5a48aeee0f6b939ab98da612a6a987faccb1ba2" },
  { schema_version: 1, binding, bundle_digest: "d358379da219f90f843b9fe2e29363bb1d650e99504cbee1a35a81196915544f",
    offset: 3, total_bytes: 10, next_offset: null, payload_base64: "p6rDqeWwvg==",
    page_digest: "bb629f10e6dec123d007ddd07c930fbea9375ad90fd4866e937fbfa08745b952" },
];
// Python's list(raw), constructed in the same realm as the browser receiver.
const bytes = new Uint8Array([65, 240, 159, 167, 170, 195, 169, 229, 176, 190]);
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));
const hash = (value: Uint8Array | string) => createHash("sha256").update(value).digest("hex");
function canonical(value: unknown): string {
  if (typeof value === "string") return JSON.stringify(value.normalize("NFC"));
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  return `{${Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
    .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
}
function rehash(changes: Record<string, unknown>, source = pythonPages[0]) {
  const { page_digest: _digest, ...wire } = { ...clone(source), ...changes };
  return { ...wire, page_digest: hash(canonical(wire)) };
}
function onePage(data: Uint8Array) {
  return rehash({ total_bytes: data.length, next_offset: null,
    payload_base64: Buffer.from(data).toString("base64"), bundle_digest: hash(data) });
}
beforeEach(() => vi.stubGlobal("crypto", webcrypto));
afterEach(() => vi.unstubAllGlobals());

describe("Python-compatible result page transport", () => {
  it("parses real Python wire and reconstructs a split UTF-8 character byte exactly", async () => {
    expect(MAX_PAGE_BYTES).toBe(262144);
    expect(MAX_BUNDLE_BYTES).toBe(16 * 1024 * 1024);
    const acc = new ResultPageAccumulatorV1(binding, { maxTotalBytes: 10 });
    expect(acc.state).toEqual({ readCompleteness: "PARTIAL", receivedBytes: 0, totalBytes: null });
    for (const wire of pythonPages) {
      const page = await parseResultPageV1(wire);
      expect(page).toEqual(wire);
      expect(Object.isFrozen(page)).toBe(true);
      expect(Object.isFrozen(page.binding)).toBe(true);
      await acc.add(page);
      if (wire.next_offset !== null) {
        expect(acc.state.readCompleteness).toBe("PARTIAL");
        expect(() => acc.finish()).toThrow("RESULT_PAGE_INCOMPLETE");
      }
    }
    expect(acc.state).toEqual({ readCompleteness: "COMPLETE", receivedBytes: 10, totalBytes: 10 });
    expect(acc.finish()).toEqual(bytes);
    expect(new TextDecoder("utf-8", { fatal: true }).decode(acc.finish())).toBe("A🧪é尾");
  });

  it.each([0, 2, true, "1", null])("rejects unknown/noninteger version %s explicitly", async (schema_version) => {
    await expect(parseResultPageV1({ ...pythonPages[0], schema_version })).rejects.toMatchObject({ code: "UNSUPPORTED_VERSION" });
  });

  it.each([
    { extra: true }, { binding: { ...binding, extra: true } }, { binding: { ...binding, destination: "elsewhere" } },
    { binding: { ...binding, source_ref: "" } }, { binding: { ...binding, source_ref: "\u0000" } },
    { binding: { ...binding, source_ref: "\ud800" } }, { binding: { ...binding, section_id: "🧪".repeat(1025) } },
    { binding: { ...binding, source_digest: "A".repeat(64) } }, { offset: true }, { offset: -1 }, { offset: 0.5 },
    { total_bytes: 0 }, { total_bytes: MAX_BUNDLE_BYTES + 1 }, { next_offset: null }, { next_offset: 4 },
    { payload_base64: "QfCf\n" }, { payload_base64: "" }, { payload_base64: "!QfC" },
    { payload_base64: "Zg==", total_bytes: 1, next_offset: null, page_digest: "a".repeat(64) },
    { page_digest: "b".repeat(64) }, { bundle_digest: "X".repeat(64) },
  ])("rejects malformed wire %#", async (change) => {
    await expect(parseResultPageV1({ ...pythonPages[0], ...change })).rejects.toMatchObject({ code: "RESULT_PAGE_INVALID" });
  });

  it("rejects missing fields and noncanonical base64 even with matching page hash", async () => {
    const { next_offset: _next, ...missing } = pythonPages[0];
    await expect(parseResultPageV1(missing)).rejects.toThrow("RESULT_PAGE_INVALID");
    await expect(parseResultPageV1(rehash({ payload_base64: "Zh==", total_bytes: 1, next_offset: null }))).rejects.toThrow("RESULT_PAGE_INVALID");
  });

  it("normalizes binding NFC just like Python, without normalizing payload bytes", async () => {
    const page = await parseResultPageV1({ ...pythonPages[0], binding: { ...binding, source_ref: "源:e\u0301" } });
    expect(page.binding.source_ref).toBe("源:é");
    const acc = new ResultPageAccumulatorV1({ ...binding, source_ref: "源:e\u0301" }, { maxTotalBytes: 10 });
    await acc.add(page);
    await acc.add(pythonPages[1]);
    expect(acc.finish()).toEqual(bytes);
  });

  it("enforces payload and final canonical page ceilings before hashing", async () => {
    const digest = vi.fn();
    vi.stubGlobal("crypto", { subtle: { digest } });
    await expect(parseResultPageV1({ ...pythonPages[0], payload_base64: "A".repeat(MAX_PAGE_BYTES + 4) })).rejects.toThrow("RESULT_PAGE_INVALID");
    await expect(parseResultPageV1(rehash({ payload_base64: "A".repeat(MAX_PAGE_BYTES), total_bytes: MAX_BUNDLE_BYTES }))).rejects.toThrow("RESULT_PAGE_INVALID");
    expect(digest).not.toHaveBeenCalled();
  });

  it("accepts a near-limit valid page but rejects a rehashed page beyond the full-wire ceiling", async () => {
    const large = onePage(new Uint8Array(196200).fill(65));
    expect(new TextEncoder().encode(canonical(large)).length).toBeLessThanOrEqual(MAX_PAGE_BYTES);
    await expect(parseResultPageV1(large)).resolves.toEqual(large);
    const tooLarge = onePage(new Uint8Array(196500).fill(65));
    expect(new TextEncoder().encode(canonical(tooLarge)).length).toBeGreaterThan(MAX_PAGE_BYTES);
    await expect(parseResultPageV1(tooLarge)).rejects.toThrow("RESULT_PAGE_INVALID");
  });

  it("snapshots parser input before async hashing and exposes no mutable binding", async () => {
    const input = clone(pythonPages[0]);
    const pending = parseResultPageV1(input);
    input.binding.source_digest = "b".repeat(64);
    input.payload_base64 = "AAAA";
    const parsed = await pending;
    expect(parsed).toEqual(pythonPages[0]);
    expect(() => Reflect.set(parsed.binding, "source_ref", "changed")).not.toThrow();
    expect(parsed.binding.source_ref).toBe(binding.source_ref);
  });

  it("fails closed if browser Web Crypto is unavailable", async () => {
    vi.stubGlobal("crypto", undefined);
    await expect(parseResultPageV1(pythonPages[0])).rejects.toThrow("RESULT_PAGE_CRYPTO_UNAVAILABLE");
  });
});

describe("bounded asynchronous byte accumulator", () => {
  it("rejects duplicate, gap, overlap, mixed binding/digest/total and preserves prior bytes", async () => {
    const acc = new ResultPageAccumulatorV1(binding, { maxTotalBytes: 32 });
    await expect(acc.add(pythonPages[1])).rejects.toThrow("RESULT_PAGE_INVALID");
    await acc.add(pythonPages[0]);
    const before = acc.state;
    for (const wire of [pythonPages[0],
      rehash({ offset: 4, total_bytes: 11 }, pythonPages[1]),
      rehash({ offset: 2, total_bytes: 9 }, pythonPages[1]),
      rehash({ binding: { ...binding, section_id: "foreign" } }, pythonPages[1]),
      rehash({ bundle_digest: "b".repeat(64) }, pythonPages[1]),
      rehash({ total_bytes: 11, next_offset: 10 }, pythonPages[1])]) {
      await expect(acc.add(wire)).rejects.toThrow("RESULT_PAGE_INVALID");
      expect(acc.state).toEqual(before);
    }
    await acc.add(pythonPages[1]);
    expect(acc.finish()).toEqual(bytes);
  });

  it("requires whole-bundle hash, not just last-page flag and valid page hashes", async () => {
    const acc = new ResultPageAccumulatorV1(binding, { maxTotalBytes: 10 });
    await acc.add(pythonPages[0]);
    const damaged = rehash({ payload_base64: "p6rDqeWwvw==" }, pythonPages[1]);
    await expect(parseResultPageV1(damaged)).resolves.toBeDefined();
    await expect(acc.add(damaged)).rejects.toThrow("RESULT_PAGE_INVALID");
    expect(acc.state.readCompleteness).toBe("PARTIAL");
    expect(() => acc.finish()).toThrow("RESULT_PAGE_INCOMPLETE");
  });

  it("checks declared receiver limits before hashing/allocating and requires an explicit ceiling", async () => {
    for (const limit of [0, -1, 1.5, NaN, Infinity, MAX_BUNDLE_BYTES + 1]) {
      expect(() => new ResultPageAccumulatorV1(binding, { maxTotalBytes: limit })).toThrow("RESULT_PAGE_INVALID");
    }
    const digest = vi.fn();
    vi.stubGlobal("crypto", { subtle: { digest } });
    const acc = new ResultPageAccumulatorV1(binding, { maxTotalBytes: 9 });
    await expect(acc.add(pythonPages[0])).rejects.toThrow("RESULT_PAGE_INVALID");
    expect(digest).not.toHaveBeenCalled();
    expect(acc.state.receivedBytes).toBe(0);
  });

  it("defensively copies inputs, state, and finished bytes; rejects post-completion add", async () => {
    const bound = clone(binding);
    const acc = new ResultPageAccumulatorV1(bound, { maxTotalBytes: 10 });
    bound.section_id = "changed";
    const wire = clone(pythonPages[0]);
    const pending = acc.add(wire);
    wire.payload_base64 = "AAAA";
    wire.binding.section_id = "changed";
    await pending;
    const state = acc.state;
    expect(Object.isFrozen(state)).toBe(true);
    await acc.add(pythonPages[1]);
    expect(state.readCompleteness).toBe("PARTIAL");
    const output = acc.finish(); output.fill(0);
    expect(acc.finish()).toEqual(bytes);
    await expect(acc.add(pythonPages[1])).rejects.toThrow("RESULT_PAGE_INVALID");
  });

  it("rejects concurrent add explicitly, without racing ordering", async () => {
    const acc = new ResultPageAccumulatorV1(binding, { maxTotalBytes: 10 });
    const first = acc.add(pythonPages[0]);
    await expect(acc.add(pythonPages[1])).rejects.toThrow("RESULT_PAGE_BUSY");
    await first;
    await acc.add(pythonPages[1]);
    expect(acc.finish()).toEqual(bytes);
  });

  it("reset invalidates an in-flight add and starts a distinct bound snapshot", async () => {
    const acc = new ResultPageAccumulatorV1(binding, { maxTotalBytes: 10 });
    const old = acc.add(pythonPages[0]);
    const rejected = expect(old).rejects.toThrow("RESULT_PAGE_CANCELLED");
    const nextBinding = { ...binding, source_digest: "b".repeat(64) };
    acc.reset(nextBinding);
    await acc.add(rehash({ binding: nextBinding }, onePage(new Uint8Array([65]))));
    await rejected;
    expect(acc.finish()).toEqual(new Uint8Array([65]));
  });

  it("cancel clears retained bytes and rejects further use until explicit reset", async () => {
    const acc = new ResultPageAccumulatorV1(binding, { maxTotalBytes: 10 });
    await acc.add(pythonPages[0]);
    acc.cancel();
    expect(acc.state).toEqual({ readCompleteness: "PARTIAL", receivedBytes: 0, totalBytes: null });
    await expect(acc.add(pythonPages[1])).rejects.toThrow("RESULT_PAGE_CANCELLED");
    expect(() => acc.finish()).toThrow("RESULT_PAGE_CANCELLED");
    acc.reset(binding);
    await acc.add(onePage(bytes));
    expect(acc.finish()).toEqual(bytes);
  });

  it("cancels while final bundle hashing is pending without exposing COMPLETE", async () => {
    let entered!: () => void;
    let release!: () => void;
    const hashingBundle = new Promise<void>(resolve => { entered = resolve; });
    const gate = new Promise<void>(resolve => { release = resolve; });
    vi.stubGlobal("crypto", { subtle: { digest: async (algorithm: string, data: Uint8Array<ArrayBuffer>) => {
      const result = await webcrypto.subtle.digest(algorithm, data);
      if (data.byteLength === bytes.length) { entered(); await gate; }
      return result;
    } } });
    const acc = new ResultPageAccumulatorV1(binding, { maxTotalBytes: 10 });
    const pending = acc.add(onePage(bytes));
    const cancelled = expect(pending).rejects.toThrow("RESULT_PAGE_CANCELLED");
    await hashingBundle;
    expect(acc.state.readCompleteness).toBe("PARTIAL");
    expect(() => acc.finish()).toThrow("RESULT_PAGE_INCOMPLETE");
    acc.cancel();
    release();
    await cancelled;
    expect(acc.state).toEqual({ readCompleteness: "PARTIAL", receivedBytes: 0, totalBytes: null });
  });
});
