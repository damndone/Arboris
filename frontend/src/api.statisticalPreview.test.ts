import { afterEach, describe, expect, it, vi } from "vitest";

import { isStatisticalFile, previewFile } from "./api";

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

  it("refuses without a project instead of misreading the file", async () => {
    await expect(previewFile(new File(["x"], "survey.dta"))).rejects.toThrow(/open project/);
  });
});
