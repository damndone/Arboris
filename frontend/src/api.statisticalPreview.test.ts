import { afterEach, describe, expect, it, vi } from "vitest";

import { isStatisticalFile, previewFile, withoutDeclaredMissing } from "./api";

describe("previewFile for SPSS/Stata files", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("recognises statistical file names", () => {
    expect(["a.sav", "b.ZSAV", "c.dta"].map(isStatisticalFile)).toEqual([true, true, true]);
    expect(["a.csv", "b.xlsx", "sav.txt"].map(isStatisticalFile)).toEqual([false, false, false]);
  });

  it("asks the server and reports the whole file's row count", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          columns: ["wage", "educ"],
          rows: [
            { wage: 20.5, educ: 12 },
            { wage: 18.1, educ: -99 },
          ],
          total_rows: 5000,
          labels: {},
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const preview = await previewFile(new File(["x"], "survey.sav"), undefined, undefined, "/project");

    expect(String(fetchMock.mock.calls[0][0])).toContain("/uploads/preview");
    expect(preview.rowCount).toBe(5000);
    expect(preview.columns.map((column) => column.name)).toEqual(["wage", "educ"]);
    expect(preview.sheetNames).toEqual([]);
  });

  it("describes columns without their declared missing-value codes", async () => {
    // GSS-style: -100..-10 are "inapplicable", "no answer", ... and 9 is refused.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            columns: ["age", "happy"],
            rows: [
              { age: 30, happy: 1 },
              { age: 50, happy: 9 },
              { age: -100, happy: 2 },
              { age: -98, happy: 1 },
            ],
            total_rows: 4,
            labels: { user_missing_values: { age: [{ low: -100, high: -10 }], happy: [9] } },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const preview = await previewFile(new File(["x"], "gss.sav"), undefined, undefined, "/project");
    const age = preview.columns.find((column) => column.name === "age")!;
    const happy = preview.columns.find((column) => column.name === "happy")!;

    expect(age.mean).toBe(40);
    expect(age.uniqueCount).toBe(2);
    expect(age.missingRate).toBe(0.5);
    expect(happy.uniqueCount).toBe(2);
    // The preview table still shows the codes as stored.
    expect(preview.previewRows[2].age).toBe(-100);
  });

  it("matches string codes exactly and leaves undeclared columns alone", () => {
    const rows = [{ a: "NA", b: -1 }, { a: "ok", b: 2 }];
    expect(withoutDeclaredMissing(rows, { a: ["NA"] })).toEqual([{ a: null, b: -1 }, { a: "ok", b: 2 }]);
    expect(withoutDeclaredMissing(rows, undefined)).toBe(rows);
  });

  it("refuses without a project instead of misreading the file", async () => {
    await expect(previewFile(new File(["x"], "survey.dta"))).rejects.toThrow(/open project/);
  });
});
