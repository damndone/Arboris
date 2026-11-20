import { describe, expect, it } from "vitest";
import { WORKSPACE_VIEWS } from "../workspace/WorkspaceTopbar";
import { parseWorkbenchUrl } from "./state/urlSchema";

describe("research comparison migration", () => {
  it("publishes Compare and maps old Notebook deep links without losing their record identity", () => {
    expect(WORKSPACE_VIEWS).toContainEqual({ id: "plans", label: "Compare" });
    expect(WORKSPACE_VIEWS.some(view => String(view.id) === "notebook")).toBe(false);
    const params = new URLSearchParams("view=notebook&notebook=nb_saved&focus=source");
    expect(parseWorkbenchUrl(params).view).toBe("plans");
    expect(params.get("notebook")).toBe("nb_saved");
  });
});
