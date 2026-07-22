import { describe, expect, test, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useArmaGarchArtifacts } from "./useArmaGarchArtifacts";
import { fetchArtifactJson, fetchRunArtifacts } from "../api";

vi.mock("../api", () => ({
  fetchRunArtifacts: vi.fn(),
  fetchArtifactJson: vi.fn(),
}));

const groupsWith = (ids: string[]) => ({
  groups: [{ items: ids.map((artifact_id) => ({ artifact_id })) }],
});

beforeEach(() => {
  vi.mocked(fetchRunArtifacts).mockReset();
  vi.mocked(fetchArtifactJson).mockReset();
});

test("returns undefined when the run has no ts.report artifact", async () => {
  vi.mocked(fetchRunArtifacts).mockResolvedValue(groupsWith(["ols_1"]) as never);
  const { result } = renderHook(() => useArmaGarchArtifacts("/p", "run_a"));
  await waitFor(() => expect(fetchRunArtifacts).toHaveBeenCalled());
  expect(result.current).toBeUndefined();
  expect(fetchArtifactJson).not.toHaveBeenCalled();
});

test("maps each ts.* artifact to its field and unwraps the payload", async () => {
  vi.mocked(fetchRunArtifacts).mockResolvedValue(
    groupsWith(["ts.report", "ts.arma_candidates"]) as never,
  );
  vi.mocked(fetchArtifactJson).mockImplementation(
    async (_root: unknown, _run: unknown, artifactId: unknown) =>
      ({ payload: { id: artifactId } }) as never,
  );

  const { result } = renderHook(() => useArmaGarchArtifacts("/p", "run_a"));

  await waitFor(() => expect(result.current).toBeDefined());
  expect(result.current?.report).toEqual({ id: "ts.report" });
  expect(result.current?.meanCandidates).toEqual({ id: "ts.arma_candidates" });
  // absent artifacts are not fetched and stay undefined
  expect(result.current?.comparison).toBeUndefined();
});

test("returns undefined without a projectRoot or runId", async () => {
  const { result } = renderHook(() => useArmaGarchArtifacts(null, null));
  expect(result.current).toBeUndefined();
  expect(fetchRunArtifacts).not.toHaveBeenCalled();
});
