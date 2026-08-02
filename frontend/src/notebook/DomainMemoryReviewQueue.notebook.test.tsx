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

  it("does not present a proposed candidate as ready for user approval", () => {
    render(
      <DomainMemoryReviewQueue
        candidates={[{ candidate_id: "candidate-proposed", revision: 1, status: "proposed", memory_kind: "workflow_lesson", compact_lesson: "Await independent readiness review.", source_summary_refs: ["binding-1"] }]}
        onReview={vi.fn()}
      />,
    );

    expect(screen.getByText(/awaiting readiness review/i)).toBeInTheDocument();
    expect(screen.queryByTestId("domain-memory-review-approve-candidate-proposed")).not.toBeInTheDocument();
    expect(screen.getByTestId("domain-memory-review-reject-candidate-proposed")).toHaveTextContent("Discard candidate");
  });
});
