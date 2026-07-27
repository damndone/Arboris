import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OptionCard } from "./OptionCard";
import { canonicalOptionRevision } from "./fixtures/canonicalMocks";

describe("OptionCard — capability-bound execution declaration", () => {
  it("shows confirm-and-execute only when the server explicitly offers it", () => {
    const onConfirmAndExecute = vi.fn();
    const option = {
      ...canonicalOptionRevision(),
      contract_version: "1.2" as const,
      lifecycle_projection: "proposed" as const,
      materializable: true,
      evidence_refs: [],
      comparative_claims: [],
      recommendation_decision_id: "decision_capability",
      recommendation_status: "recommended" as const,
      capability_resolution_binding_ref: "a".repeat(64),
      execution_modes: ["materialize_only", "confirm_and_execute"] as Array<
        "materialize_only" | "confirm_and_execute"
      >,
      confirmAndExecute: true,
    };

    render(<OptionCard option={option} onConfirmAndExecute={onConfirmAndExecute} />);

    const button = screen.getByTestId("option-confirm-and-execute");
    expect(button).toBeEnabled();
    expect(screen.getByTestId("option-capability-binding")).toHaveTextContent(
      "server-bound capability",
    );
    fireEvent.click(button);
    expect(onConfirmAndExecute).toHaveBeenCalledWith(option);
  });

  it("does not invent the execution button for a materialize-only option", () => {
    render(<OptionCard option={canonicalOptionRevision()} />);
    expect(screen.queryByTestId("option-confirm-and-execute")).toBeNull();
  });
});
