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
  const hit = count(raw.prompt_cache_hit_tokens ?? (raw.prompt_tokens_details as Record<string,unknown> | undefined)?.cached_tokens);
  return {event, input, output, hit: input !== null && hit !== null && hit <= input ? hit : null};
}
function subtotal(values: (number | null)[], name: string): string {
  const known = values.filter((value): value is number => value !== null);
  if (!known.length) return `${name[0].toUpperCase()+name.slice(1)} unavailable`;
  return `${known.reduce((sum,value)=>sum+value,0)} ${name}${known.length < values.length ? " (reported subtotal)" : ""}`;
}

export function AgentUsagePanel({events}: {events: AgentEvent[]}) {
  if (!events.length) return null;
  const rows = events.map(reported);
  const cacheRows = rows.filter(row=>row.input !== null && row.hit !== null);
  const cachedInput = cacheRows.reduce((sum,row)=>sum+row.input!,0);
  const cachedHit = cacheRows.reduce((sum,row)=>sum+row.hit!,0);
  const cache = cachedInput ? `${(100*cachedHit/cachedInput).toFixed(1)}% cache${cacheRows.length < rows.length ? " (reported subset)" : ""}` : "Cache unavailable";
  return <details className="wb-agent-usage" data-testid="agent-usage">
    <summary>{rows.length} provider steps · {subtotal(rows.map(row=>row.input),"input")} · {subtotal(rows.map(row=>row.output),"output")} · {cache} · Cost unverified</summary>
    <p>Provider-reported snapshots for this session. Missing usage stays unknown. Retries may consume additional unreported tokens; these counts are not an invoice. Earlier branches retain their own call records after undo.</p>
    <div className="wb-agent-usage__scroll"><table aria-label="Agent provider usage by step">
      <thead><tr><th>Command / step</th><th>Model</th><th>Elapsed</th><th>First content</th><th>Input</th><th>Output</th><th>Cache hit</th><th>Retries</th><th>Outcome</th></tr></thead>
      <tbody>{rows.map(({event,input,output,hit})=><tr key={event.event_id}>
        <td title={String(event.payload.request_id)}>{event.command_id?.slice(-8) ?? "Unknown"} / {String(event.payload.provider_step)}</td>
        <td>{String(event.payload.model ?? "Unknown")}</td>
        <td>{seconds(event.payload.elapsed_s)}</td><td>{seconds(event.payload.first_public_s)}</td>
        <td>{input ?? "Unknown"}</td><td>{output ?? "Unknown"}</td><td>{hit ?? "Unknown"}</td>
        <td>{count(event.payload.retries) ?? "Unknown"}</td><td>{String(event.payload.outcome)}</td>
      </tr>)}</tbody>
    </table></div>
  </details>;
}
