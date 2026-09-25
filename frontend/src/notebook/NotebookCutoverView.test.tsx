import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NotebookCutoverView } from "./NotebookCutoverView";

const mocks = vi.hoisted(() => ({
  getNotebook: vi.fn(),
  listNotebooks: vi.fn(),
  ensureNotebookProjection: vi.fn(),
  updateNotebookFocus: vi.fn(),
  getCutoverIdentity: vi.fn(),
  compileNotebookCutover: vi.fn(),
  confirmCutover: vi.fn(),
  executeCutover: vi.fn(),
  listDomainMemoryCandidates: vi.fn(),
  reviewDomainMemoryCandidate: vi.fn(),
}));

vi.mock("./notebookApi", () => ({
  getNotebook: mocks.getNotebook,
  listNotebooks: mocks.listNotebooks,
  ensureNotebookProjection: mocks.ensureNotebookProjection,
  updateNotebookFocus: mocks.updateNotebookFocus,
}));
vi.mock("../cutoverApi", () => ({
  getCutoverIdentity: mocks.getCutoverIdentity,
  compileNotebookCutover: mocks.compileNotebookCutover,
  confirmCutover: mocks.confirmCutover,
  executeCutover: mocks.executeCutover,
  isRetryableCutoverError: (error: unknown) => {
    const candidate = error as { code?: string; status?: number };
    if (candidate?.code === "UNSUPPORTED_VERSION" || candidate?.code === "CUTOVER_CONTRACT_INVALID") {
      return false;
    }
    if (typeof candidate?.status === "number") {
      return [408, 429, 502, 503, 504].includes(candidate.status);
    }
    return error instanceof TypeError;
  },
}));
vi.mock("./domainMemoryApi", () => ({
  listDomainMemoryCandidates: mocks.listDomainMemoryCandidates,
  reviewDomainMemoryCandidate: mocks.reviewDomainMemoryCandidate,
}));

const notebook = {
  notebook_id: "nb_1",
  project_id: "local",
  run_family_id: "family_1",
  title: "Analysis Notebook",
  created_by: "user",
  active_head_run_id: "run_1",
  user_focus: {},
};
const identity = {
  schema_version: "agent-notebook-cutover-identity.v1",
  actor_ref: "principal:local:backend",
  session_ref: "session:local:backend",
  project_ref: "project:local",
};

const readyPreview = {
  schema_version: "cutover-compilation-preview.v1",
  entrypoint: "notebook",
  operation_id: "cutover-operation:1",
  compilation_record_id: "compilation:1",
  record_digest: "a".repeat(64),
  semantic_plan_hash: "b".repeat(64),
  server_execution_identity: "compiler:local:1",
  preview_fingerprint: "c".repeat(64),
  plan_diff: {
    effect: "read",
    risk_level: "low",
    data_impact: { read_refs: ["dataset:snapshot:1"], write_mode: "none" },
    evidence_required: true,
  },
  clarifications: [],
};

const binding = {
  schema_version: "server-proposal-binding.v1",
  proposal_id: "cutover-proposal:compilation:1",
  proposal_revision: 1,
  proposal_fingerprint: "d".repeat(64),
  semantic_plan_hash: "b".repeat(64),
  actor_ref: identity.actor_ref,
  session_ref: identity.session_ref,
  project_ref: identity.project_ref,
  confirmation_id: "confirmation:1",
  compilation_record_id: "compilation:1",
};

const confirmation = {
  schema_version: "server-confirmation-receipt.v1",
  confirmation_id: "confirmation:1",
  confirmation_digest: "f".repeat(64),
  compilation_record_id: "compilation:1",
  proposal_id: binding.proposal_id,
  proposal_revision: binding.proposal_revision,
  proposal_fingerprint: binding.proposal_fingerprint,
  semantic_plan_hash: binding.semantic_plan_hash,
  actor_ref: identity.actor_ref,
  session_ref: identity.session_ref,
  project_ref: identity.project_ref,
};

const executionResult = {
  schema_version: "cutover-execution-result.v1",
  operation_id: "cutover-operation:1",
  compilation_record_id: "compilation:1",
  execution_instance_hash: "e".repeat(64),
  status: "completed",
  result: { raw: "DO_NOT_RENDER_NESTED_RESULT" },
  evidence_refs: ["evidence:1", "artifact:model:1"],
  raw: "DO_NOT_RENDER_RAW_RESULT",
};

const memoryCandidate = {
  candidate_id: "candidate-1",
  revision: 2,
  status: "needs_review" as const,
  memory_kind: "workflow_lesson",
  compact_lesson: "Keep the evidence boundary visible.",
  source_summary_refs: ["binding:1"],
};

const auditedPreview = {
  ...readyPreview,
  plan_diff: {
    ...readyPreview.plan_diff,
    audit: {
      lifecycle: [
        { event_id: "compile-1", event_type: "compiled", summary: "Server compiled the plan.", occurred_at: "2026-08-25T12:00:00Z" },
      ],
      omissions: [
        { section: "context", reason: "server_budget", omitted_count: 2 },
      ],
      evidence: ["evidence:preview:1"],
    },
  },
};

function notFound(notebookId = "missing") {
  return Object.assign(new Error(`Notebook ${notebookId} was not found`), {
    status: 404,
    code: "NOTEBOOK_NOT_FOUND",
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function renderView(
  initialEntry = "/?notebook=nb_1",
  activeRunId: string | null = "run_1",
) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <NotebookCutoverView projectRoot="/tmp/project" activeRunId={activeRunId} />
    </MemoryRouter>,
  );
}

interface ScopeCommitSnapshot {
  previewVisible: boolean;
  confirmationVisible: boolean;
  resultVisible: boolean;
}

function scopeCommitSnapshot(): ScopeCommitSnapshot {
  return {
    previewVisible: document.querySelector('[data-testid="notebook-cutover-preview"]') !== null,
    confirmationVisible: document.querySelector('[data-testid="notebook-cutover-confirmation"]') !== null,
    resultVisible: document.querySelector('[data-testid="notebook-cutover-result"]') !== null,
  };
}

function ProjectScopeHarness({
  projectRoot,
  onScopeCommit,
}: {
  projectRoot: string;
  onScopeCommit: (snapshot: ScopeCommitSnapshot) => void;
}) {
  useLayoutEffect(() => {
    onScopeCommit(scopeCommitSnapshot());
  }, [onScopeCommit, projectRoot]);
  return <NotebookCutoverView projectRoot={projectRoot} activeRunId="run_1" />;
}

function NotebookScopeHarness({
  onScopeCommit,
}: {
  onScopeCommit: (snapshot: ScopeCommitSnapshot) => void;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const notebookId = searchParams.get("notebook");
  useLayoutEffect(() => {
    onScopeCommit(scopeCommitSnapshot());
  }, [notebookId, onScopeCommit]);
  return (
    <>
      <button type="button" onClick={() => setSearchParams({ notebook: "nb_2" })}>
        Switch Notebook scope
      </button>
      <NotebookCutoverView projectRoot="/tmp/project" activeRunId="run_1" />
    </>
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  mocks.getNotebook.mockResolvedValue(notebook);
  mocks.listNotebooks.mockResolvedValue([notebook]);
  mocks.ensureNotebookProjection.mockResolvedValue(notebook);
  mocks.updateNotebookFocus.mockResolvedValue({
    ...notebook,
    user_focus: { goal: "检查当前数据" },
  });
  mocks.getCutoverIdentity.mockResolvedValue(identity);
  mocks.compileNotebookCutover.mockResolvedValue({ preview: readyPreview, binding });
  mocks.confirmCutover.mockResolvedValue({
    confirmation,
  });
  mocks.executeCutover.mockResolvedValue({ result: executionResult });
  mocks.listDomainMemoryCandidates.mockResolvedValue({
    candidates: [memoryCandidate],
    memory_authority: "server_owned",
  });
  mocks.reviewDomainMemoryCandidate.mockResolvedValue({ status: "approved" });
});

describe("NotebookCutoverView", () => {
  it("shows the restored planning shell, persists Plan/Action, and keeps the cutover lifecycle typed", async () => {
    renderView();

    expect(await screen.findByTestId("notebook-planning-mode")).toBeInTheDocument();
    expect(screen.getByTestId("notebook-memory-managed")).toHaveTextContent("managed per project");
    expect(screen.getByRole("button", { name: "Manage memory" })).toBeInTheDocument();
    expect(screen.getByTestId("context-evidence-details")).toBeInTheDocument();
    expect(screen.getByTestId("domain-memory-review-queue")).toBeInTheDocument();

    const actionMode = screen.getByTestId("notebook-mode-action");
    fireEvent.click(actionMode);

    await waitFor(() => expect(mocks.updateNotebookFocus).toHaveBeenCalledWith(
      "/tmp/project",
      "nb_1",
      { interaction_mode: "action" },
    ));
    expect(actionMode).toHaveAttribute("aria-pressed", "true");

    const input = screen.getByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    await waitFor(() => expect(mocks.compileNotebookCutover).toHaveBeenCalledWith(
      "/tmp/project",
      "nb_1",
      "检查当前数据",
      identity,
    ));
    expect(mocks.confirmCutover).not.toHaveBeenCalled();
    expect(mocks.executeCutover).not.toHaveBeenCalled();
  });

  it("hydrates Plan/Action from Notebook user_focus before local state", async () => {
    mocks.getNotebook.mockResolvedValueOnce({
      ...notebook,
      user_focus: { interaction_mode: "action" },
    });

    renderView();

    expect(await screen.findByTestId("notebook-mode-action")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("notebook-mode-plan")).toHaveAttribute("aria-pressed", "false");
  });

  it("uses local Plan/Action state when Notebook user_focus has no mode", async () => {
    localStorage.setItem("workbench:notebook:interaction-mode:/tmp/project:nb_1", "action");

    renderView();

    expect(await screen.findByTestId("notebook-mode-action")).toHaveAttribute("aria-pressed", "true");
  });

  it("opens and closes server evidence details without exposing private reasoning", async () => {
    mocks.compileNotebookCutover.mockResolvedValueOnce({ preview: auditedPreview, binding });
    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "审计当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));

    const details = await screen.findByTestId("context-evidence-details");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(screen.getByTestId("context-evidence-summary"));
    expect(details).toHaveAttribute("open");
    expect(details).toHaveTextContent("Server compiled the plan.");
    expect(details).toHaveTextContent("server_budget");
    expect(details).toHaveTextContent("evidence:preview:1");
    expect(details).not.toHaveTextContent("private reasoning");
    fireEvent.click(screen.getByTestId("context-evidence-summary"));
    expect(details).not.toHaveAttribute("open");
  });

  it("reviews memory candidates explicitly with the typed revision and actor binding", async () => {
    renderView();

    fireEvent.click(await screen.findByTestId("domain-memory-review-approve-candidate-1"));

    await waitFor(() => expect(mocks.reviewDomainMemoryCandidate).toHaveBeenCalledWith(
      "/tmp/project",
      "candidate-1",
      expect.objectContaining({
        decision: "approved",
        expected_revision: 2,
        actor_id: identity.actor_ref,
      }),
    ));
    expect(mocks.confirmCutover).not.toHaveBeenCalled();
    expect(mocks.executeCutover).not.toHaveBeenCalled();
  });

  it("compiles from the Notebook keyboard shortcut without changing the draft", async () => {
    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "用快捷键检查当前数据" } });
    fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });

    await waitFor(() => expect(mocks.compileNotebookCutover).toHaveBeenCalledWith(
      "/tmp/project",
      "nb_1",
      "用快捷键检查当前数据",
      identity,
    ));
    expect(input).toHaveValue("用快捷键检查当前数据");
  });

  it("uses the mature Notebook shell and the shared compiler confirmation path", async () => {
    renderView();

    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    const surface = screen.getByTestId("notebook-cutover-view");
    expect(surface).toHaveClass("nb-surface", "nb-cutover-surface");
    expect(screen.getByTestId("notebook-header-identity")).toHaveTextContent("nb_1 · family_1");
    expect(screen.getByTestId("notebook-compiler-status")).toHaveTextContent("Compiler ready");

    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));

    await waitFor(() => {
      expect(mocks.compileNotebookCutover).toHaveBeenCalledWith(
        "/tmp/project",
        "nb_1",
        "检查当前数据",
        identity,
      );
    });
    expect(mocks.updateNotebookFocus).toHaveBeenCalledWith("/tmp/project", "nb_1", {
      goal: "检查当前数据",
      interaction_mode: "plan",
    });
    expect(await screen.findByTestId("notebook-activity-user")).toHaveTextContent("检查当前数据");

    const preview = screen.getByTestId("notebook-cutover-preview");
    expect(within(preview).getByText("Effect")).toBeInTheDocument();
    expect(within(preview).getByText("Risk level")).toBeInTheDocument();
    expect(within(preview).getByText("Data impact")).toBeInTheDocument();
    expect(within(preview).getByText("dataset:snapshot:1")).toBeInTheDocument();
    expect(preview.querySelector("pre")).toBeNull();
    expect(preview).not.toHaveTextContent('\"effect\": \"read\"');
    expect(screen.getByText("Nothing runs until you confirm.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirm and execute notebook plan" }));
    const result = await screen.findByTestId("notebook-cutover-result");
    expect(result).toHaveTextContent("completed");
    expect(result).toHaveTextContent("cutover-operation:1");
    expect(result).toHaveTextContent("Execution instance hash");
    expect(result).toHaveTextContent("e".repeat(64));
    expect(result).toHaveTextContent("evidence:1");
    expect(result).toHaveTextContent("artifact:model:1");
    expect(result).not.toHaveTextContent("DO_NOT_RENDER_RAW_RESULT");
    expect(result).not.toHaveTextContent("DO_NOT_RENDER_NESTED_RESULT");
    const progress = within(screen.getByTestId("notebook-cutover-progress"));
    const progressStages = within(progress.getByRole("list")).getAllByRole("listitem");
    expect(progressStages).toHaveLength(4);
    expect(progressStages.map((stage) => stage.textContent)).toEqual([
      "Notebook scope and server identity",
      "Server compilation and structured preview",
      "Explicit server confirmation",
      "Execution and formal evidence references",
    ]);
    expect(progress.getAllByText("Server compilation and structured preview")).toHaveLength(1);
    expect(mocks.confirmCutover).toHaveBeenCalledWith(binding, identity);
    expect(mocks.executeCutover).toHaveBeenCalledWith(
      binding,
      identity,
      confirmation,
      { expected_operation_id: "cutover-operation:1" },
    );
  });

  it("invalidates the compiled preview, binding, and result as soon as the request changes", async () => {
    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    await screen.findByTestId("notebook-cutover-preview");
    fireEvent.click(screen.getByRole("button", { name: "Confirm and execute notebook plan" }));
    await screen.findByTestId("notebook-cutover-result");
    await waitFor(() => {
      expect(screen.getByTestId("notebook-cutover-view")).toHaveAttribute("aria-busy", "false");
    });

    fireEvent.change(input, { target: { value: "改为检查另一份数据" } });

    expect(screen.queryByTestId("notebook-cutover-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("notebook-cutover-confirmation")).not.toBeInTheDocument();
    expect(screen.queryByTestId("notebook-cutover-result")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm and execute notebook plan" })).not.toBeInTheDocument();
  });

  it("clears compiled state and refetches identity when projectRoot changes", async () => {
    const scopeCommits: ScopeCommitSnapshot[] = [];
    const recordScopeCommit = (snapshot: ScopeCommitSnapshot) => scopeCommits.push(snapshot);
    const rendered = render(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <ProjectScopeHarness projectRoot="/tmp/project-a" onScopeCommit={recordScopeCommit} />
      </MemoryRouter>,
    );
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    await screen.findByTestId("notebook-cutover-preview");
    fireEvent.click(screen.getByRole("button", { name: "Confirm and execute notebook plan" }));
    await screen.findByTestId("notebook-cutover-result");

    rendered.rerender(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <ProjectScopeHarness projectRoot="/tmp/project-b" onScopeCommit={recordScopeCommit} />
      </MemoryRouter>,
    );

    expect(scopeCommits[scopeCommits.length - 1]).toEqual({
      previewVisible: false,
      confirmationVisible: false,
      resultVisible: false,
    });
    expect(screen.queryByTestId("notebook-cutover-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("notebook-cutover-confirmation")).not.toBeInTheDocument();
    expect(screen.queryByTestId("notebook-cutover-result")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mocks.getCutoverIdentity).toHaveBeenCalledWith("/tmp/project-b");
      expect(mocks.getNotebook).toHaveBeenCalledWith("/tmp/project-b", "nb_1");
    });
  });

  it("clears compiled state and refetches identity when the Notebook scope changes", async () => {
    const scopeCommits: ScopeCommitSnapshot[] = [];
    const recordScopeCommit = (snapshot: ScopeCommitSnapshot) => scopeCommits.push(snapshot);
    const secondNotebook = {
      ...notebook,
      notebook_id: "nb_2",
      run_family_id: "family_2",
      title: "Forecast Notebook",
    };
    mocks.getNotebook.mockImplementation((_projectRoot: string, notebookId: string) => (
      Promise.resolve(notebookId === "nb_2" ? secondNotebook : notebook)
    ));
    render(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <NotebookScopeHarness onScopeCommit={recordScopeCommit} />
      </MemoryRouter>,
    );
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    await screen.findByTestId("notebook-cutover-preview");
    await waitFor(() => {
      expect(screen.getByRole("button", {
        name: "Confirm and execute notebook plan",
      })).toBeEnabled();
    });

    fireEvent.click(screen.getByRole("button", { name: "Switch Notebook scope" }));

    expect(scopeCommits[scopeCommits.length - 1]).toEqual({
      previewVisible: false,
      confirmationVisible: false,
      resultVisible: false,
    });
    expect(screen.queryByTestId("notebook-cutover-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("notebook-cutover-confirmation")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId("notebook-header-identity")).toHaveTextContent("nb_2 · family_2");
      expect(mocks.getCutoverIdentity).toHaveBeenCalledTimes(2);
    });
  });

  it("drops a compilation response that resolves after its scope key is stale", async () => {
    const compileGate = deferred<{ preview: typeof readyPreview; binding: typeof binding }>();
    mocks.compileNotebookCutover.mockReturnValueOnce(compileGate.promise);
    const scopeCommits: ScopeCommitSnapshot[] = [];
    const recordScopeCommit = (snapshot: ScopeCommitSnapshot) => scopeCommits.push(snapshot);
    const rendered = render(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <ProjectScopeHarness projectRoot="/tmp/project-a" onScopeCommit={recordScopeCommit} />
      </MemoryRouter>,
    );
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    await waitFor(() => expect(mocks.compileNotebookCutover).toHaveBeenCalledOnce());

    rendered.rerender(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <ProjectScopeHarness projectRoot="/tmp/project-b" onScopeCommit={recordScopeCommit} />
      </MemoryRouter>,
    );
    await act(async () => {
      compileGate.resolve({ preview: readyPreview, binding });
      await compileGate.promise;
    });

    expect(screen.queryByTestId("notebook-cutover-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("notebook-cutover-confirmation")).not.toBeInTheDocument();
  });

  it("rejects an old A response after an A to B to A scope cycle", async () => {
    const oldCompileGate = deferred<{ preview: typeof readyPreview; binding: typeof binding }>();
    mocks.compileNotebookCutover.mockReturnValueOnce(oldCompileGate.promise);
    const rendered = render(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <ProjectScopeHarness projectRoot="/tmp/project-a" onScopeCommit={() => undefined} />
      </MemoryRouter>,
    );
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "旧 A 请求" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    await waitFor(() => expect(mocks.compileNotebookCutover).toHaveBeenCalledOnce());

    rendered.rerender(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <ProjectScopeHarness projectRoot="/tmp/project-b" onScopeCommit={() => undefined} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(mocks.getCutoverIdentity).toHaveBeenCalledWith("/tmp/project-b"));
    rendered.rerender(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <ProjectScopeHarness projectRoot="/tmp/project-a" onScopeCommit={() => undefined} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(mocks.getCutoverIdentity).toHaveBeenCalledTimes(3));

    await act(async () => {
      oldCompileGate.resolve({ preview: readyPreview, binding });
      await oldCompileGate.promise;
    });

    expect(screen.queryByTestId("notebook-cutover-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("notebook-cutover-confirmation")).not.toBeInTheDocument();
    expect(screen.queryByText("旧 A 请求")).not.toBeInTheDocument();
  });

  it("stops a stale Notebook recovery chain before it lists or ensures the old scope", async () => {
    const oldNotebookGate = deferred<typeof notebook>();
    mocks.getNotebook.mockImplementation((projectRoot: string) => (
      projectRoot === "/tmp/project-a" ? oldNotebookGate.promise : Promise.resolve(notebook)
    ));
    const scopeCommits: ScopeCommitSnapshot[] = [];
    const recordScopeCommit = (snapshot: ScopeCommitSnapshot) => scopeCommits.push(snapshot);
    const rendered = render(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <ProjectScopeHarness projectRoot="/tmp/project-a" onScopeCommit={recordScopeCommit} />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(mocks.getNotebook).toHaveBeenCalledWith("/tmp/project-a", "nb_1");
    });

    rendered.rerender(
      <MemoryRouter initialEntries={["/?notebook=nb_1"]}>
        <ProjectScopeHarness projectRoot="/tmp/project-b" onScopeCommit={recordScopeCommit} />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(mocks.getNotebook).toHaveBeenCalledWith("/tmp/project-b", "nb_1");
    });
    await act(async () => {
      oldNotebookGate.reject(notFound("nb_1"));
      await oldNotebookGate.promise.catch(() => undefined);
    });

    expect(mocks.listNotebooks).not.toHaveBeenCalledWith("/tmp/project-a");
    expect(mocks.ensureNotebookProjection).not.toHaveBeenCalledWith(
      "/tmp/project-a",
      expect.anything(),
    );
  });

  it("keeps the task draft editable when server identity fails and preserves it through Retry", async () => {
    mocks.getCutoverIdentity
      .mockRejectedValueOnce(Object.assign(new Error("Identity binding unavailable"), {
        code: "AGENT_NOTEBOOK_IDENTITY_NOT_BOUND",
      }))
      .mockResolvedValueOnce(identity);

    renderView();

    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    expect(input).toBeEnabled();
    fireEvent.change(input, { target: { value: "保留这份草稿" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Identity binding unavailable");
    fireEvent.click(screen.getByRole("button", { name: /Retry/i }));

    await waitFor(() => {
      expect(screen.getByTestId("notebook-compiler-status")).toHaveTextContent("Compiler ready");
    });
    expect(input).toHaveValue("保留这份草稿");
    expect(screen.getByRole("button", { name: "Compile notebook plan" })).toBeEnabled();
  });

  it("collects clarification fields and recompiles with normalized fields before confirmation", async () => {
    const clarificationPreview = {
      ...readyPreview,
      operation_id: null,
      compilation_record_id: null,
      record_digest: null,
      semantic_plan_hash: null,
      server_execution_identity: null,
      preview_fingerprint: null,
      plan_diff: { status: "clarification_required" },
      clarifications: [
        {
          code: "missing_required_information",
          field: "capability_id",
          message: "Choose a registered capability.",
          allowed_values: [],
        },
        {
          code: "missing_required_information",
          field: "target_ref",
          message: "Identify the analysis target.",
          allowed_values: [],
        },
        {
          code: "missing_required_information",
          field: "requested_effect",
          message: "Choose the requested effect.",
          allowed_values: ["read", "model_fit"],
        },
        {
          code: "missing_required_information",
          field: "sensitivity",
          message: "Classify the data sensitivity.",
          allowed_values: ["public", "internal", "sensitive"],
        },
      ],
    };
    mocks.compileNotebookCutover
      .mockResolvedValueOnce({ preview: clarificationPreview })
      .mockResolvedValueOnce({ preview: readyPreview, binding });

    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));

    const clarification = await screen.findByTestId("notebook-clarifications");
    expect(clarification).toHaveTextContent("Choose a registered capability.");
    expect(screen.queryByRole("button", { name: "Confirm and execute notebook plan" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Capability"), {
      target: { value: "fixture.contracts.capability" },
    });
    fireEvent.change(screen.getByLabelText("Target"), {
      target: { value: "dataset:fixture:1" },
    });
    fireEvent.change(screen.getByLabelText("Requested effect"), {
      target: { value: "read" },
    });
    fireEvent.change(screen.getByLabelText("Sensitivity"), {
      target: { value: "public" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Recompile with answers" }));

    await waitFor(() => {
      expect(mocks.compileNotebookCutover).toHaveBeenNthCalledWith(
        2,
        "/tmp/project",
        "nb_1",
        "检查当前数据",
        identity,
        {
          capability_id: "fixture.contracts.capability",
          target_ref: "dataset:fixture:1",
          requested_effect: "read",
          sensitivity: "public",
        },
      );
    });
    expect(await screen.findByText("Nothing runs until you confirm.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and execute notebook plan" })).toBeEnabled();
  });

  it("shows live compile and execute stages while requests are in flight", async () => {
    const compileGate = deferred<{ preview: typeof readyPreview; binding: typeof binding }>();
    const executeGate = deferred<{ result: typeof executionResult }>();
    mocks.compileNotebookCutover.mockReturnValueOnce(compileGate.promise);
    mocks.executeCutover.mockReturnValueOnce(executeGate.promise);

    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    expect(await screen.findByTestId("notebook-cutover-progress")).toHaveTextContent(
      "Compiling server plan",
    );

    await act(async () => {
      compileGate.resolve({ preview: readyPreview, binding });
      await compileGate.promise;
    });
    fireEvent.click(await screen.findByRole("button", {
      name: "Confirm and execute notebook plan",
    }));
    await waitFor(() => expect(mocks.executeCutover).toHaveBeenCalledOnce());
    expect(screen.getByTestId("notebook-cutover-progress")).toHaveTextContent(
      "Executing confirmed plan",
    );

    await act(async () => {
      executeGate.resolve({ result: executionResult });
      await executeGate.promise;
    });
    expect(await screen.findByTestId("notebook-cutover-result")).toHaveTextContent("completed");
  });

  it("retries only execution after confirmation succeeds and execution fails", async () => {
    mocks.executeCutover
      .mockRejectedValueOnce(new TypeError("Executor temporarily unavailable"))
      .mockResolvedValueOnce({ result: executionResult });

    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Confirm and execute notebook plan",
    }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Executor temporarily unavailable");
    expect(mocks.confirmCutover).toHaveBeenCalledOnce();
    expect(mocks.executeCutover).toHaveBeenCalledOnce();
    const retryExecution = await screen.findByRole("button", { name: "Retry execution" });
    await waitFor(() => expect(retryExecution).toBeEnabled());
    fireEvent.click(retryExecution);

    expect(await screen.findByTestId("notebook-cutover-result")).toHaveTextContent("completed");
    expect(mocks.confirmCutover).toHaveBeenCalledOnce();
    expect(mocks.executeCutover).toHaveBeenCalledTimes(2);
    expect(mocks.executeCutover).toHaveBeenNthCalledWith(
      2,
      binding,
      identity,
      confirmation,
      { expected_operation_id: "cutover-operation:1" },
    );
  });

  it("fails closed when the confirmation response is uncertain", async () => {
    mocks.confirmCutover.mockRejectedValueOnce(Object.assign(
      new Error("Confirmation response was lost"),
      { status: 503 },
    ));

    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Confirm and execute notebook plan",
    }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/confirmation response was lost/i);
    expect(screen.queryByRole("button", {
      name: "Confirm and execute notebook plan",
    })).not.toBeInTheDocument();
    expect(screen.getByText(/confirmation status is uncertain.*compile a new plan/i)).toBeInTheDocument();
    expect(mocks.confirmCutover).toHaveBeenCalledOnce();
    expect(mocks.executeCutover).not.toHaveBeenCalled();
  });

  it("sends only one confirmation for a synchronous double click", async () => {
    const confirmGate = deferred<{ confirmation: typeof confirmation }>();
    mocks.confirmCutover.mockReturnValueOnce(confirmGate.promise);

    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    const confirmButton = await screen.findByRole("button", {
      name: "Confirm and execute notebook plan",
    });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    expect(mocks.confirmCutover).toHaveBeenCalledOnce();
    confirmGate.resolve({ confirmation });
    await waitFor(() => expect(screen.getByTestId("notebook-cutover-result")).toHaveTextContent("completed"));
    expect(mocks.executeCutover).toHaveBeenCalledOnce();
  });

  it("does not offer execution retry for an explicit terminal state error", async () => {
    mocks.executeCutover.mockRejectedValueOnce(Object.assign(
      new Error("The confirmed operation is already terminal"),
      { status: 409, code: "OPERATION_EXECUTION_STATE_INVALID" },
    ));

    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Confirm and execute notebook plan",
    }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already terminal");
    expect(screen.queryByRole("button", { name: "Retry execution" })).not.toBeInTheDocument();
    expect(screen.getByText(/compile a new plan/i)).toBeInTheDocument();
  });

  it("offers at most one execution retry before requiring a new compilation", async () => {
    mocks.executeCutover
      .mockRejectedValueOnce(new TypeError("Connection interrupted"))
      .mockRejectedValueOnce(new TypeError("Connection interrupted again"));

    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    fireEvent.click(await screen.findByRole("button", {
      name: "Confirm and execute notebook plan",
    }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry execution" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("interrupted again");
    expect(screen.queryByRole("button", { name: "Retry execution" })).not.toBeInTheDocument();
    expect(mocks.confirmCutover).toHaveBeenCalledOnce();
    expect(mocks.executeCutover).toHaveBeenCalledTimes(2);
  });

  it("clears failed compilation activity and error as soon as the draft changes", async () => {
    mocks.compileNotebookCutover.mockRejectedValueOnce(new Error("Compiler unavailable"));
    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "旧请求" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Compiler unavailable");
    expect(screen.getByTestId("notebook-activity-user")).toHaveTextContent("旧请求");

    fireEvent.change(input, { target: { value: "新请求" } });

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("notebook-activity-user")).not.toBeInTheDocument();
  });

  it("keeps the previous task visible when a new request replaces a compiled task", async () => {
    renderView();
    const input = await screen.findByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "第一轮：检查当前数据" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile notebook plan" }));
    await screen.findByTestId("notebook-cutover-preview");

    fireEvent.change(input, { target: { value: "第二轮：比较两个模型" } });

    const history = screen.getByTestId("notebook-task-history");
    expect(history).toHaveTextContent("第一轮：检查当前数据");
    expect(history).toHaveTextContent("Plan preview ready");
    expect(input).toHaveValue("第二轮：比较两个模型");
  });

  it("recovers a requested 404 to the only persisted Notebook", async () => {
    mocks.getNotebook.mockImplementation((_projectRoot: string, notebookId: string) => (
      notebookId === "missing" ? Promise.reject(notFound()) : Promise.resolve(notebook)
    ));

    renderView("/?notebook=missing");

    await waitFor(() => {
      expect(screen.getByTestId("notebook-header-identity")).toHaveTextContent("nb_1 · family_1");
    });
    expect(mocks.listNotebooks).toHaveBeenCalledWith("/tmp/project");
    expect(screen.queryByTestId("notebook-chooser")).not.toBeInTheDocument();
  });

  it("does not treat an untyped route 404 as a missing Notebook fallback", async () => {
    mocks.getNotebook.mockRejectedValue(Object.assign(new Error("Cutover route missing"), {
      status: 404,
    }));

    renderView("/?notebook=missing");

    expect(await screen.findByRole("alert")).toHaveTextContent("Cutover route missing");
    expect(mocks.listNotebooks).not.toHaveBeenCalled();
    expect(mocks.ensureNotebookProjection).not.toHaveBeenCalled();
  });

  it("shows an explicit chooser instead of guessing when a requested 404 has multiple Notebooks", async () => {
    const secondNotebook = {
      ...notebook,
      notebook_id: "nb_2",
      run_family_id: "family_2",
      title: "Forecast Notebook",
      active_head_run_id: "run_2",
    };
    mocks.getNotebook.mockImplementation((_projectRoot: string, notebookId: string) => {
      if (notebookId === "missing") return Promise.reject(notFound());
      return Promise.resolve(notebookId === "nb_2" ? secondNotebook : notebook);
    });
    mocks.listNotebooks.mockResolvedValue([notebook, secondNotebook]);

    renderView("/?notebook=missing");

    const chooser = await screen.findByTestId("notebook-chooser");
    expect(chooser).toHaveTextContent("The requested Notebook was not found");
    expect(screen.getByTestId("notebook-header-identity")).toHaveTextContent("No Notebook selected");
    expect(screen.getByRole("button", { name: "Compile notebook plan" })).toBeDisabled();
    fireEvent.click(within(chooser).getByRole("button", { name: "Use Forecast Notebook" }));
    await waitFor(() => {
      expect(screen.getByTestId("notebook-header-identity")).toHaveTextContent("nb_2 · family_2");
    });
  });

  it("ensures a projection when a requested 404 has no persisted Notebook and an active run", async () => {
    const projected = {
      ...notebook,
      notebook_id: "nb_projected",
      run_family_id: "family_projected",
    };
    mocks.getNotebook.mockImplementation((_projectRoot: string, notebookId: string) => (
      notebookId === "missing" ? Promise.reject(notFound()) : Promise.resolve(projected)
    ));
    mocks.listNotebooks.mockResolvedValue([]);
    mocks.ensureNotebookProjection.mockResolvedValue(projected);

    renderView("/?notebook=missing", "run_1");

    await waitFor(() => {
      expect(mocks.ensureNotebookProjection).toHaveBeenCalledWith("/tmp/project", {
        from_run_id: "run_1",
        created_by: "user",
        title: "Analysis Notebook",
      });
    });
    expect(screen.getByTestId("notebook-header-identity")).toHaveTextContent(
      "nb_projected · family_projected",
    );
  });

  it("shows a recoverable not-found state when no Notebook or active run exists", async () => {
    mocks.getNotebook.mockRejectedValue(notFound());
    mocks.listNotebooks.mockResolvedValue([]);

    renderView("/?notebook=missing", null);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No Notebook is available");
    const input = screen.getByRole("textbox", { name: "Notebook request" });
    fireEvent.change(input, { target: { value: "草稿仍然可编辑" } });
    expect(input).toHaveValue("草稿仍然可编辑");
    expect(screen.getByRole("button", { name: /Retry/i })).toBeInTheDocument();
  });
});
