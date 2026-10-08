import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, test } from "vitest";
import { ThemeProvider } from "../theme";
import { AppearanceSettings } from "./AppearanceSettings";

describe("AppearanceSettings", () => {
  beforeEach(() => localStorage.clear());

  test("chooses the theme and the workspace, and remembers both", () => {
    render(
      <ThemeProvider>
        <AppearanceSettings />
      </ThemeProvider>,
    );
    const theme = screen.getByRole("radiogroup", { name: "Theme" });
    fireEvent.click(within(theme).getByRole("radio", { name: "Dark" }));
    expect(within(theme).getByRole("radio", { name: "Dark" })).toBeChecked();
    expect(document.documentElement.dataset.theme).toBe("dark");

    const workspace = screen.getByRole("radiogroup", { name: "Workspace" });
    expect(within(workspace).getByRole("radio", { name: /Classic/ })).toBeChecked();
    fireEvent.click(within(workspace).getByRole("radio", { name: /New workspace/ }));
    expect(within(workspace).getByRole("radio", { name: /New workspace/ })).toBeChecked();
    expect(localStorage.getItem("workbench:workspace")).toBe("new");
  });
});
