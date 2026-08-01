import "@testing-library/jest-dom/vitest";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemorySettingsPanel } from "./MemorySettingsPanel";
import {
  archiveMemoryLibraryEntries,
  fetchDomainMemorySettings,
  issueArchiveMemoryConfirmation,
  issueMemorySettingsConfirmation,
  listDomainMemoryLibrary,
  updateGlobalMemorySettings,
  updateProjectMemorySetting,
} from "../notebook/domainMemoryApi";

vi.mock("../notebook/domainMemoryApi", () => ({
  archiveMemoryLibraryEntries: vi.fn(),
  fetchDomainMemorySettings: vi.fn(),
  issueArchiveMemoryConfirmation: vi.fn(),
  issueMemorySettingsConfirmation: vi.fn(),
  listDomainMemoryLibrary: vi.fn(),
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
});
