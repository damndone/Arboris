// The spreadsheet reader is loaded on first use (see bundleBoundaries.test);
// these read real CSV and XLSX bytes through that dynamic import.
import { describe, expect, it } from "vitest";
import * as XLSX from "xlsx";

import { previewFile } from "./api";

describe("previewFile for spreadsheets", () => {
  it("reads a CSV", async () => {
    const preview = await previewFile(new File(["wage,educ\n20.5,12\n18.1,16\n"], "wages.csv"));
    expect(preview.rowCount).toBe(2);
    expect(preview.columns.map((column) => column.name)).toEqual(["wage", "educ"]);
    expect(preview.previewRows[1]).toEqual({ wage: 18.1, educ: 16 });
  });

  it("lists the sheets of a workbook and reads the one asked for", async () => {
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([["a"], [1]]), "First");
    XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([["x", "y"], [1, 2], [3, 4], [5, 6]]), "Second");
    const bytes = XLSX.write(book, { type: "array", bookType: "xlsx" }) as ArrayBuffer;
    const preview = await previewFile(new File([bytes], "book.xlsx"), "Second");
    expect(preview.sheetNames).toEqual(["First", "Second"]);
    expect(preview.selectedSheet).toBe("Second");
    expect(preview.rowCount).toBe(3);
    expect(preview.columns.map((column) => column.name)).toEqual(["x", "y"]);
  });
});
