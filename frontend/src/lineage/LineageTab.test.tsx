import "@testing-library/jest-dom/vitest";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LineageTab } from "./LineageTab";

const fixture = {
  schema_version: 2,
  run_id: "r1",
  legacy: false,
  stats: { node_count: 2, edge_count: 1, leaf_count: 1, has_dp_count: 0 },
  nodes: {
    "stage:raw": {
      id: "stage:raw",
      kind: "dataset_stage",
      display_label: "Raw",
      summary: "Raw: 10 rows × 2 cols",
      created_at: "2026-05-19T00:00:00Z",
      parent_stage_id: null,
      branch_id: "main",
      trust: "ok",
      trust_reason: null,
      archived: false,
      payload_ref: null,
      decision_points: [],
      annotations: [],
    },
    "model:ols_1": {
      id: "model:ols_1",
      kind: "model",
      display_label: "Primary OLS",
      summary: "OLS · HC1 · n = 10",
      created_at: "2026-05-19T00:00:01Z",
      parent_stage_id: null,
      branch_id: "main",
      trust: "ok",
      trust_reason: null,
      archived: false,
      payload_ref: null,
      decision_points: [],
      annotations: [],
    },
  },
  edges: {
    e1: {
      id: "e1",
      source_id: "stage:raw",
      target_id: "model:ols_1",
      op: "fit",
      params: {},
      reversible: false,
      inverse_op: null,
    },
  },
  branches: {},
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
afterEach(() => vi.clearAllMocks());

describe("LineageTab", () => {
  it("renders loading then graph on 200", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(fixture),
    );
    render(
      <MemoryRouter>
        <LineageTab projectRoot="/p" runId="r1" />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Loading lineage/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("Raw")).toBeInTheDocument(),
    );
  });

  it("shows legacy empty state when graph.legacy=true", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ ...fixture, legacy: true, nodes: {}, edges: {} }),
    );
    render(
      <MemoryRouter>
        <LineageTab projectRoot="/p" runId="r1" />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByText(/No lineage data/)).toBeInTheDocument(),
    );
  });

  it("shows 404 error state", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ detail: "missing" }, 404),
    );
    render(
      <MemoryRouter>
        <LineageTab projectRoot="/p" runId="r1" />
      </MemoryRouter>,
    );
    await waitFor(() => {
      const matches = screen.getAllByText(/Run not found/i);
      expect(matches.length).toBeGreaterThan(0);
    });
  });

  it("shows 422 error state with Try again button", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ detail: "corrupt" }, 422),
    );
    render(
      <MemoryRouter>
        <LineageTab projectRoot="/p" runId="r1" />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(
        screen.getByText(/Lineage data is corrupt/i),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /Try again/i }),
    ).toBeInTheDocument();
  });

  it("opens and closes Raw JSON with the global Cmd+J shortcut", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(fixture),
    );
    render(
      <MemoryRouter initialEntries={["/?node=model:ols_1"]}>
        <LineageTab projectRoot="/p" runId="r1" />
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("dialog", { name: "Primary OLS" }),
      ).toBeInTheDocument(),
    );

    const openEvent = createEvent.keyDown(window, {
      key: "j",
      metaKey: true,
      bubbles: true,
      cancelable: true,
    });
    const preventDefault = vi.spyOn(openEvent, "preventDefault");
    fireEvent(window, openEvent);

    expect(preventDefault).toHaveBeenCalled();
    expect(
      await screen.findByRole("dialog", { name: /Raw JSON/i }),
    ).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "j", metaKey: true });
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: /Raw JSON/i }),
      ).not.toBeInTheDocument(),
    );
  });
});
