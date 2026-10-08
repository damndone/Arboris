/**
 * Column references in model formulas: `Q(<Python string literal>)`.
 *
 * The backend writes the literal with `repr(column)` (backend/workbench/
 * formula_terms.py): `Q('x')`, `Q("o'brien")` when the name holds a single
 * quote, and backslash escapes when it holds both quotes or a backslash.
 * Decoding the literal, rather than stripping quote characters, gives back
 * the user's column exactly.
 */

const STRING_LITERAL = String.raw`(?:'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")`;

/** A treatment-coded level: `C(Q('g'))[T.b]`, optionally with a contrast. */
const CATEGORICAL_LEVEL = new RegExp(String.raw`^C\(Q\((${STRING_LITERAL})\)(?:\s*,[^\[]*)?\)\[T\.`);

const SIMPLE_ESCAPES: Record<string, string> = {
  "\\": "\\",
  "'": "'",
  '"': '"',
  n: "\n",
  r: "\r",
  t: "\t",
};
const HEX_ESCAPE_LENGTH: Record<string, number> = { x: 2, u: 4, U: 8 };

/** The string a Python literal as `repr` writes it denotes; null for anything else. */
export function pythonStringValue(literal: string): string | null {
  const quote = literal[0];
  if (literal.length < 2 || (quote !== "'" && quote !== '"') || literal[literal.length - 1] !== quote) {
    return null;
  }
  const body = literal.slice(1, -1);
  let value = "";
  for (let index = 0; index < body.length; index += 1) {
    const char = body[index];
    if (char !== "\\") {
      value += char;
      continue;
    }
    index += 1;
    const escape = body[index];
    if (escape === undefined) return null;
    if (escape in SIMPLE_ESCAPES) {
      value += SIMPLE_ESCAPES[escape];
      continue;
    }
    const length = HEX_ESCAPE_LENGTH[escape];
    if (length === undefined) return null;
    const hex = body.slice(index + 1, index + 1 + length);
    if (hex.length !== length || !/^[0-9a-fA-F]+$/.test(hex)) return null;
    value += String.fromCodePoint(parseInt(hex, 16));
    index += length;
  }
  return value;
}

/** The column of a treatment-coded categorical term, or null for any other term. */
export function dummyCodedColumn(term: string): string | null {
  const match = CATEGORICAL_LEVEL.exec(term);
  return match ? pythonStringValue(match[1]) : null;
}
