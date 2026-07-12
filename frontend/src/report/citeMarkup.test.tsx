import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CiteChip, formatFactValue, parseCiteSegments } from "./citeMarkup";
import type { CitableFact } from "./factTable";

const fact: CitableFact = {
  id: "c1",
  node_key: "hash_model",
  node_label: "OLS model",
  field: "metric:r_squared",
  label: "r_squared",
  value: 0.8559,
};

describe("parseCiteSegments", () => {
  it("splits text around [[c:ID]] markers", () => {
    expect(parseCiteSegments("R² was 0.86 [[c:c1]] using HC1 [[c:c2]].")).toEqual([
      { type: "text", text: "R² was 0.86 " },
      { type: "cite", id: "c1" },
      { type: "text", text: " using HC1 " },
      { type: "cite", id: "c2" },
      { type: "text", text: "." },
    ]);
  });

  it("text without markers is a single segment", () => {
    expect(parseCiteSegments("no citations here")).toEqual([
      { type: "text", text: "no citations here" },
    ]);
  });
});

describe("CiteChip", () => {
  it("verified chip renders the LOCAL fact value and jumps to its node", () => {
    const onJump = vi.fn();
    render(<CiteChip id="c1" fact={fact} onJump={onJump} />);
    const chip = screen.getByTestId("cite-chip");
    expect(chip.textContent).toContain("r_squared");
    expect(chip.textContent).toContain("0.8559");
    fireEvent.click(chip);
    expect(onJump).toHaveBeenCalledWith("hash_model");
  });

  it("unknown citation id renders an explicit unverified chip", () => {
    render(<CiteChip id="c99" fact={undefined} />);
    expect(screen.getByTestId("cite-chip-unverified")).toBeInTheDocument();
  });
});

describe("formatFactValue", () => {
  it("trims float noise but keeps integers and strings", () => {
    expect(formatFactValue(0.855900001)).toBe("0.8559");
    expect(formatFactValue("HC1")).toBe("HC1");
    expect(formatFactValue(60)).toBe("60");
  });
});
