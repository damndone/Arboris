import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test } from "vitest";
import { resolveWorkspaceMode, setWorkspaceMode, useWorkspaceMode } from "./workspaceMode";

function Probe() {
  return <span data-testid="mode">{useWorkspaceMode()}</span>;
}

describe("workspace mode switch", () => {
  beforeEach(() => localStorage.clear());

  test("the classic shell stays the default until the new one is accepted", () => {
    expect(resolveWorkspaceMode("", null)).toBe("classic");
    expect(resolveWorkspaceMode("", "new")).toBe("new");
    expect(resolveWorkspaceMode("", "garbage")).toBe("classic");
  });

  test("a URL parameter wins over the stored choice", () => {
    expect(resolveWorkspaceMode("?workspace=new", "classic")).toBe("new");
    expect(resolveWorkspaceMode("?workspace=classic", "new")).toBe("classic");
    expect(resolveWorkspaceMode("?workspace=other", "new")).toBe("new");
  });

  test("changing the setting updates every subscriber and is remembered", () => {
    render(<Probe />);
    expect(screen.getByTestId("mode")).toHaveTextContent("classic");
    act(() => setWorkspaceMode("new"));
    expect(screen.getByTestId("mode")).toHaveTextContent("new");
    expect(localStorage.getItem("workbench:workspace")).toBe("new");
  });
});
