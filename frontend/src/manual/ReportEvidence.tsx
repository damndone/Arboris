// v1.9.0 — a manual report as it reads. The text is the person's; numbers in
// it are value markers, [[v:<fact id>]], shown as the fact's stored value
// (formatted by the one rule in format/numbers) with its source on hover, so
// editing the prose cannot change a number. Reports saved before v1.9.0 list
// facts as "- label: value [[c:id]]" lines; those still read as facts.

import type { ReactNode } from "react";
import type { Draft } from "./manualApi";
import { formatEstimate, formatPValue } from "../format/numbers";

type Fact = Draft["facts"][number];

const labels: Record<string, string> = {
  p_value: "p-value",
  std_error: "Standard error",
  ci_lower: "Confidence interval lower bound",
  ci_upper: "Confidence interval upper bound",
  nobs: "Observations",
  n_observations: "Observations",
  r_squared: "R²",
  adjusted_r_squared: "Adjusted R²",
  estimate: "Estimate",
};

// Identities and bookkeeping a reader does not need inline; they stay listed
// under "Methods and technical evidence".
const TECHNICAL_FIELD = [
  /^(?:param|decision)\//,
  /\/(?:id|model_id|model_run_id|model_type|artifact_id|result_id|source_id|execution_key|contract|contract_version|reason_code|operation_id)$/,
  /\/retained_positions\//,
];

const VALUE = /\[\[v:([A-Za-z0-9._-]+)\]\]/g;

export function factLabel(fact: Fact): string {
  return fact.label.split(" · ").map((part) => labels[part] ?? part.replace(/_/g, " ")).join(" · ");
}

/** Same words as backend/workbench/services/manual_report_text.py format_fact_value. */
export function factValue(fact: Fact): string {
  if (fact.value === null) return "Not reported";
  if (typeof fact.value === "boolean") return fact.value ? "Yes" : "No";
  if (typeof fact.value !== "number") return fact.value;
  return /(?:^|[/ .])p_value(?:_corrected)?$/.test(fact.field) ? formatPValue(fact.value) : formatEstimate(fact.value);
}

/** The one fact a marker names: its id, or a unique prefix of at least eight
 *  characters (the backend's manual_report_text.resolve). */
export function resolveFact(marker: string, byId: Map<string, Fact>): Fact | undefined {
  const exact = byId.get(marker);
  if (exact || marker.length < 8) return exact;
  let found: Fact | undefined;
  for (const [id, fact] of byId) {
    if (!id.startsWith(marker)) continue;
    if (found) return undefined;
    found = fact;
  }
  return found;
}

/** Each distinct marker in a text, with the fact it names (if any). */
export function markersIn(text: string, facts: Fact[]): Array<{ marker: string; fact: Fact | undefined }> {
  const byId = new Map(facts.map((fact) => [fact.id, fact]));
  return [...new Set([...text.matchAll(VALUE)].map((match) => match[1]))].map((marker) => ({ marker, fact: resolveFact(marker, byId) }));
}

function provenance(fact: Fact): string {
  return `${factLabel(fact)} · exact value ${String(fact.value)} · ${fact.source.result_ref} · run ${fact.source.run_id}`;
}

/** Inline text: **bold**, value markers, and citation markers. */
function inline(text: string, byId: Map<string, Fact>, key: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const pattern = /\*\*([^*]+)\*\*|\[\[v:([A-Za-z0-9._-]+)\]\]|\[\[c:([^\]]+)\]\]/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let n = 0;
  while ((match = pattern.exec(text))) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    const id = `${key}:${n++}`;
    if (match[1] !== undefined) {
      parts.push(<strong key={id}>{inline(match[1], byId, id)}</strong>);
    } else if (match[2] !== undefined) {
      const fact = resolveFact(match[2], byId);
      parts.push(
        fact ? (
          <span key={id} className="manual-value" title={provenance(fact)}>{factValue(fact)}</span>
        ) : (
          <span key={id} className="manual-value manual-value--missing" title="This value is not in the selected evidence">value unavailable</span>
        ),
      );
    } else {
      const fact = byId.get(match[3]);
      parts.push(<sup key={id} className="manual-cite" title={fact ? provenance(fact) : match[3]}>source</sup>);
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/** A fact line from a report saved before value markers existed. */
function legacyFact(line: string, byId: Map<string, Fact>): Fact | null {
  const match = line.match(/^- .* \[\[c:([^\]]+)\]\]$/);
  const fact = match ? byId.get(match[1]) : undefined;
  if (!fact) return null;
  // Python and JavaScript spell floats differently (0.0/0, 1e-08/1e-8).
  // Require the exact registered label and citation, and an equal scalar.
  const prefix = `- ${fact.label}: `;
  const suffix = ` [[c:${fact.id}]]`;
  if (!line.startsWith(prefix) || !line.endsWith(suffix)) return null;
  const scalar = line.slice(prefix.length, -suffix.length);
  const pythonScalar = (value: Fact["value"]) => (value === null ? "None" : typeof value === "boolean" ? (value ? "True" : "False") : value);
  const equal =
    typeof fact.value === "number"
      ? /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(scalar) && Number(scalar) === fact.value
      : scalar === pythonScalar(fact.value);
  return equal ? fact : null;
}

/** Display only: source values, identities and saved prose remain untouched. */
export function ReportReadingView({ text, facts }: { text: string; facts: Fact[] }) {
  const byId = new Map(facts.map((fact) => [fact.id, fact]));
  const blocks: ReactNode[] = [];
  const technical: ReactNode[] = [];
  let list: ReactNode[] = [];
  let paragraph: string[] = [];
  const flushList = () => {
    if (list.length) blocks.push(<ul key={`ul${blocks.length}`}>{list}</ul>);
    list = [];
  };
  const flushParagraph = () => {
    if (paragraph.length) blocks.push(<p key={`p${blocks.length}`}>{inline(paragraph.join(" "), byId, `p${blocks.length}`)}</p>);
    paragraph = [];
  };

  text.split("\n").forEach((raw, index) => {
    const line = raw.trimEnd();
    const fact = legacyFact(line, byId);
    if (fact) {
      flushParagraph();
      const item = (
        <details key={index} className="manual-reading__fact">
          <summary>
            {factLabel(fact)}: <strong>{factValue(fact)}</strong>
          </summary>
          <small>
            Original line: {line}
            <br />
            Exact value: {String(fact.value)} · Field: {fact.field} · Evidence: {fact.id} · Run: {fact.source.run_id}
          </small>
        </details>
      );
      if (TECHNICAL_FIELD.some((pattern) => pattern.test(fact.field))) technical.push(item);
      else {
        flushList();
        blocks.push(item);
      }
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const Tag = (`h${Math.min(heading[1].length + 2, 6)}`) as "h3";
      blocks.push(<Tag key={index} data-level={heading[1].length}>{inline(heading[2], byId, `h${index}`)}</Tag>);
      return;
    }
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      flushParagraph();
      list.push(<li key={index}>{inline(bullet[1], byId, `li${index}`)}</li>);
      return;
    }
    if (!line.trim()) {
      flushParagraph();
      flushList();
      return;
    }
    flushList();
    paragraph.push(line.trim());
  });
  flushParagraph();
  flushList();

  return (
    <section aria-label="Report reading view" className="manual-reading">
      {blocks}
      {technical.length > 0 && (
        <details>
          <summary>Methods and technical evidence ({technical.length})</summary>
          {technical}
        </details>
      )}
    </section>
  );
}
