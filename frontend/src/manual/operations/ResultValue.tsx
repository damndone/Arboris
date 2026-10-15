// v1.9.0 — a saved result, read rather than dumped: records become tables,
// objects become labelled lists, numbers keep six significant digits. The
// exact JSON stays one click away for anyone who needs it verbatim.

import type { ReactNode } from "react";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

const MAX_ROWS = 200;
const MAX_DEPTH = 4;
const numberFormat = new Intl.NumberFormat("en", { maximumSignificantDigits: 6 });

const isRecord = (value: Json): value is { [key: string]: Json } => typeof value === "object" && value !== null && !Array.isArray(value);
const isScalar = (value: Json) => value === null || typeof value !== "object";

export function label(key: string): string {
  const words = key.replace(/[_.]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

const smallFormat = new Intl.NumberFormat("en", { notation: "scientific", maximumSignificantDigits: 3 });

export function formatScalar(value: Json): string {
  if (value === null) return "—";
  if (typeof value === "number") {
    if (Number.isInteger(value) && Math.abs(value) < 1e15) return value.toLocaleString("en");
    // Tiny values (p-values above all) keep their magnitude instead of rounding to 0.
    return value !== 0 && Math.abs(value) < 1e-4 ? smallFormat.format(value) : numberFormat.format(value);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/** A record that reads as one table row: scalars, lists of scalars, and one
 *  level of flat sub-records (`effect: {r}` becomes the column "Effect r"). */
function flatRow(row: Json): { [key: string]: Json } | null {
  if (!isRecord(row)) return null;
  const flat: { [key: string]: Json } = {};
  for (const [key, value] of Object.entries(row)) {
    if (isScalar(value)) flat[key] = value;
    else if (Array.isArray(value) && value.every(isScalar)) flat[key] = value.map(formatScalar).join(", ");
    else if (isRecord(value) && Object.values(value).every(isScalar)) {
      for (const [sub, inner] of Object.entries(value)) flat[`${key} ${sub}`] = inner;
    } else return null;
  }
  return flat;
}

const empty = (value: Json | undefined) => value === undefined || value === null || value === "";

function Table({ rows }: { rows: Array<{ [key: string]: Json }> }) {
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))].filter((column) => rows.some((row) => !empty(row[column])));
  return (
    <div className="op-result__table">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column} scope="col">{label(column)}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, MAX_ROWS).map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column} data-numeric={typeof row[column] === "number" || undefined}>{formatScalar(row[column] ?? null)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > MAX_ROWS && <p className="op-result__more">First {MAX_ROWS} of {rows.length.toLocaleString("en")} rows.</p>}
    </div>
  );
}

function Value({ value, depth }: { value: Json; depth: number }): ReactNode {
  if (isScalar(value)) return <span data-numeric={typeof value === "number" || undefined}>{formatScalar(value)}</span>;
  if (depth >= MAX_DEPTH) return <code>{JSON.stringify(value)}</code>;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="op-result__none">None</span>;
    if (value.every(isScalar)) return <span>{value.map(formatScalar).join(", ")}</span>;
    const rows = value.map(flatRow);
    if (rows.every((row) => row !== null)) return <Table rows={rows as Array<{ [key: string]: Json }>} />;
    return (
      <ol className="op-result__list">
        {value.slice(0, MAX_ROWS).map((item, index) => <li key={index}><Value value={item} depth={depth + 1} /></li>)}
      </ol>
    );
  }
  // What was computed reads before how it was computed.
  const entries = Object.entries(value).sort(([a], [b]) => Number(/^results?$/.test(b)) - Number(/^results?$/.test(a)));
  if (entries.length === 0) return <span className="op-result__none">None</span>;
  return (
    <dl className="op-result__fields">
      {entries.map(([key, item]) => (
        <div key={key} data-block={!isScalar(item) || undefined}>
          <dt>{label(key)}</dt>
          <dd><Value value={item} depth={depth + 1} /></dd>
        </div>
      ))}
    </dl>
  );
}

export function ResultValue({ value }: { value: unknown }) {
  const json = value as Json;
  // A saved result is an envelope: the result, plus where it came from
  // (source, request, fingerprints). The result comes first.
  const envelope = isRecord(json) && isRecord(json.result) ? json : null;
  const provenance = envelope ? Object.fromEntries(Object.entries(envelope).filter(([key]) => key !== "result")) : null;
  return (
    <div className="op-result" aria-label="Analysis result">
      <Value value={envelope ? envelope.result : json} depth={0} />
      {provenance && Object.keys(provenance).length > 0 && (
        <details className="op-result__raw">
          <summary>Provenance</summary>
          <Value value={provenance} depth={1} />
        </details>
      )}
      <details className="op-result__raw">
        <summary>Exact JSON</summary>
        <pre>{JSON.stringify(value, null, 2)}</pre>
      </details>
    </div>
  );
}
