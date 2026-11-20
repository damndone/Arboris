import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, test } from "vitest";
import { ThemeProvider } from "../theme";
import { AppearanceSettings } from "./AppearanceSettings";

describe("AppearanceSettings", () => {
  beforeEach(() => localStorage.clear());

  test("keeps theme controls and retires the Classic layout switch", () => {
    render(
      <ThemeProvider>
        <AppearanceSettings />
      </ThemeProvider>,
    );
    const theme = screen.getByRole("radiogroup", { name: "Theme" });
    fireEvent.click(within(theme).getByRole("radio", { name: "Dark" }));
    expect(within(theme).getByRole("radio", { name: "Dark" })).toBeChecked();
    expect(document.documentElement.dataset.theme).toBe("dark");

    expect(screen.queryByRole("radiogroup", { name: "Workspace" })).toBeNull();
    expect(screen.queryByText("Classic")).toBeNull();
  });
});
