import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { ReportViewContent } from "./ReportView";
import { ResultEvidenceReader } from "./ResultEvidenceReader";
import * as evidence from "./reportEvidence";

vi.mock("../workbench/ForestContext", () => ({ useForest: () => ({ activeRunId: "r1" }) }));
vi.mock("../workbench/WorkbenchStateProvider", () => ({ useWorkbenchOptional: () => null }));
vi.mock("./ReportWorkspaceContext", async (original) => ({
  ...await original<typeof import("./ReportWorkspaceContext")>(),
  useReportWorkspace: () => ({ projectRoot: "/project", activeRunId: "r1", table: null,
    excludedFactIds: [], excludedFigureIds: [], reportEvidenceProjection: null }),
}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
beforeEach(() => vi.stubGlobal("crypto", webcrypto));

it("mounts the manual formal reader even when the whole Report projection/table is unavailable", () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  render(<ReportViewContent />);
  expect(screen.getByRole("region", { name: "Formal result reader" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Read directory" })).toBeEnabled();
  expect(fetch).not.toHaveBeenCalled();
});

// Deterministic wire built from the ordinary NumericFact fixture and verified
// below by Python's actual bundle parser and pager (not by the JS receiver).
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
function canonical(v: any): string {
  if (typeof v === "string") return JSON.stringify(v.normalize("NFC"));
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (v && typeof v === "object") return `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canonical(v[k])}`).join(",")}}`;
  return JSON.stringify(v);
}
const hash = (v: any) => createHash("sha256").update(canonical(v)).digest("hex");
const identity = { actor_ref: "actor:structured", project_ref: "project:structured", session_ref: "session:structured",
  scope_ref: "scope:structured", run_id: "r1", model_run_id: "r1", confirmation_ref: "confirmation:r1" };
const source = { artifact_ref: "artifact-1", commit_id: "commit:fixture", envelope_digest: "a".repeat(64) };
const contract = "9ac17e068d3d718e6cb09a938e2d373db3c43d49b11ca6b7ac6df76897732ab6";
const policy = { kind: "policy", logical_id: "workbench.consumer_projection.local_structured_v1.report", semantic_version: "1.0",
  contract_digest: "0bd2f4b04a959c37aa3deab0580adadb90f8fd1808c0d62674e1a7d38b7d2344" };
function bundle(id = "a"): any {
  const original = JSON.parse(readFileSync("../tests/fixtures/contracts/v189/evidence_envelope.json", "utf8"));
  const fact = clone(original.numeric_facts[0]);
  fact.source_selector.artifact_ref = id;
  fact.source_selector.artifact_digest = "b".repeat(64);
  return { schema_version: 1, source_ref: source.artifact_ref, source_digest: source.envelope_digest, commit_id: source.commit_id,
    result_identity: { contract: "evidence-envelope", schema_version: "1.0", result_id: "result-1", project_ref: identity.project_ref, run_id: "r1" },
    section_contract_digest: contract,
    section: { schema_version: 1, section_id: id, section_type: "statistical_tests", status: "available", reason_codes: [],
      fact_refs: [fact.fact_id], dependency_refs: [id], content: { kind: "object", fields: { results: { kind: "list", items: [
        { kind: "object", fields: { label: { kind: "text", value: "统计🧪" }, statistic: { kind: "fact", fact_id: fact.fact_id, representation: "number" } } },
      ] } } } }, facts: [fact],
    result_dependencies: { schema_version: 1, project_ref: identity.project_ref, run_id: "r1", records: [
      { artifact_id: id, path: ["runs", "r1", `${id}.json`], sha256: "b".repeat(64), index_record: {
        artifact_id: id, path: `${id}.json`, sha256: "b".repeat(64), artifact_type: "model_results", step: "estimation", inputs: [],
      } },
    ] },
    projection_metadata: { consumer_id: "report", consumer_version: "1.0", renderer_key: "workbench.consumer_projection.report",
      projection_ref: { kind: "projection", logical_id: "workbench.consumer_projection.report", semantic_version: "1.0",
        contract_digest: "a8ef0d53d792009995caa12044aebab7cb94c6aaf8644fa4d358d413956331f8" },
      envelope_ref: `evidence-envelope:${source.envelope_digest}`, execution_status: "completed", availability: "available",
      completeness_status: "complete", numerical_method: "deterministic_numeric", inference_basis: "asymptotic", evaluation_design: "in_sample",
      status: "available", validation_summary: original.validation_summary, lineage_refs: ["operation-1", "artifact-1"],
      data_snapshot_ref: "dataset-1", data_snapshot_digest: "c".repeat(64),
      audit: { policy_ref: policy, destination: "local", requested_fact_ids: [fact.fact_id], selected_fact_ids: [fact.fact_id],
        omitted_fact_ids: [], redacted_fact_ids: [], requested_section_ids: [id], selected_section_ids: [id],
        omitted_section_ids: [id === "a" ? "b" : "a"], redacted_section_ids: [], raw_rows_rejected: false,
        restriction_reason: null, row_budget: 1, token_budget: 274 },
    },
  };
}
function directory(): any {
  const wire = { schema_version: 1, authority: "server-owned", consumer_id: "report", destination: "local", identity: clone(identity), ...source,
    section_contract_digest: contract, read_completeness: "PARTIAL", completion_scope: "run",
    sections: ["a", "b"].map(section_id => ({ section_id, section_type: "statistical_tests", status: "available", reason_codes: [] })), directory_digest: "" };
  wire.directory_digest = hash(wire.sections);
  return { ...wire, receipt: { schema_version: 1, kind: "evidence.report.directory-receipt.v1", wire_digest: hash(wire) } };
}
function signOwner(wire: any, canonicalCharge = false): any {
  const body = clone(wire); delete body.receipt;
  if (body.delivery) {
    const d = body.delivery; delete d.wire_digest; d.wire_digest = hash(d);
    const receipt = { schema_version: 1, kind: "evidence.report.page-receipt.v1", identity: clone(body.identity),
      provenance: { artifact_ref: body.artifact_ref, commit_id: body.commit_id, envelope_digest: body.envelope_digest }, payload_digest: d.wire_digest, wire_digest: "" };
    for (let i = 0; i < 4; i++) {
      receipt.wire_digest = hash(body);
      body.audit.token_budget = Math.ceil(Buffer.byteLength(canonicalCharge ? canonical({ ...body, receipt }) : JSON.stringify({ ...body, receipt })) / 4);
    }
    receipt.wire_digest = hash(body);
    return { ...body, receipt };
  }
  return { ...body, receipt: { schema_version: 1, kind: "evidence.report.directory-receipt.v1", wire_digest: hash(body) } };
}
function page(b = bundle(), offset = 0, size = 2000): any {
  const bytes = Buffer.from(canonical(b));
  const end = Math.min(bytes.length, offset + size);
  const p: any = { schema_version: 1, binding: { source_ref: source.artifact_ref, source_digest: source.envelope_digest,
    section_id: b.section.section_id, consumer_id: "report", destination: "local" }, bundle_digest: hash(b), offset, total_bytes: bytes.length,
    next_offset: end === bytes.length ? null : end, payload_base64: bytes.subarray(offset, end).toString("base64") };
  p.page_digest = hash(p);
  return signOwner({ schema_version: 1, authority: "server-owned", consumer_id: "report", destination: "local", identity: clone(identity), ...source,
    read_completeness: "PARTIAL", completion_scope: "section", audit: { token_budget: 0, row_budget: 5 },
    delivery: { schema_version: 1, authority: "server-owned", source: "persisted-typed-evidence-page", consumer_id: "report", destination: "local", ...source,
      identity: { project_ref: identity.project_ref, run_id: "r1", scope_ref: identity.scope_ref }, observed_sensitivity: "public", policy_ref: policy,
      audit: { row_budget: 5, token_budget: 1957, envelope_reserve_bytes: 1314 }, page: p },
  });
}
function serve(transform?: (wire: any, url: URL) => any) {
  const fetch = vi.fn(async (input: string) => {
    const url = new URL(input, "http://localhost");
    let wire = url.pathname.endsWith("directory") ? directory() : page(bundle(url.searchParams.get("section_id")!), Number(url.searchParams.get("offset")));
    if (transform) wire = transform(wire, url);
    return new Response(JSON.stringify(wire), { headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetch); return fetch;
}
async function openReader() {
  render(<ResultEvidenceReader projectRoot="/project" runId="r1" />);
  fireEvent.click(screen.getByRole("button", { name: "Read directory" }));
  await screen.findByRole("button", { name: "Read a" });
}

it("fixture is accepted by Python's ordinary bundle validator and byte pager", () => {
  const out = execFileSync("../.venv/bin/python", ["-c", `
import workbench.orchestrator
import sys,json
from workbench.canonical import canonical_json_v1
from workbench.evidence.consumer_adapters import parse_result_section_bundle
from workbench.contracts.evidence.result_pages import ResultBundlePagerV1
v=json.load(sys.stdin)
raw=canonical_json_v1(v['bundle']).encode()
parse_result_section_bundle(raw)
p=ResultBundlePagerV1(raw,binding=v['binding'])
print(canonical_json_v1(p.page(offset=0,max_wire_bytes=262144).to_dict()))
`], { input: JSON.stringify({ bundle: bundle(), binding: page().delivery.page.binding }), env: { ...process.env, PYTHONPATH: "../backend" }, encoding: "utf8" });
  expect(JSON.parse(out)).toEqual(page(bundle(), 0, 10000).delivery.page);
});

it.each(["fact.mean", "path", "artifact_type", "step"])("matches Python ordinary bundle contract for %s", variant => {
  const b = bundle();
  if (variant === "fact.mean") {
    b.facts[0].fact_id = "fact.mean";
    b.section.fact_refs = ["fact.mean"];
    b.section.content.fields.results.items[0].fields.statistic.fact_id = "fact.mean";
    b.projection_metadata.audit.requested_fact_ids = ["fact.mean"];
    b.projection_metadata.audit.selected_fact_ids = ["fact.mean"];
  } else {
    const dep = b.result_dependencies.records[0];
    if (variant === "path") { dep.path[2] = " a.json"; dep.index_record.path = " a.json"; }
    else dep.index_record[variant] = ` ${dep.index_record[variant]}`;
  }
  const accepted = execFileSync("../.venv/bin/python", ["-c", `
import workbench.orchestrator
import sys,json
from workbench.canonical import canonical_json_v1
from workbench.evidence.consumer_adapters import parse_result_section_bundle
try:
    parse_result_section_bundle(canonical_json_v1(json.load(sys.stdin)).encode())
except ValueError:
    print("rejected")
else:
    print("accepted")
`], { input: JSON.stringify(b), env: { ...process.env, PYTHONPATH: "../backend" }, encoding: "utf8" }).trim();
  expect(accepted).toBe(variant === "fact.mean" ? "accepted" : "rejected");
  const read = () => evidence.readResultSectionBundle(new TextEncoder().encode(canonical(b)), directory(), "a");
  if (variant === "fact.mean") expect(read().facts).toEqual(b.facts);
  else expect(read).toThrow();
});

it("reads only on explicit clicks, separates section/run completeness, and resets", async () => {
  const fetch = serve(); await openReader();
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Read a" }));
  await screen.findByRole("button", { name: "Load next a" });
  expect(screen.getByTestId("section-read-a")).toHaveTextContent("PARTIAL");
  expect(screen.queryByText("统计🧪")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Load next a" }));
  await waitFor(() => expect(screen.getByTestId("section-read-a")).toHaveTextContent("COMPLETE"));
  expect(screen.getByTestId("run-read-completeness")).toHaveTextContent("PARTIAL");
  expect(screen.getByText("统计🧪")).toBeInTheDocument();
  expect(screen.getByText(/not statistical validation/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Read b" }));
  fireEvent.click(await screen.findByRole("button", { name: "Load next b" }));
  await waitFor(() => expect(screen.getByTestId("run-read-completeness")).toHaveTextContent("COMPLETE"));
  expect(fetch).toHaveBeenCalledTimes(5);
  for (const [url] of fetch.mock.calls) expect(url).not.toMatch(/actor_ref|session_ref|llm|confirmation_ref/);
  fireEvent.click(screen.getByRole("button", { name: "Reset reading" }));
  expect(screen.queryByText("统计🧪")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Read directory" })).toBeEnabled();
});

it.each(["run", "version", "consumer", "destination", "hash", "receipt", "duplicate", "unknown field"])("rejects directory %s before paging", async attack => {
  const fetch = serve(w => {
    if (attack === "run") w.identity.run_id = "foreign";
    if (attack === "version") w.schema_version = 2;
    if (attack === "consumer") w.consumer_id = "agent";
    if (attack === "destination") w.destination = "remote";
    if (attack === "hash") w.directory_digest = "0".repeat(64);
    if (attack === "duplicate") w.sections.push(w.sections[0]);
    if (attack === "unknown field") w.raw_payload = {};
    return attack === "receipt" ? { ...w, receipt: { ...w.receipt, wire_digest: "0".repeat(64) } } : signOwner(w);
  });
  render(<ResultEvidenceReader projectRoot="/project" runId="r1" />);
  fireEvent.click(screen.getByRole("button", { name: "Read directory" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("RESULT_");
  expect(screen.queryByRole("button", { name: "Read a" })).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(["tamper", "gap", "source", "owner identity", "delivery identity", "receipt identity", "delivery hash", "consumer", "schema"])("fails closed on page %s without displaying bytes", async attack => {
  serve((w, url) => {
    if (url.pathname.endsWith("directory")) return w;
    if (attack === "tamper") { w.delivery.page.payload_base64 = "AAAA"; return w; }
    if (attack === "gap") w.delivery.page.offset = 1;
    if (attack === "source") w.envelope_digest = "d".repeat(64);
    if (attack === "owner identity") w.identity.confirmation_ref = "other";
    if (attack === "delivery identity") w.delivery.identity.project_ref = "other";
    if (attack === "consumer") w.delivery.consumer_id = "agent";
    if (attack === "schema") { const b = bundle(); b.section.section_type = "arbitrary_json"; return page(b, 0, 10000); }
    const signed = signOwner(w);
    if (attack === "receipt identity") signed.receipt.identity.session_ref = "other";
    if (attack === "delivery hash") signed.delivery.wire_digest = "0".repeat(64);
    return signed;
  });
  await openReader(); fireEvent.click(screen.getByRole("button", { name: "Read a" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("RESULT_");
  expect(screen.getByTestId("run-read-completeness")).toHaveTextContent("PARTIAL");
  expect(screen.queryByText("统计🧪")).not.toBeInTheDocument();
});

it("resumes at retained offset after a network failure without an automatic retry", async () => {
  const fetch = serve(); await openReader();
  fireEvent.click(screen.getByRole("button", { name: "Read a" }));
  await screen.findByRole("button", { name: "Load next a" });
  fetch.mockRejectedValueOnce(new TypeError("offline"));
  fireEvent.click(screen.getByRole("button", { name: "Load next a" }));
  fireEvent.click(await screen.findByRole("button", { name: "Resume a" }));
  await waitFor(() => expect(screen.getByTestId("section-read-a")).toHaveTextContent("COMPLETE"));
  expect(fetch.mock.calls[2][0]).toBe(fetch.mock.calls[3][0]);
});

it.each(["project", "run", "reset"])("cancels pending old state on %s change", async kind => {
  let resolve!: (response: Response) => void;
  const fetch = vi.fn().mockImplementation((_url, init) => {
    expect(init.signal).toBeDefined(); return new Promise<Response>(r => { resolve = r; });
  }); vi.stubGlobal("fetch", fetch);
  const view = render(<ResultEvidenceReader projectRoot="/project" runId="r1" />);
  fireEvent.click(screen.getByRole("button", { name: "Read directory" }));
  if (kind === "reset") fireEvent.click(screen.getByRole("button", { name: "Reset reading" }));
  else view.rerender(<ResultEvidenceReader projectRoot={kind === "project" ? "/other" : "/project"} runId={kind === "run" ? "r2" : "r1"} />);
  expect(fetch.mock.calls[0][1].signal.aborted).toBe(true);
  await act(async () => resolve(new Response(JSON.stringify(directory()))));
  expect(screen.queryByRole("button", { name: "Read a" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Read directory" })).toBeEnabled();
});

it("rejects response bytes before JSON parsing, including missing Content-Length", async () => {
  const cancel = vi.fn(); let count = 0;
  vi.stubGlobal("fetch", vi.fn(async () => new Response(new ReadableStream({
    pull(c) { count++; c.enqueue(new Uint8Array(150000)); }, cancel,
  }))));
  render(<ResultEvidenceReader projectRoot="/project" runId="r1" />);
  fireEvent.click(screen.getByRole("button", { name: "Read directory" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("RESULT_READ_LIMIT");
  expect(cancel).toHaveBeenCalled(); expect(count).toBeLessThan(5);
});

it.each(["fact reference", "dependency", "provenance", "schema", "raw numeric", "depth", "validation"])("rejects reconstructed bundle %s using the ordinary contract", attack => {
  const b = bundle();
  if (attack === "fact reference") b.section.fact_refs = [];
  if (attack === "dependency") b.result_dependencies.records = [];
  if (attack === "provenance") b.facts[0].source_selector.artifact_digest = "d".repeat(64);
  if (attack === "schema") b.section.content.fields.unrecognized = { kind: "text", value: "x" };
  if (attack === "raw numeric") b.section.content.fields.results.items[0].fields.statistic = { kind: "text", value: "2" };
  if (attack === "depth") b.section.content.fields.results.items = Array(17000).fill({ kind: "null" });
  if (attack === "validation") b.facts[0].validation_level = "reference_software";
  expect(() => evidence.readResultSectionBundle(b, directory(), "a")).toThrow("RESULT_SECTION_BUNDLE_INVALID");
});

it.each(["verbatim", "normalized page identity", "normalized receipt identity", "undercharged"])("NFD owner: %s", async mode => {
  const nfd = `actor:${"e\u0301".repeat(50)}`;
  serve((w, url) => {
    w.identity.actor_ref = nfd;
    if (mode === "normalized page identity" && url.pathname.endsWith("page")) w.identity.actor_ref = nfd.normalize("NFC");
    const signed = signOwner(w, mode === "undercharged");
    if (mode === "normalized receipt identity" && url.pathname.endsWith("page")) signed.receipt.identity.actor_ref = nfd.normalize("NFC");
    return signed;
  });
  await openReader(); fireEvent.click(screen.getByRole("button", { name: "Read a" }));
  if (mode !== "verbatim") {
    expect(await screen.findByRole("alert")).toHaveTextContent(mode === "undercharged" ? "RESULT_READ_LIMIT" : "RESULT_READ_IDENTITY_MISMATCH");
  } else {
    fireEvent.click(await screen.findByRole("button", { name: "Load next a" }));
    await waitFor(() => expect(screen.getByTestId("section-read-a")).toHaveTextContent("COMPLETE"));
  }
});

it("retains all ordinary facts, references, dependencies, and provenance without aliasing", () => {
  const b = bundle(); const result = evidence.readResultSectionBundle(b, directory(), "a");
  expect(result.facts).toEqual(b.facts);
  expect(result.dependencies).toEqual(b.result_dependencies);
  expect(result.metadata).toEqual(b.projection_metadata);
  expect(result.structuredSection).toEqual(b.section);
  b.facts[0].oracle_checks = []; b.section.content.fields.results.items = [];
  expect(result.facts).not.toEqual(b.facts);
  expect(result.section.content).toEqual({ results: [{ label: "统计🧪", statistic: 2 }] });
});

it("the section bridge accepts canonical complete bytes, not just a parsed JSON object", () => {
  const b = bundle();
  expect(evidence.readResultSectionBundle(new TextEncoder().encode(canonical(b)), directory(), "a").facts).toEqual(b.facts);
});

it("binds canonical bundle project identity to the verbatim NFD owner anchor without changing it", () => {
  const b = bundle(), d = directory(); d.identity.project_ref = "project:e\u0301";
  b.result_identity.project_ref = d.identity.project_ref; b.result_dependencies.project_ref = d.identity.project_ref;
  expect(evidence.readResultSectionBundle(new TextEncoder().encode(canonical(b)), d, "a").facts).toEqual(b.facts);
  expect(d.identity.project_ref).toBe("project:e\u0301");
});

it.each(["duplicate", "noncanonical", "unsafe integer", "over byte cap"])("rejects reconstructed bytes: %s", attack => {
  const b = bundle();
  if (attack === "unsafe integer") b.facts[0].value = Number.MAX_SAFE_INTEGER + 1;
  let raw = canonical(b);
  if (attack === "duplicate") raw = raw.replace('"schema_version":1,', '"schema_version":1,"schema_version":1,');
  if (attack === "noncanonical") raw = ` ${raw}`;
  if (attack === "over byte cap") raw += " ".repeat(1048576);
  expect(() => evidence.readResultSectionBundle(new TextEncoder().encode(raw), directory(), "a")).toThrow("RESULT_SECTION_BUNDLE_INVALID");
});

it("rejects NumericFact text padded with whitespace instead of trimming evidence", () => {
  const b = bundle(); b.facts[0].statistic_id = " padded ";
  expect(() => evidence.readResultSectionBundle(b, directory(), "a")).toThrow("RESULT_SECTION_BUNDLE_INVALID");
});

it.each(["sensitivity", "declared bytes", "bundle identity", "metadata consumer", "metadata policy", "unsafe dependency", "unknown fact field", "bad interval", "negative standard error"])("rejects additional boundary: %s", async attack => {
  serve((w, url) => {
    if (url.pathname.endsWith("directory")) return w;
    if (attack === "sensitivity") { w.delivery.observed_sensitivity = "sensitive"; return signOwner(w); }
    if (attack === "declared bytes") { w.delivery.page.total_bytes = 1048577; return signOwner(w); }
    const b = bundle();
    if (attack === "bundle identity") b.result_identity.project_ref = "other";
    if (attack === "metadata consumer") b.projection_metadata.consumer_id = "agent";
    if (attack === "metadata policy") b.projection_metadata.audit.policy_ref = { ...policy, contract_digest: "0".repeat(64) };
    if (attack === "unsafe dependency") b.result_dependencies.records[0].path = ["runs", "r1", "..", "a.json"];
    if (attack === "unknown fact field") b.facts[0].invented = true;
    if (attack === "bad interval") b.facts[0].confidence_interval.lower = 10;
    if (attack === "negative standard error") b.facts[0].standard_error = -1;
    return page(b, 0, 10000);
  });
  await openReader(); fireEvent.click(screen.getByRole("button", { name: "Read a" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("RESULT_");
  expect(screen.queryByText("统计🧪")).not.toBeInTheDocument();
});

it("a changed source invalidates earlier COMPLETE sections, not only the current page", async () => {
  serve((w, url) => {
    if (url.searchParams.get("section_id") === "b") { w.commit_id = "changed"; return signOwner(w); }
    return w;
  });
  await openReader(); fireEvent.click(screen.getByRole("button", { name: "Read a" }));
  fireEvent.click(await screen.findByRole("button", { name: "Load next a" }));
  await waitFor(() => expect(screen.getByTestId("section-read-a")).toHaveTextContent("COMPLETE"));
  fireEvent.click(screen.getByRole("button", { name: "Read b" }));
  await screen.findByRole("alert");
  expect(screen.getByTestId("section-read-a")).toHaveTextContent("PARTIAL");
  expect(screen.queryByText("统计🧪")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Read a" })).toBeDisabled();
});

it("run switch invalidates a pending page digest as well as its network request", async () => {
  serve(); const view = render(<ResultEvidenceReader projectRoot="/project" runId="r1" />);
  fireEvent.click(screen.getByRole("button", { name: "Read directory" }));
  await screen.findByRole("button", { name: "Read a" });
  const pending: Array<() => void> = [];
  vi.stubGlobal("crypto", { subtle: { digest: (...args: Parameters<typeof webcrypto.subtle.digest>) => new Promise(resolve => {
    pending.push(async () => resolve(await webcrypto.subtle.digest(...args)));
  }) } });
  fireEvent.click(screen.getByRole("button", { name: "Read a" }));
  await waitFor(() => expect(pending.length).toBe(1));
  view.rerender(<ResultEvidenceReader projectRoot="/project" runId="r2" />);
  vi.stubGlobal("crypto", webcrypto);
  await act(async () => { pending[0](); });
  expect(screen.queryByTestId("section-read-a")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Read directory" })).toBeEnabled();
});
