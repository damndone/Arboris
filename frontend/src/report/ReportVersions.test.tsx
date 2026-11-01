import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReportVersionPicker, restoreWritten, useReportVersions } from "./ReportVersions";

const mocks = vi.hoisted(() => ({ reportHistory: vi.fn(), saveReport: vi.fn(), fetchRunArtifacts: vi.fn() }));
vi.mock("../manual/manualApi", () => ({ reportHistory: mocks.reportHistory, saveReport: mocks.saveReport }));
vi.mock("../api", async (original) => ({ ...(await original<object>()), fetchRunArtifacts: mocks.fetchRunArtifacts }));

const written = (id: string, at: string, author: string, parent: string | null = null) => ({
  id, author, created_at: at, title: "T", text: "Body", document_id: "d", parent_report_id: parent, revision_number: 1,
  source_fingerprint: "sha256:a", facts: [{ id: "f1" }], figures: [],
});

function Harness({ onPick }: { onPick: (key: string) => void }) {
  const { versions } = useReportVersions("/p", "run", [{ id: "ai", generatedAt: "2026-11-02T00:00:00Z", model: "m", text: "x" } as never]);
  return versions.length ? <ReportVersionPicker versions={versions} selected={versions[0].key} onSelect={onPick} /> : null;
}

describe("report versions", () => {
  beforeEach(() => {
    mocks.reportHistory.mockResolvedValue({ reports: [written("mrpt_b", "2026-11-03T00:00:00Z", "agent"), written("mrpt_a", "2026-11-01T00:00:00Z", "user")] });
    mocks.fetchRunArtifacts.mockResolvedValue({ groups: [{ artifact_type: "report", items: [{ artifact_id: "report_html" }, { artifact_id: "workflow_report_x_html" }] }] });
    mocks.saveReport.mockReset();
  });

  it("lists every author's versions, newest first and numbered in the order they were made", async () => {
    const onPick = vi.fn();
    render(<Harness onPick={onPick} />);
    const picker = await screen.findByRole("combobox", { name: "Report version" }) as HTMLSelectElement;
    await waitFor(() => expect(picker.options).toHaveLength(4));
    const labels = [...picker.options].map((option) => option.textContent ?? "");
    expect(labels[0]).toMatch(/^Version 4 · Agent/);
    expect(labels[1]).toMatch(/^Version 3 · m/);
    expect(labels[2]).toMatch(/^Version 2 · You/);
    expect(labels[3]).toBe("Version 1 · Workflow");
    fireEvent.change(picker, { target: { value: "written:mrpt_a" } });
    expect(onPick).toHaveBeenCalledWith("written:mrpt_a");
  });

  it("restores an earlier version as a new one with the same words and evidence", async () => {
    await restoreWritten("/p", "run", written("mrpt_a", "t", "user") as never, written("mrpt_b", "t", "agent") as never);
    expect(mocks.saveReport).toHaveBeenCalledWith("/p", "run", expect.objectContaining({
      text: "Body", fact_ids: ["f1"], parent_report_id: "mrpt_b", source_fingerprint: "sha256:a",
    }));
    expect(mocks.saveReport.mock.calls[0][2].id).toMatch(/^mrpt_/);
    expect(mocks.saveReport.mock.calls[0][2].id).not.toBe("mrpt_a");
  });
});
