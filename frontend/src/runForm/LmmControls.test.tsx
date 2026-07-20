import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { LmmControls } from "./LmmControls";

test("collects the explicit LMM subject, time, group, and random-slope choices", () => {
  const onChange = vi.fn();
  render(
    <LmmControls
      columns={["participant_id", "week", "arm"]}
      value={{ subject_id: "", time: "", group: "", fit_method: "reml", random_slope: true }}
      onChange={onChange}
    />,
  );

  fireEvent.change(screen.getByLabelText("LMM subject"), { target: { value: "participant_id" } });
  fireEvent.change(screen.getByLabelText("LMM time"), { target: { value: "week" } });
  fireEvent.change(screen.getByLabelText("LMM group"), { target: { value: "arm" } });
  fireEvent.click(screen.getByLabelText("LMM random slope"));

  expect(onChange).toHaveBeenNthCalledWith(1, expect.objectContaining({ subject_id: "participant_id" }));
  expect(onChange).toHaveBeenNthCalledWith(2, expect.objectContaining({ time: "week" }));
  expect(onChange).toHaveBeenNthCalledWith(3, expect.objectContaining({ group: "arm" }));
  expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ random_slope: false }));
});
