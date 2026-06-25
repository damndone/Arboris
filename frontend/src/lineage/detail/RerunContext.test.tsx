/* RerunContext.test.tsx — v1.6.1.x forest rerun parent resolution.
 *
 * The blocker this guards: a deduped node shared across runs must fork from the
 * ACTIVE HEAD (the version being viewed), not from runs[0]. The provider is mounted
 * with runId = the active head; submitRerun resolves the parent against candidateRuns.
 * Mocked at the rerunFromNode boundary so we assert the POST target run id.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { rerunFromNodeMock } = vi.hoisted(() => ({ rerunFromNodeMock: vi.fn() }));
vi.mock("../../api", async () => {
  const mod = await vi.importActual<typeof import("../../api")>("../../api");
  return { ...mod, rerunFromNode: rerunFromNodeMock };
});

import { RerunProvider, useRerun } from "./RerunContext";
import type { RerunArgs } from "./RerunContext";

function Trigger({ args }: { args: RerunArgs }) {
  const rerun = useRerun()!;
  return (
    <button type="button" onClick={() => void rerun.submitRerun(args)}>
      go
    </button>
  );
}

function mount(activeHead: string, args: RerunArgs) {
  render(
    <RerunProvider projectRoot="/p" runId={activeHead} onRerun={() => {}}>
      <Trigger args={args} />
    </RerunProvider>,
  );
}

describe("RerunProvider submitRerun parent resolution", () => {
  beforeEach(() => {
    rerunFromNodeMock.mockReset();
    rerunFromNodeMock.mockResolvedValue({ run_id: "child_1" });
  });

  it("forks from the active head when it owns the shared node (NOT runs[0])", async () => {
    mount("run_c", {
      fromNode: "model:ols_1",
      opOverrides: { covariance: "robust" },
      candidateRuns: ["run_a", "run_b", "run_c"],
    });
    fireEvent.click(screen.getByText("go"));
    await waitFor(() => expect(rerunFromNodeMock).toHaveBeenCalledTimes(1));
    expect(rerunFromNodeMock.mock.calls[0][1]).toBe("run_c"); // parent run id (path arg)
  });

  it("forks from the first owning run when the active head doesn't own the node", async () => {
    mount("run_x", {
      fromNode: "model:ols_1",
      opOverrides: { covariance: "robust" },
      candidateRuns: ["run_a", "run_b"],
    });
    fireEvent.click(screen.getByText("go"));
    await waitFor(() => expect(rerunFromNodeMock).toHaveBeenCalledTimes(1));
    expect(rerunFromNodeMock.mock.calls[0][1]).toBe("run_a");
  });

  it("falls back to the active head when no candidateRuns are given", async () => {
    mount("run_head", {
      fromNode: "model:ols_1",
      opOverrides: { covariance: "robust" },
    });
    fireEvent.click(screen.getByText("go"));
    await waitFor(() => expect(rerunFromNodeMock).toHaveBeenCalledTimes(1));
    expect(rerunFromNodeMock.mock.calls[0][1]).toBe("run_head");
  });
});
