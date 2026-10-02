/**
 * The one rule for showing a statistic.
 *
 * The same rule the Agent follows when it quotes a number: about four
 * significant digits, a large number keeps its integer digits, and a p-value
 * below 0.001 is written as such rather than as 0. Before v1.8.10 each view had
 * its own `fmt`; the report's regression table printed 0.9928945017762245 and
 * "p = 0".
 */

const MISSING = "—";

function finite(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function formatEstimate(value: number | null | undefined): string {
  if (!finite(value)) return MISSING;
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude >= 1000) {
    return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }
  if (magnitude < 1e-4) {
    const [mantissa, exponent] = value.toExponential(2).split("e");
    return `${Number(mantissa)}e${Number(exponent)}`;
  }
  return String(Number(value.toPrecision(4)));
}

export function formatPValue(value: number | null | undefined): string {
  if (!finite(value)) return MISSING;
  if (value < 0.001) return "< 0.001";
  return value.toFixed(3);
}

export function formatInterval(
  lower: number | null | undefined,
  upper: number | null | undefined,
): string {
  if (!finite(lower) || !finite(upper)) return MISSING;
  return `[${formatEstimate(lower)}, ${formatEstimate(upper)}]`;
}
