import { expect, test, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { FailureCard } from "./FailureCard";
import type { FailureEvidence, RecommendedAction } from "./FailureCard";
import sampleActionsJson from "../../../tests/contracts/recommended_actions.model_fit_failure.sample.json";

const sampleActions = sampleActionsJson as RecommendedAction[];

const sampleEvidence: FailureEvidence = {
  error_code: "MODEL_FIT_FAILED",
  requested_model_type: "logit",
  root_cause: "ValueError: y must be binary (got 40 unique continuous values)",
  y_type: "continuous",
  recommended_actions: sampleActions,
};

test("renders the requested model name + root cause", () => {
  render(<FailureCard evidence={sampleEvidence} onAction={() => {}} />);
  expect(screen.getByText(/logit/)).toBeInTheDocument();
  expect(screen.getByText(/y must be binary/)).toBeInTheDocument();
});

test("renders one button per recommended_action", () => {
  render(<FailureCard evidence={sampleEvidence} onAction={() => {}} />);
  for (const action of sampleActions) {
    expect(screen.getByRole("button", { name: action.label })).toBeInTheDocument();
  }
});

test("clicking an action calls onAction with the action object", () => {
  const onAction = vi.fn();
  render(<FailureCard evidence={sampleEvidence} onAction={onAction} />);
  fireEvent.click(screen.getByRole("button", { name: "Re-run with auto" }));
  expect(onAction).toHaveBeenCalledTimes(1);
  expect(onAction.mock.calls[0][0]).toBe(sampleActions[0]);
});

test("primary action has different visual styling than secondary", () => {
  render(<FailureCard evidence={sampleEvidence} onAction={() => {}} />);
  const primary = screen.getByRole("button", { name: "Re-run with auto" });
  const secondary = screen.getByRole("button", { name: "Change model type" });
  expect(primary.className).not.toEqual(secondary.className);
});

test("renders nothing when no recommended_actions present", () => {
  const { container } = render(
    <FailureCard evidence={{ error_code: "X", root_cause: "y" }} onAction={() => {}} />,
  );
  // Component should still render the story (root_cause) but no button row.
  expect(screen.getByText(/y/)).toBeInTheDocument();
  expect(container.querySelectorAll("button").length).toBe(0);
});
