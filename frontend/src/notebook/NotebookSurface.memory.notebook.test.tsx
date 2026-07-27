import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NotebookSurface } from "./NotebookSurface";
import type { NotebookReadyView } from "./contracts";
import { canonicalOptionRevision } from "./fixtures/canonicalMocks";
import { provisionalContextSlice } from "./fixtures/provisionalContextSlice";

function ready(): NotebookReadyView {
  return {
    status: "ready",
    notebook: {
      notebook_id: "nb-memory",
      run_family_id: "family-memory",
      narrative: [],
      options: [canonicalOptionRevision()],
      contextSlice: provisionalContextSlice(),
      confirmation: null,
      execution: null,
      result: null,
      selection: null,
    },
  };
}

describe("NotebookSurface domain memory integration", () => {
  it("shows bounded hints and keeps both controls explicit", () => {
    const onChange = vi.fn();
    const view = ready();
    view.notebook.contextSlice = {
      ...view.notebook.contextSlice!,
      domain_memory_projection: {
        contract_version: "domain-memory-context-input/v1",
        retrieval_ref: "retrieval-1",
        scope_ref: "scope-1",
        outcome: "used",
        reason: "approved hint",
        entries: [{
          memory_id: "memory-1",
          revision: 1,
          content_hash: "sha256:memory",
          memory_kind: "workflow_lesson",
          domain_tags: ["econometrics"],
          compact_lesson: "Check clustered dependence.",
          recommended_effect_kind: "assumption_check_hint",
          recommended_target_refs: ["model"],
          source_summary_refs: ["summary-1"],
          match_reason: ["analysis_family=ols"],
        }],
        omissions: [],
        bounded: true,
        preference_ref: "preference-1",
      },
    };

    render(
      <NotebookSurface
        view={view}
        domainMemoryPreferences={{
          cross_project_domain_memory_use: false,
          cross_project_domain_memory_iteration: false,
        }}
        onDomainMemoryPreferencesChange={onChange}
      />,
    );

    expect(screen.getByTestId("domain-memory-controls")).toBeInTheDocument();
    expect(screen.getByTestId("domain-memory-entry-list")).toHaveTextContent("Check clustered dependence.");
    fireEvent.click(screen.getByTestId("domain-memory-use"));
    expect(onChange).toHaveBeenCalledWith({
      cross_project_domain_memory_use: true,
      cross_project_domain_memory_iteration: false,
    });
  });
});
