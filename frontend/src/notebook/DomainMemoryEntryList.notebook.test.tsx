import "@testing-library/jest-dom/vitest";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DomainMemoryEntryList } from "./DomainMemoryEntryList";


describe("DomainMemoryEntryList", () => {
  it("labels memory as a non-authoritative hint and shows provenance refs", () => {
    render(
      <DomainMemoryEntryList
        projection={{
          outcome: "used",
          reason: "retrieved",
          entries: [{
            memory_id: "memory-1", revision: 2, content_hash: "a".repeat(64), memory_kind: "workflow_lesson",
            domain_tags: ["domain-a"], compact_lesson: "Inspect the registered assumption first.",
            recommended_effect_kind: "assumption_check_hint", recommended_target_refs: ["check-1"],
            source_summary_refs: ["binding-1"], match_reason: ["analysis_family"],
          }], omissions: [], bounded: true,
        }}
      />,
    );
    expect(screen.getByText(/non-authoritative/i)).toBeInTheDocument();
    expect(screen.getByText("Inspect the registered assumption first.")).toBeInTheDocument();
    expect(screen.getByText(/binding-1/)).toBeInTheDocument();
  });
});
