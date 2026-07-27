import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DomainMemoryReviewQueue } from "./DomainMemoryReviewQueue";


describe("DomainMemoryReviewQueue", () => {
  it("keeps candidate review explicit and never presents approval as execution", () => {
    const onReview = vi.fn();
    render(
      <DomainMemoryReviewQueue
        candidates={[{ candidate_id: "candidate-1", revision: 2, status: "needs_review", memory_kind: "workflow_lesson", compact_lesson: "Inspect the registered assumption.", source_summary_refs: ["binding-1"] }]}
        onReview={onReview}
      />,
    );
    expect(screen.getByText(/no automatic execution/i)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("domain-memory-review-approve-candidate-1"));
    expect(onReview).toHaveBeenCalledWith("candidate-1", "approved", 2);
    expect(screen.queryByText(/run analysis/i)).not.toBeInTheDocument();
  });
});
