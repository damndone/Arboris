import { describe, expect, it } from "vitest";

import { VIEW_TABS } from "./WorkbenchTopbar";
import { parseWorkbenchUrl } from "./state/urlSchema";

describe("Workbench Notebook route", () => {
  it("publishes Notebook as a first-class Workbench view", () => {
    expect(VIEW_TABS).toContainEqual({ id: "notebook", label: "Notebook" });
    expect(parseWorkbenchUrl(new URLSearchParams("view=notebook")).view).toBe("notebook");
  });
});
