import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { ResearchCurve } from "./ResearchCurve";

it("preserves long time identities and exact values when inspecting irregularly spaced points", () => {
  const first = "9000000000000000123";
  const middle = "9000000000000001123";
  const last = "9000000010000000123";
  render(<ResearchCurve title="Forecast" xLabel="Period" yLabel="Value" bandLabel="95% interval"
    points={[
      { position: 0, time: first, value: 100000000 },
      { position: 3, time: middle, value: 100000001, lower: 100000000, upper: 100000002 },
      { position: 150, time: last, value: 100000002 },
    ]}
    formatValue={(number) => number.toExponential(0)} />);

  const chart = screen.getByRole("img", { name: "Forecast" });
  expect(within(chart).getByText(first)).toBeVisible();
  expect(within(chart).getByText(last)).toBeVisible();
  const coordinates = chart.querySelector("polyline")?.getAttribute("points") ?? "";
  const [left, near, right] = coordinates.split(" ").map((pair) => Number(pair.split(",")[0]));
  expect((near - left) / (right - left)).toBeCloseTo(3 / 150);
  fireEvent(chart, new MouseEvent("pointermove", { bubbles: true, clientX: near }));
  const tooltip = screen.getByRole("tooltip", { name: "Forecast details" });
  expect(tooltip).toHaveTextContent(middle);
  expect(tooltip).toHaveTextContent("100000001");
  expect(tooltip).toHaveTextContent("100000000 to 100000002");
  fireEvent.keyDown(chart, { key: "End" });
  expect(tooltip).toHaveTextContent(last);
  fireEvent.keyDown(chart, { key: "Escape" });
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("draws portfolio and benchmark on one scale and inspects the same saved period", () => {
  render(<ResearchCurve title="Walk-forward equity" xLabel="Evaluation period" yLabel="Equity"
    points={[{ position: 4, time: "2020-01-04", value: 102 }, { position: 5, time: "2020-01-05", value: 110 }]}
    comparison={{ primary: "Minimum variance", label: "Equal weights", values: [80, 91] }}
    formatValue={String} />);
  const chart = screen.getByRole("img", { name: "Walk-forward equity" });
  expect(within(chart).getByText("80")).toBeVisible();
  expect(chart.querySelectorAll("polyline")).toHaveLength(2);
  fireEvent.keyDown(chart, { key: "End" });
  const details = screen.getByRole("tooltip", { name: "Walk-forward equity details" });
  expect(details).toHaveTextContent("2020-01-05");
  expect(details).toHaveTextContent("Minimum variance110");
  expect(details).toHaveTextContent("Equal weights91");
});
