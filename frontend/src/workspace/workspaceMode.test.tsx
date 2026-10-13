import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test } from "vitest";
import { resolveWorkspaceMode, setWorkspaceMode, useWorkspaceMode } from "./workspaceMode";

function Probe() {
  return <span data-testid="mode">{useWorkspaceMode()}</span>;
}

describe("workspace mode switch", () => {
  beforeEach(() => localStorage.clear());

  test("the accepted new shell is default and explicit classic preference survives", () => {
    expect(resolveWorkspaceMode("", null)).toBe("new");
    expect(resolveWorkspaceMode("", "classic")).toBe("classic");
    expect(resolveWorkspaceMode("", "new")).toBe("new");
    expect(resolveWorkspaceMode("", "garbage")).toBe("new");
  });

  test("a URL parameter wins over the stored choice", () => {
    expect(resolveWorkspaceMode("?workspace=new", "classic")).toBe("new");
    expect(resolveWorkspaceMode("?workspace=classic", "new")).toBe("classic");
    expect(resolveWorkspaceMode("?workspace=other", "new")).toBe("new");
  });

  test("changing the setting updates every subscriber and is remembered", () => {
    render(<Probe />);
    expect(screen.getByTestId("mode")).toHaveTextContent("new");
    act(() => setWorkspaceMode("classic"));
    expect(screen.getByTestId("mode")).toHaveTextContent("classic");
    expect(localStorage.getItem("workbench:workspace")).toBe("classic");
  });
});
