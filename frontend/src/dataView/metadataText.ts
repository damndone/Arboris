// Plain-text editing of value labels and missing codes, SPSS style:
//   value labels:  1 = North; 2 = South
//   missing codes: -99, 999, 900..999, NA

import type { MissingCode } from "./dataViewApi";

export function formatValueLabels(labels: Record<string, string>): string {
  return Object.entries(labels)
    .map(([value, label]) => `${value} = ${label}`)
    .join("; ");
}

export function parseValueLabels(text: string): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const part of text.split(";")) {
    const entry = part.trim();
    if (!entry) continue;
    const separator = entry.indexOf("=");
    if (separator <= 0) throw new Error(`"${entry}" is not "value = label"`);
    const value = entry.slice(0, separator).trim();
    const label = entry.slice(separator + 1).trim();
    if (!value || !label) throw new Error(`"${entry}" needs both a value and a label`);
    if (value in labels) throw new Error(`value ${value} is labelled twice`);
    labels[value] = label;
  }
  return labels;
}

function formatCode(code: MissingCode): string {
  if (typeof code === "object") return `${code.low}..${code.high}`;
  return String(code);
}

export function formatMissingCodes(codes: MissingCode[]): string {
  return codes.map(formatCode).join(", ");
}

const RANGE = /^(-?\d+(?:\.\d+)?)\s*\.\.\s*(-?\d+(?:\.\d+)?)$/;
const NUMBER = /^-?\d+(?:\.\d+)?$/;

export function parseMissingCodes(text: string): MissingCode[] {
  const codes: MissingCode[] = [];
  for (const part of text.split(",")) {
    const token = part.trim();
    if (!token) continue;
    const range = RANGE.exec(token);
    if (range) {
      const low = Number(range[1]);
      const high = Number(range[2]);
      if (low > high) throw new Error(`range ${token} runs backwards`);
      codes.push({ low, high });
    } else if (NUMBER.test(token)) {
      codes.push(Number(token));
    } else {
      codes.push(token);
    }
  }
  return codes;
}

export function matchesMissingCode(value: unknown, codes: MissingCode[]): boolean {
  if (value === null || value === undefined) return false;
  return codes.some((code) => {
    if (typeof code === "object") {
      return typeof value === "number" && value >= code.low && value <= code.high;
    }
    if (typeof code === "number") return typeof value === "number" ? value === code : Number(value) === code;
    return String(value) === code;
  });
}

/** The label for a stored value, matching "2" to 2 and 2.0 as the server does. */
export function valueLabelFor(value: unknown, labels: Record<string, string>): string | undefined {
  if (value === null || value === undefined) return undefined;
  return labels[String(value)];
}
