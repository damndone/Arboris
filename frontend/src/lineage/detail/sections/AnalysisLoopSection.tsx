import { useEffect, useState } from "react";
import type { GraphViewNode } from "../../api/graphViewTypes";
import {
  fetchAnalysisLoopPackets,
  type AnalysisLoopPacketBundle,
  type AnalysisLoopPacketsResponse,
} from "../../api/analysisLoop";
import { useProjectRootOptional } from "../../../workbench/ProjectRootContext";

type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function textValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return "[unavailable]";
  }
}

function runIdForNode(node: GraphViewNode): string | null {
  const runs = (node as GraphViewNode & { runs?: unknown }).runs;
  if (Array.isArray(runs) && typeof runs[0] === "string" && runs[0]) return runs[0];
  const raw = record(node.raw);
  return raw && typeof raw.run_id === "string" && raw.run_id ? raw.run_id : null;
}

function packetTarget(packet: AnalysisLoopPacketBundle | null): string | null {
  const compare = record(packet?.compare_packet);
  const target = record(compare?.target);
  return target && typeof target.result_id === "string" ? target.result_id : null;
}

function PacketStatus({ packet }: { packet: AnalysisLoopPacketBundle }) {
  const validation = record(packet.validation_packet);
  const compare = record(packet.compare_packet);
  const conclusion = record(compare?.conclusion_diff);
  return (
    <div
      data-testid="analysis-loop-child-packet"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 3,
        padding: 8,
        borderRadius: 6,
        background: "var(--bg-card-2, rgba(255,255,255,0.04))",
      }}
    >
      <strong>{packet.child_run_id}</strong>
      <span>Validation: {textValue(validation?.status)}</span>
      <span>Compare: {textValue(compare?.compare_status)}</span>
      <span>Conclusion: {textValue(conclusion?.classification ?? conclusion?.reason_code)}</span>
    </div>
  );
}

export function AnalysisLoopSection({ node }: { node: GraphViewNode }) {
  const projectRoot = useProjectRootOptional();
  const runId = runIdForNode(node);
  const [data, setData] = useState<AnalysisLoopPacketsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!projectRoot || !runId) {
      setData(null);
      setError("ANALYSIS_LOOP_CONTEXT_UNAVAILABLE");
      setLoading(false);
      return () => { cancelled = true; };
    }
    setLoading(true);
    setError(null);
    fetchAnalysisLoopPackets(projectRoot, runId)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        setLoading(false);
      })
      .catch((requestError: unknown) => {
        if (cancelled) return;
        setData(null);
        setError(requestError instanceof Error ? requestError.message : String(requestError));
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectRoot, runId]);

  if (loading) {
    return (
      <section aria-label="Agent analysis loop" data-testid="analysis-loop-loading" style={{ marginTop: 18 }}>
        <div className="ln-section-label">Agent analysis loop</div>
        <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>Loading backend evidence…</div>
      </section>
    );
  }

  if (error) {
    return (
      <section aria-label="Agent analysis loop" data-testid="analysis-loop-error" style={{ marginTop: 18 }}>
        <div className="ln-section-label">Agent analysis loop</div>
        <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>
          Analysis Loop unavailable: {error}
        </div>
      </section>
    );
  }

  if (!data) return null;
  const run = data.run;
  const source = record(data.source_run) ?? {};
  const packet = data.packet;
  const target = packetTarget(packet);
  const plan = record(packet?.plan_diff);
  const productPatch = record(plan?.product_patch);
  const validation = record(packet?.validation_packet);
  const checks = Array.isArray(validation?.checks) ? validation.checks : [];
  const compare = record(packet?.compare_packet);
  const conclusion = record(compare?.conclusion_diff);
  const invariants = record(plan?.invariants);

  return (
    <section aria-label="Agent analysis loop" data-testid="analysis-loop-section" style={{ marginTop: 18 }}>
      <div className="ln-section-label" style={{ marginBottom: 6 }}>
        Agent analysis loop
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 8,
          padding: 10,
          background: "var(--bg-card-2, rgba(255,255,255,0.04))",
          borderRadius: 8,
          fontSize: 12,
        }}
      >
        <div data-testid="analysis-loop-status">
          Status: <strong>{data.status}</strong>
        </div>
        <div data-testid="analysis-loop-run-facts">
          OLS contract {textValue(run.contract_version)} · run {textValue(run.status)} · covariance {textValue(run.covariance)}
        </div>
        <div data-testid="analysis-loop-source-facts">
          Source {textValue(source.run_id)} · {textValue(source.status)} · covariance {textValue(source.covariance_product ?? source.covariance)}
        </div>
        <div data-testid="analysis-loop-cluster-validation">
          Cluster variable: {textValue(productPatch?.cluster_variable ?? run.entity_col ?? "Not selected")}
        </div>
        <div data-testid="analysis-loop-primary-target">
          Primary target: {target ?? "Not selected"}
        </div>

        {plan && (
          <section data-testid="analysis-loop-plan-diff" aria-label="PlanDiff">
            <strong>PlanDiff</strong>
            <div>Product patch: {textValue(plan.product_patch)}</div>
            <div>Wire patch: {textValue(plan.wire_patch)}</div>
            <div>Plan hash: {textValue(plan.plan_hash)}</div>
            <div>Canonical patch hash: {textValue(plan.canonical_patch_hash)}</div>
            <div>Expected unchanged: {textValue(invariants)}</div>
          </section>
        )}

        {validation && (
          <section data-testid="analysis-loop-validation" aria-label="ValidationPacket">
            <strong>ValidationPacket</strong>
            <div>Status: {textValue(validation.status)} · overall: {textValue(validation.overall_status)}</div>
            {checks.length === 0 ? (
              <div>No validation checks recorded.</div>
            ) : (
              <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                {checks.map((item, index) => {
                  const check = record(item);
                  return (
                    <li key={`${textValue(check?.check_id)}-${index}`}>
                      {textValue(check?.check_id)} · {textValue(check?.status)} · {textValue(check?.severity)}
                      {check?.reason_code ? ` · ${textValue(check.reason_code)}` : ""}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        )}

        {compare && (
          <section data-testid="analysis-loop-compare" aria-label="ComparePacket">
            <strong>ComparePacket</strong>
            <div>Status: {textValue(compare.compare_status)} · source {textValue(compare.source_run_id)} · child {textValue(compare.child_run_id)}</div>
            <div>Data diff: {textValue(compare.data_diff)}</div>
            <div>Parameter diff: {textValue(compare.parameter_diff)}</div>
            <div>Result diff: {textValue(compare.result_diff)}</div>
            <div>Conclusion: {textValue(conclusion?.classification ?? conclusion?.reason_code)}</div>
            {Array.isArray(compare.integrity_findings) && compare.integrity_findings.length > 0 && (
              <div>Integrity findings: {compare.integrity_findings.map(textValue).join(", ")}</div>
            )}
          </section>
        )}

        {data.children.length > 0 && (
          <section data-testid="analysis-loop-child-packets" aria-label="Analysis Loop child packets">
            <strong>Child runs</strong>
            {data.children.map((child) => <PacketStatus key={child.child_run_id} packet={child} />)}
          </section>
        )}
      </div>
    </section>
  );
}
