import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DomainMemoryControls } from "./DomainMemoryControls";


describe("DomainMemoryControls", () => {
  it("keeps use and iteration independent and visibly default-off", () => {
    const onChange = vi.fn();
    render(
      <DomainMemoryControls
        preferences={{ cross_project_domain_memory_use: false, cross_project_domain_memory_iteration: false }}
        onChange={onChange}
      />,
    );
    expect(screen.getByTestId("domain-memory-use")).not.toBeChecked();
    expect(screen.getByTestId("domain-memory-iteration")).not.toBeChecked();
    fireEvent.click(screen.getByTestId("domain-memory-use"));
    expect(onChange).toHaveBeenCalledWith({ cross_project_domain_memory_use: true, cross_project_domain_memory_iteration: false });
  });
});
