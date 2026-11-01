import type { AgentEvent } from "./agentTypes";

// Provider usage is an external boundary. A missing or inconsistent field
// remains unknown, including when a request failed after consuming tokens.
function count(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
function seconds(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? `${value.toFixed(2)}s` : "Unknown";
}
function reported(event: AgentEvent) {
  const payload = event.payload;
  const raw = payload.usage_state === "reported" && payload.usage && typeof payload.usage === "object"
    ? payload.usage as Record<string, unknown> : {};
  const input = count(raw.prompt_tokens), output = count(raw.completion_tokens);
  const details = raw.prompt_tokens_details as Record<string,unknown> | undefined;
  const hitValue = count(raw.prompt_cache_hit_tokens ?? details?.cached_tokens);
  const missValue = count(raw.prompt_cache_miss_tokens);
  const consistentCache = input !== null && hitValue !== null && hitValue <= input
    && (missValue === null || hitValue + missValue === input)
    && (raw.prompt_cache_hit_tokens === undefined || details?.cached_tokens === undefined
        || raw.prompt_cache_hit_tokens === details.cached_tokens);
  const totalValue = count(raw.total_tokens);
  const reasoningValue = count((raw.completion_tokens_details as Record<string,unknown> | undefined)?.reasoning_tokens);
  return {event, raw, input, output, hit: consistentCache ? hitValue : null,
    miss: consistentCache ? missValue : null,
    total: input !== null && output !== null && totalValue === input + output ? totalValue : null,
    reasoning: output !== null && reasoningValue !== null && reasoningValue <= output ? reasoningValue : null};
}
function subtotal(values: (number | null)[], name: string): string {
  const known = values.filter((value): value is number => value !== null);
  if (!known.length) return `${name[0].toUpperCase()+name.slice(1)} unavailable`;
  return `${known.reduce((sum,value)=>sum+value,0)} ${name}${known.length < values.length ? " (reported subtotal)" : ""}`;
}

/** 1760242 → "1.76M", 15104 → "15.1K": a glance, not the record. */
function compactCount(values: (number | null)[]): string | null {
  const known = values.filter((value): value is number => value !== null);
  if (!known.length) return null;
  const total = known.reduce((sum, value) => sum + value, 0);
  if (total >= 1_000_000) return `${(total / 1_000_000).toFixed(2)}M`;
  if (total >= 1_000) return `${(total / 1_000).toFixed(1)}K`;
  return String(total);
}

export function AgentUsagePanel({events, compact = false}: {events: AgentEvent[]; compact?: boolean}) {
  if (!events.length) return null;
  const rows = events.map(reported);
  const cacheRows = rows.filter(row=>row.input !== null && row.hit !== null);
  const cachedInput = cacheRows.reduce((sum,row)=>sum+row.input!,0);
  const cachedHit = cacheRows.reduce((sum,row)=>sum+row.hit!,0);
  const cache = cachedInput ? `${(100*cachedHit/cachedInput).toFixed(1)}% cache${cacheRows.length < rows.length ? " (reported subset)" : ""}` : "Cache unavailable";
  const full = `${rows.length} provider steps · ${subtotal(rows.map(row=>row.input),"input")} · ${subtotal(rows.map(row=>row.output),"output")} · ${cache} · Cost unverified`;
  const glance = [
    `${rows.length} ${rows.length === 1 ? "step" : "steps"}`,
    ...[["in", rows.map(row=>row.input)], ["out", rows.map(row=>row.output)]].flatMap(([label, values]) => {
      const count = compactCount(values as (number | null)[]);
      return count ? [`${count} ${label}`] : [];
    }),
    ...(cachedInput ? [`${Math.round(100*cachedHit/cachedInput)}% cache`] : []),
  ].join(" · ");
  return <details className={compact ? "wb-agent-usage wb-agent-usage--compact" : "wb-agent-usage"} data-testid="agent-usage">
    {compact
      ? <summary title={full}>{glance}</summary>
      : <summary>{full}</summary>}
    <div className="wb-agent-usage__body">
    <p>Provider-reported snapshots for this session. Missing usage stays unknown. Retries may consume additional unreported tokens; these counts are not an invoice. Reasoning tokens are included in output, not added to it. Earlier branches retain their own call records after undo.</p>
    <div className="wb-agent-usage__scroll"><table aria-label="Agent provider usage by step">
      <thead><tr><th>Command / step</th><th>Model</th><th>Elapsed</th><th>First content</th><th>Input</th><th>Output</th><th>Total</th><th>Cache hit</th><th>Cache miss</th><th>Reasoning</th><th>Retries</th><th>Outcome / source</th></tr></thead>
      <tbody>{rows.map(({event,raw,input,output,total,hit,miss,reasoning})=><tr key={event.event_id}>
        <td title={String(event.payload.request_id)}>{event.command_id?.slice(-8) ?? "Unknown"} / {String(event.payload.provider_step)}</td>
        <td>{String(event.payload.model ?? "Unknown")}</td>
        <td>{seconds(event.payload.elapsed_s)}</td><td>{seconds(event.payload.first_public_s)}</td>
        <td>{input ?? "Unknown"}</td><td>{output ?? "Unknown"}</td><td>{total ?? "Unknown"}</td><td>{hit ?? "Unknown"}</td><td>{miss ?? "Unknown"}</td><td>{reasoning ?? "Unknown"}</td>
        <td>{count(event.payload.retries) ?? "Unknown"}</td><td>{String(event.payload.outcome)}<details><summary>Raw usage</summary>
          <p>Request: {String(event.payload.provider_request_id ?? "Unknown")} · event: {event.event_id}</p>
          <pre>{event.payload.usage_state === "reported" ? JSON.stringify(raw, null, 2) : "Unavailable"}</pre>
        </details></td>
      </tr>)}</tbody>
    </table></div>
    </div>
  </details>;
}
