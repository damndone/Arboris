// Recode rules as text, one per line, SPSS style:
//   18..29 = 1        a closed range
//   bj = north        a single value
//   missing = 9       what missing values become (otherwise they stay missing)
//   else = copy       every other value (copy keeps it; else = missing drops it)

export type RecodeRule = {
  from: number | string | { low: number; high: number };
  to: number | string | null;
};

const NUMBER = /^-?\d+(?:\.\d+)?$/;
const RANGE = /^(-?\d+(?:\.\d+)?)\s*\.\.\s*(-?\d+(?:\.\d+)?)$/;

function parseTarget(text: string): number | string | null {
  if (text === "missing") return null;
  if (NUMBER.test(text)) return Number(text);
  return text;
}

export function parseRecodeRules(text: string): RecodeRule[] {
  const rules: RecodeRule[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const separator = line.lastIndexOf("=");
    if (separator <= 0) throw new Error(`"${line}" is not "from = to"`);
    const from = line.slice(0, separator).trim();
    const to = line.slice(separator + 1).trim();
    if (!from || !to) throw new Error(`"${line}" needs both sides`);
    const range = RANGE.exec(from);
    let origin: RecodeRule["from"];
    if (range) {
      const low = Number(range[1]);
      const high = Number(range[2]);
      if (low > high) throw new Error(`range ${from} runs backwards`);
      origin = { low, high };
    } else if (from === "missing" || from === "else") {
      origin = from;
    } else {
      origin = NUMBER.test(from) ? Number(from) : from;
    }
    rules.push({ from: origin, to: to === "copy" ? "copy" : parseTarget(to) });
  }
  if (rules.length === 0) throw new Error("add at least one rule");
  return rules;
}
