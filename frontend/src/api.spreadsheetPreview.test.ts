// CSV and Excel are previewed by the server with the reader the run imports them
// with (2026-11-06 risk review, finding 4: the in-browser parser, xlsx 0.18.5, had
// known vulnerabilities and typed files differently from the import). The parsing
// itself is tested against the import in tests/test_upload_preview_tabular.py.
import { afterEach, describe, expect, it, vi } from "vitest";

import { previewFile } from "./api";

function serverPreview(body: Record<string, unknown>) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ labels: {}, sheet_names: [], selected_sheet: null, ...body }), {
      status: 200, headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("previewFile for spreadsheets", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks the server for a CSV and describes the columns it returns", async () => {
    const fetchMock = serverPreview({
      columns: ["outcome", "treatment", "revenue", "firm_id"],
      rows: [
        { outcome: 10, treatment: 1, revenue: 100, firm_id: "a" },
        { outcome: 12, treatment: 0, revenue: 120, firm_id: "b" },
        { outcome: 15, treatment: 1, revenue: 150, firm_id: "c" },
      ],
      total_rows: 3,
    });
    const preview = await previewFile(new File(["ignored"], "sample.csv"), undefined, undefined, "/project");
    expect(String(fetchMock.mock.calls[0][0])).toContain("/uploads/preview");
    expect(preview.rowCount).toBe(3);
    expect(preview.suggestedY).toBe("outcome");
    expect(preview.suggestedX).toEqual(["treatment", "revenue"]);
    expect(preview.columns.find((column) => column.name === "firm_id")).toMatchObject({ dtype: "string", suggestedRole: "id" });
  });

  it("sends the chosen sheet and transpose, and shows the workbook's sheets", async () => {
    const fetchMock = serverPreview({
      columns: ["x", "y"], rows: [{ x: 1, y: 2 }, { x: 3, y: 4 }, { x: 5, y: 6 }], total_rows: 3,
      sheet_names: ["First", "Second"], selected_sheet: "Second",
    });
    const preview = await previewFile(new File(["ignored"], "book.xlsx"), "Second", true, "/project");
    const form = fetchMock.mock.calls[0][1].body as FormData;
    expect(form.get("sheet_name")).toBe("Second");
    expect(form.get("transpose")).toBe("true");
    expect(form.get("project_root")).toBe("/project");
    expect(preview.sheetNames).toEqual(["First", "Second"]);
    expect(preview.selectedSheet).toBe("Second");
    expect(preview.rowCount).toBe(3);
  });

  it("reports the whole file's row count, not the sampled rows", async () => {
    serverPreview({ columns: ["a"], rows: [{ a: 1 }, { a: 2 }], total_rows: 6000 });
    const preview = await previewFile(new File(["ignored"], "big.csv"), undefined, undefined, "/project");
    expect(preview.rowCount).toBe(6000);
  });

  it("parses nothing in the browser without a project", async () => {
    const fetchMock = serverPreview({ columns: [], rows: [], total_rows: 0 });
    await expect(previewFile(new File(["a,b\n1,2\n"], "wages.csv"))).rejects.toThrow(/open project/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
