import "@testing-library/jest-dom/vitest";

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemorySettingsPanel } from "./MemorySettingsPanel";
import {
  archiveMemoryLibraryEntries,
  fetchDomainMemorySettings,
  issueArchiveMemoryConfirmation,
  issueMemorySettingsConfirmation,
  listDomainMemoryCandidates,
  listDomainMemoryLibrary,
  reviewDomainMemoryCandidate,
  updateGlobalMemorySettings,
  updateProjectMemorySetting,
} from "../notebook/domainMemoryApi";

vi.mock("../notebook/domainMemoryApi", () => ({
  archiveMemoryLibraryEntries: vi.fn(),
  fetchDomainMemorySettings: vi.fn(),
  issueArchiveMemoryConfirmation: vi.fn(),
  issueMemorySettingsConfirmation: vi.fn(),
  listDomainMemoryCandidates: vi.fn(),
  listDomainMemoryLibrary: vi.fn(),
  reviewDomainMemoryCandidate: vi.fn(),
  updateGlobalMemorySettings: vi.fn(),
  updateProjectMemorySetting: vi.fn(),
}));

const settings = {
  global: { revision: 0, library_enabled: false },
  project: {
    revision: 0,
    library_enabled: false,
    inherit_global: false,
    candidate_generation_enabled: false,
  },
  memory_authority: "server_owned" as const,
};

describe("MemorySettingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchDomainMemorySettings).mockResolvedValue(settings);
    vi.mocked(listDomainMemoryCandidates).mockResolvedValue({ candidates: [], memory_authority: "server_owned" });
    vi.mocked(listDomainMemoryLibrary).mockResolvedValue({ library: "global", entries: [], memory_authority: "server_owned" });
    vi.mocked(issueMemorySettingsConfirmation).mockResolvedValue({
      receipt: "receipt-1",
      action: "enable_global_library",
      scope_ref: "scope-global",
      expected_revision: 0,
      target_count: 0,
      expires_at: "2026-08-01T00:05:00Z",
    });
    vi.mocked(updateGlobalMemorySettings).mockResolvedValue({
      ...settings,
      global: { revision: 1, library_enabled: true },
    });
  });

  it("keeps all libraries off initially and requires a second confirmation before enabling", async () => {
    vi.mocked(fetchDomainMemorySettings)
      .mockResolvedValueOnce(settings)
      .mockResolvedValue({ ...settings, global: { revision: 1, library_enabled: true } });
    render(<MemorySettingsPanel projectRoot="/project-a" />);

    expect(await screen.findByTestId("memory-settings-panel")).toHaveTextContent("Off");
    fireEvent.click(screen.getByRole("button", { name: "Enable global library" }));

    expect(await screen.findByRole("dialog", { name: "Confirm memory change" })).toHaveTextContent("No automatic execution");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(updateGlobalMemorySettings).toHaveBeenCalledWith(
      "/project-a",
      { library_enabled: true, expected_revision: 0, confirmation_receipt: "receipt-1" },
    ));
    expect(await screen.findByRole("button", { name: "Disable global library" })).toBeInTheDocument();
  });

  it("shows enough safe context to archive the intended memory", async () => {
    vi.mocked(listDomainMemoryLibrary).mockImplementation(async (_projectRoot, library) => ({
      library,
      memory_authority: "server_owned",
      entries: library === "global" ? [{
        memory_id: "memory-ols-convention",
        revision: 2,
        validity_revision: 1,
        state: "active",
        memory_kind: "workflow_lesson",
        domain_tags: ["econometrics"],
        compact_lesson: "Use HC1 covariance for this convention.",
        apply_mode: "suggest_default",
      }] : [],
    }));
    render(<MemorySettingsPanel projectRoot="/project-a" />);

    expect(await screen.findByText("Use HC1 covariance for this convention.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
  });

  it("shows a pending project candidate and refreshes the server-owned queue after an explicit rejection", async () => {
    vi.mocked(listDomainMemoryCandidates)
      .mockResolvedValueOnce({
        candidates: [{
          candidate_id: "candidate-1",
          revision: 2,
          status: "needs_review",
          memory_kind: "workflow_lesson",
          compact_lesson: "Inspect the registered assumption.",
          source_summary_refs: ["binding-1"],
        }],
        memory_authority: "server_owned",
      })
      .mockResolvedValue({ candidates: [], memory_authority: "server_owned" });
    vi.mocked(reviewDomainMemoryCandidate).mockResolvedValue({ automatic_execution: false });
    render(<MemorySettingsPanel projectRoot="/project-a" />);

    expect(await screen.findByText("Inspect the registered assumption.")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("domain-memory-review-reject-candidate-1"));

    await waitFor(() => expect(reviewDomainMemoryCandidate).toHaveBeenCalledWith(
      "/project-a",
      "candidate-1",
      { decision: "rejected", expected_revision: 2, actor_id: "local-user" },
    ));
    expect(await screen.findByText("No pending memory candidates.")).toBeInTheDocument();
  });

  it("sends an explicit approval timestamp and review schedule for a candidate", async () => {
    vi.mocked(listDomainMemoryCandidates).mockResolvedValueOnce({
      candidates: [{
        candidate_id: "candidate-approval",
        revision: 3,
        status: "needs_review",
        memory_kind: "workflow_lesson",
        compact_lesson: "Only an explicit review may publish this memory.",
        source_summary_refs: ["binding-1"],
      }],
      memory_authority: "server_owned",
    }).mockResolvedValue({ candidates: [], memory_authority: "server_owned" });
    vi.mocked(reviewDomainMemoryCandidate).mockResolvedValue({ automatic_execution: false });
    render(<MemorySettingsPanel projectRoot="/project-a" />);

    await screen.findByText("Only an explicit review may publish this memory.");
    fireEvent.click(screen.getByTestId("domain-memory-review-approve-candidate-approval"));

    await waitFor(() => expect(reviewDomainMemoryCandidate).toHaveBeenCalledOnce());
    expect(reviewDomainMemoryCandidate).toHaveBeenCalledWith(
      "/project-a",
      "candidate-approval",
      expect.objectContaining({
        decision: "approved",
        expected_revision: 3,
        actor_id: "local-user",
        approved_at: expect.any(String),
        review_after: expect.any(String),
      }),
    );
  });

  it("keeps settings and libraries available when only the candidate queue is unavailable", async () => {
    vi.mocked(listDomainMemoryCandidates).mockRejectedValueOnce(new Error("queue unavailable"));
    render(<MemorySettingsPanel projectRoot="/project-a" />);

    expect(await screen.findByTestId("memory-settings-panel")).toHaveTextContent("Candidate review is temporarily unavailable");
    expect(screen.getByRole("button", { name: "Enable global library" })).toBeInTheDocument();
    expect(screen.getAllByText("No approved memory yet.")).toHaveLength(2);
  });

  it.each(["DOMAIN_MEMORY_CANDIDATE_STALE", "DOMAIN_MEMORY_CONFLICT_REVIEW_REQUIRED"])(
    "keeps a candidate visible and shows the fail-closed review error for %s",
    async (failureCode) => {
      vi.mocked(listDomainMemoryCandidates).mockResolvedValueOnce({
        candidates: [{
          candidate_id: "candidate-failure",
          revision: 1,
          status: "needs_review",
          memory_kind: "workflow_lesson",
          compact_lesson: "Keep the review decision explicit.",
          source_summary_refs: ["binding-1"],
        }],
        memory_authority: "server_owned",
      });
      vi.mocked(reviewDomainMemoryCandidate).mockRejectedValueOnce(new Error(failureCode));
      render(<MemorySettingsPanel projectRoot="/project-a" />);

      await screen.findByText("Keep the review decision explicit.");
      fireEvent.click(screen.getByTestId("domain-memory-review-approve-candidate-failure"));

      expect(await screen.findByRole("alert")).toHaveTextContent(failureCode);
      expect(screen.getByTestId("domain-memory-review-approve-candidate-failure")).toBeInTheDocument();
    },
  );

  it("does not let a slower former project overwrite the current project memory view", async () => {
    let releaseFormerProject: (() => void) | undefined;
    const formerProject = new Promise<typeof settings>((resolve) => {
      releaseFormerProject = () => resolve(settings);
    });
    const currentProject = {
      ...settings,
      project: { ...settings.project, revision: 1, library_enabled: true },
    };
    vi.mocked(fetchDomainMemorySettings).mockImplementation((projectRoot) => (
      projectRoot === "/project-a" ? formerProject : Promise.resolve(currentProject)
    ));
    vi.mocked(listDomainMemoryLibrary).mockImplementation(async (_projectRoot, library) => ({
      library,
      entries: [],
      memory_authority: "server_owned",
    }));
    vi.mocked(listDomainMemoryCandidates).mockResolvedValue({ candidates: [], memory_authority: "server_owned" });

    const { rerender } = render(<MemorySettingsPanel projectRoot="/project-a" />);
    rerender(<MemorySettingsPanel projectRoot="/project-b" />);

    expect(await screen.findByRole("button", { name: "Disable project library" })).toBeInTheDocument();
    await act(async () => {
      releaseFormerProject?.();
      await formerProject;
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "Disable project library" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Enable project library" })).not.toBeInTheDocument();
  });

  it("does not refresh a former project after its candidate review returns", async () => {
    let releaseReview: (() => void) | undefined;
    const reviewResult = new Promise<{ automatic_execution: false }>((resolve) => {
      releaseReview = () => resolve({ automatic_execution: false });
    });
    const currentProject = {
      ...settings,
      project: { ...settings.project, revision: 1, library_enabled: true },
    };
    vi.mocked(fetchDomainMemorySettings).mockImplementation((projectRoot) => Promise.resolve(
      projectRoot === "/project-a" ? settings : currentProject,
    ));
    vi.mocked(listDomainMemoryLibrary).mockImplementation(async (_projectRoot, library) => ({
      library,
      entries: [],
      memory_authority: "server_owned",
    }));
    vi.mocked(listDomainMemoryCandidates).mockImplementation(async (projectRoot) => ({
      candidates: projectRoot === "/project-a" ? [{
        candidate_id: "candidate-slow-review",
        revision: 1,
        status: "needs_review",
        memory_kind: "workflow_lesson",
        compact_lesson: "Do not refresh a project that is no longer open.",
        source_summary_refs: ["binding-1"],
      }] : [],
      memory_authority: "server_owned",
    }));
    vi.mocked(reviewDomainMemoryCandidate).mockReturnValueOnce(reviewResult);

    const { rerender } = render(<MemorySettingsPanel projectRoot="/project-a" />);
    await screen.findByText("Do not refresh a project that is no longer open.");
    fireEvent.click(screen.getByTestId("domain-memory-review-approve-candidate-slow-review"));
    await act(async () => {
      rerender(<MemorySettingsPanel projectRoot="/project-b" />);
      await Promise.resolve();
    });
    await waitFor(() => expect(fetchDomainMemorySettings).toHaveBeenCalledWith("/project-b"));
    expect(await screen.findByRole("button", { name: "Disable project library" })).toBeInTheDocument();

    await act(async () => {
      releaseReview?.();
      await reviewResult;
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "Disable project library" })).toBeInTheDocument());
    expect(vi.mocked(fetchDomainMemorySettings).mock.calls.filter(([projectRoot]) => projectRoot === "/project-a")).toHaveLength(1);
  });

  it("does not show a former project's candidate-review failure or busy state", async () => {
    let rejectReview: ((error: Error) => void) | undefined;
    const reviewResult = new Promise<never>((_resolve, reject) => {
      rejectReview = reject;
    });
    const currentProject = {
      ...settings,
      project: { ...settings.project, revision: 1, library_enabled: true },
    };
    vi.mocked(fetchDomainMemorySettings).mockImplementation((projectRoot) => Promise.resolve(
      projectRoot === "/project-a" ? settings : currentProject,
    ));
    vi.mocked(listDomainMemoryLibrary).mockImplementation(async (_projectRoot, library) => ({
      library,
      entries: [],
      memory_authority: "server_owned",
    }));
    vi.mocked(listDomainMemoryCandidates).mockImplementation(async (projectRoot) => ({
      candidates: projectRoot === "/project-a" ? [{
        candidate_id: "candidate-failed-review",
        revision: 1,
        status: "needs_review",
        memory_kind: "workflow_lesson",
        compact_lesson: "A stale review failure must not reach the new project.",
        source_summary_refs: ["binding-1"],
      }] : [],
      memory_authority: "server_owned",
    }));
    vi.mocked(reviewDomainMemoryCandidate).mockReturnValueOnce(reviewResult);

    const { rerender } = render(<MemorySettingsPanel projectRoot="/project-a" />);
    await screen.findByText("A stale review failure must not reach the new project.");
    fireEvent.click(screen.getByTestId("domain-memory-review-approve-candidate-failed-review"));
    await act(async () => {
      rerender(<MemorySettingsPanel projectRoot="/project-b" />);
      await Promise.resolve();
    });

    const projectButton = await screen.findByRole("button", { name: "Disable project library" });
    expect(projectButton).toBeEnabled();
    await act(async () => {
      rejectReview?.(new Error("DOMAIN_MEMORY_REVIEW_FAILED"));
      try {
        await reviewResult;
      } catch {
        // The component owns the request failure; the test only advances it.
      }
    });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disable project library" })).toBeEnabled();
  });

  it("does not render a former project's candidates while the current queue is loading", async () => {
    let releaseCurrentCandidates: (() => void) | undefined;
    const currentCandidates = new Promise<{ candidates: []; memory_authority: "server_owned" }>((resolve) => {
      releaseCurrentCandidates = () => resolve({ candidates: [], memory_authority: "server_owned" });
    });
    const currentProject = {
      ...settings,
      project: { ...settings.project, revision: 1, library_enabled: true },
    };
    vi.mocked(fetchDomainMemorySettings).mockImplementation((projectRoot) => Promise.resolve(
      projectRoot === "/project-a" ? settings : currentProject,
    ));
    vi.mocked(listDomainMemoryLibrary).mockImplementation(async (_projectRoot, library) => ({
      library,
      entries: [],
      memory_authority: "server_owned",
    }));
    vi.mocked(listDomainMemoryCandidates).mockImplementation((projectRoot) => (
      projectRoot === "/project-a" ? Promise.resolve({
        candidates: [{
          candidate_id: "candidate-former-project",
          revision: 1,
          status: "needs_review",
          memory_kind: "workflow_lesson",
          compact_lesson: "This candidate belongs only to project A.",
          source_summary_refs: ["binding-1"],
        }],
        memory_authority: "server_owned" as const,
      }) : currentCandidates
    ));

    const { rerender } = render(<MemorySettingsPanel projectRoot="/project-a" />);
    await screen.findByText("This candidate belongs only to project A.");
    rerender(<MemorySettingsPanel projectRoot="/project-b" />);

    await screen.findByRole("button", { name: "Disable project library" });
    expect(screen.queryByText("This candidate belongs only to project A.")).not.toBeInTheDocument();
    await act(async () => {
      releaseCurrentCandidates?.();
      await currentCandidates;
    });
  });
});
