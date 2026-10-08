import { describe, expect, it } from "vitest";

import { dummyCodedColumn, pythonStringValue } from "./formulaTerms";

// Terms exactly as the backend writes them: `C(Q(<repr(column)>))[T.<level>]`.
const CASES: Array<[string, string]> = [
  ["C(Q('x'))[T.b]", "x"],
  [`C(Q("o'brien"))[T.b]`, "o'brien"],
  [`C(Q('say "hi"'))[T.b]`, 'say "hi"'],
  [`C(Q('both \\' and " quotes'))[T.b]`, `both ' and " quotes`],
  ["C(Q('back\\\\slash'))[T.b]", "back\\slash"],
  ["C(Q('tab\\there'))[T.b]", "tab\there"],
  ["C(Q('收入 (元)'))[T.b]", "收入 (元)"],
  ["C(Q('nul\\x00'))[T.b]", "nul\u0000"],
  ["C(Q('g'), Sum)[T.b]", "g"],
];

describe("dummyCodedColumn", () => {
  it.each(CASES)("recovers the column of %s", (term, column) => {
    expect(dummyCodedColumn(term)).toBe(column);
  });

  it.each(["x", "Q('x')", "C(x)[T.b]", "C(Q('x'))", "C(Q('x)[T.b]"])("ignores %s", (term) => {
    expect(dummyCodedColumn(term)).toBeNull();
  });
});

describe("pythonStringValue", () => {
  it("rejects escapes repr never writes", () => {
    expect(pythonStringValue("'\\q'")).toBeNull();
    expect(pythonStringValue("'\\x4'")).toBeNull();
  });
});
