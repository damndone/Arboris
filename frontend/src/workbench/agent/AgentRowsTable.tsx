import type { AgentMessage } from "./agentTypes";

export type ShownRows = {
  run_id: string;
  node_id: string;
  columns: string[];
  total_rows: number;
  row_numbers: number[];
  rows: Record<string, unknown>[];
};

/** The rows a `show_dataset_rows` tool call put on screen, or null.
 *
 * The full result stays in the local session; under the default sharing
 * policy the provider only received a summary of it. */
export function shownRows(message: AgentMessage): ShownRows | null {
  if (message.role !== "tool" || message.name !== "show_dataset_rows") return null;
  let payload: unknown;
  try {
    payload = JSON.parse(message.content);
  } catch {
    return null;
  }
  const output = (payload as { ok?: unknown; output?: unknown } | null)?.output as Partial<ShownRows> | undefined;
  if ((payload as { ok?: unknown }).ok !== true || !output || !Array.isArray(output.rows) || !Array.isArray(output.columns)) {
    return null;
  }
  return {
    run_id: String(output.run_id ?? ""),
    node_id: String(output.node_id ?? ""),
    columns: output.columns.map(String),
    total_rows: Number(output.total_rows ?? output.rows.length),
    row_numbers: Array.isArray(output.row_numbers) ? output.row_numbers.map(Number) : [],
    rows: output.rows as Record<string, unknown>[],
  };
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(7)));
  return String(value);
}

export function AgentRowsTable({ shown }: { shown: ShownRows }) {
  const first = shown.row_numbers[0];
  const last = shown.row_numbers[shown.row_numbers.length - 1];
  const cell = { padding: "1px 6px", textAlign: "left" as const, whiteSpace: "nowrap" as const };
  return (
    <div data-testid="agent-shown-rows" className="wb-agent-terminal-line" data-role="tool" style={{ alignItems: "flex-start", fontSize: 12 }}>
      <span className="wb-agent-terminal-marker" aria-hidden="true">▦</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ color: "var(--label-secondary)", marginBottom: 2 }}>
          {shown.node_id} · rows {first ?? "—"}–{last ?? "—"} of {shown.total_rows} · shown here on your computer
        </div>
        <div style={{ overflowX: "auto", maxHeight: 320, overflowY: "auto" }} tabIndex={0} aria-label={`Rows of ${shown.node_id}`}>
          <table style={{ borderCollapse: "collapse", fontVariantNumeric: "tabular-nums" }}>
            <thead>
              <tr style={{ color: "var(--label-secondary)" }}>
                <th style={cell}>#</th>
                {shown.columns.map((column) => (
                  <th key={column} style={cell}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.rows.map((row, index) => (
                <tr key={shown.row_numbers[index] ?? index} style={{ borderTop: "1px solid var(--separator)" }}>
                  <td style={{ ...cell, color: "var(--label-tertiary)" }}>{shown.row_numbers[index] ?? index + 1}</td>
                  {shown.columns.map((column) => (
                    <td key={column} style={cell}>{cellText(row[column])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
