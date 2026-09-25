import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentCutoverPanel } from "./AgentCutoverPanel";

const identity = {
  schema_version: "agent-notebook-cutover-identity.v1",
  actor_ref: "principal:local:backend",
  session_ref: "session:local:backend",
  project_ref: "project:local:test",
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
  confirmation_id: "confirmation:cutover:1",
  compilation_record_id: "compilation:1",
};

const preview = {
  schema_version: "cutover-compilation-preview.v1",
  entrypoint: "agent",
  operation_id: "cutover-operation:1",
  compilation_record_id: "compilation:1",
  record_digest: "a".repeat(64),
  semantic_plan_hash: "b".repeat(64),
  server_execution_identity: "compile:local:1",
  preview_fingerprint: "c".repeat(64),
  plan_diff: {
    effect: "read",
    target_ref: "run:current",
    evidence_required: ["summary", "lineage"],
  },
  clarifications: [],
};

const confirmation = {
  schema_version: "server-confirmation-receipt.v1",
  confirmation_id: "confirmation:cutover:1",
  confirmation_digest: "e".repeat(64),
  compilation_record_id: "compilation:1",
  proposal_id: binding.proposal_id,
  proposal_revision: binding.proposal_revision,
  proposal_fingerprint: binding.proposal_fingerprint,
  semantic_plan_hash: binding.semantic_plan_hash,
  actor_ref: identity.actor_ref,
  session_ref: identity.session_ref,
  project_ref: identity.project_ref,
};

const result = {
  schema_version: "cutover-execution-result.v1",
  operation_id: "cutover-operation:1",
  compilation_record_id: "compilation:1",
  execution_instance_hash: "f".repeat(64),
  status: "completed",
  result: { evidence_ref: "evidence:agent:1" },
  evidence_refs: ["evidence:agent:1", "evidence:lineage:1"],
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderPanel(projectRoot = "/tmp/project", runId = "run-1") {
  return render(
    <MemoryRouter>
      <AgentCutoverPanel projectRoot={projectRoot} runId={runId} />
    </MemoryRouter>,
  );
}

async function compileRequest(text = "检查当前数据") {
  const input = await screen.findByRole("textbox", { name: "Agent request" });
  fireEvent.change(input, { target: { value: text } });
  const compileButton = screen.getByRole("button", { name: "Compile plan" });
  await waitFor(() => expect(compileButton).toBeEnabled());
  fireEvent.click(compileButton);
  return screen.findByTestId("agent-cutover-preview");
}

afterEach(() => vi.restoreAllMocks());

describe("AgentCutoverPanel", () => {
  it("renders a fresh scope as resolving before the identity effect starts", () => {
    const html = renderToString(
      <AgentCutoverPanel projectRoot="/tmp/project" runId="run-first-paint" />,
    );

    expect(html).toContain("Resolving server identity · run-first-paint");
    expect(html).not.toContain("Identity unavailable");
  });

  it("restores the mature terminal shell and renders a structured server plan without raw JSON", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }));

    renderPanel();
    const plan = await compileRequest();

    expect(screen.getByTestId("agent-cutover-panel")).toHaveClass("wb-agent-panel");
    expect(screen.getByRole("log", { name: /Agent history/i })).toHaveClass("wb-agent-terminal");
    expect(screen.getByTestId("agent-execution-trace")).toHaveClass("wb-agent-execution-trace");
    expect(screen.getByTestId("agent-action-rail")).toHaveClass("wb-agent-action-rail");
    expect(screen.getByTestId("agent-composer")).toHaveClass("wb-agent-terminal-composer");
    expect(plan).toHaveTextContent("Effect");
    expect(plan).toHaveTextContent("read");
    expect(plan).toHaveTextContent("Evidence required");
    expect(within(plan).queryByText(/\{\s*"effect"/)).not.toBeInTheDocument();
    expect(plan.querySelector("pre")).toBeNull();
  });

  it("keeps the draft editable when identity loading fails and retries identity explicitly", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ detail: "identity unavailable" }, 503))
      .mockResolvedValueOnce(json(identity));

    renderPanel();

    const input = screen.getByRole("textbox", { name: "Agent request" });
    fireEvent.change(input, { target: { value: "保留这个草稿" } });
    expect(input).toHaveValue("保留这个草稿");
    expect(await screen.findByRole("alert")).toHaveTextContent(/identity unavailable/i);

    fireEvent.click(screen.getByRole("button", { name: "Retry server identity" }));
    await waitFor(() => expect(screen.getByTestId("agent-scope-identity")).toHaveTextContent(identity.project_ref));
    expect(input).toHaveValue("保留这个草稿");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("revokes a compiled preview immediately when the natural-language request changes", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }));

    renderPanel();
    await compileRequest();
    expect(screen.getByRole("button", { name: "Confirm and execute" })).toBeInTheDocument();

    fireEvent.change(screen.getByRole("textbox", { name: "Agent request" }), {
      target: { value: "改成另一项分析" },
    });

    expect(screen.queryByTestId("agent-cutover-preview")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm and execute" })).not.toBeInTheDocument();
  });

  it("keeps the previous task visible when a new request replaces a compiled task", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }));

    renderPanel();
    await compileRequest("第一轮：检查当前数据");

    fireEvent.change(screen.getByRole("textbox", { name: "Agent request" }), {
      target: { value: "第二轮：比较两个模型" },
    });

    const history = screen.getByTestId("agent-task-history");
    expect(history).toHaveTextContent("第一轮：检查当前数据");
    expect(history).toHaveTextContent("Plan preview ready");
    expect(screen.getByRole("textbox", { name: "Agent request" })).toHaveValue("第二轮：比较两个模型");
  });

  it("collects clarification fields as a form and recompiles with normalized_fields", async () => {
    const clarificationPreview = {
      ...preview,
      operation_id: null,
      compilation_record_id: null,
      record_digest: null,
      semantic_plan_hash: null,
      server_execution_identity: null,
      preview_fingerprint: null,
      clarifications: [
        {
          code: "missing_required_information",
          field: "capability_id",
          message: "Choose the statistical capability.",
          allowed_values: ["model.ols", "model.logit"],
        },
        {
          code: "missing_required_information",
          field: "target_ref",
          message: "Choose the target run.",
          allowed_values: [],
        },
      ],
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview: clarificationPreview }))
      .mockResolvedValueOnce(json({ preview, binding }));

    renderPanel();
    await compileRequest("拟合一个模型");

    fireEvent.change(screen.getByLabelText("Capability"), { target: { value: "model.logit" } });
    fireEvent.change(screen.getByLabelText("Target"), { target: { value: "run:current" } });
    fireEvent.click(screen.getByRole("button", { name: "Recompile plan" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm and execute" })).toBeInTheDocument());
    const compileCall = fetchMock.mock.calls[2];
    expect(JSON.parse(String((compileCall[1] as RequestInit).body))).toMatchObject({
      text: "拟合一个模型",
      entrypoint: "agent",
      normalized_fields: {
        capability_id: "model.logit",
        target_ref: "run:current",
      },
    });
  });

  it("never offers confirmation while a server response still requires clarification", async () => {
    const clarificationPreview = {
      ...preview,
      operation_id: null,
      compilation_record_id: null,
      record_digest: null,
      semantic_plan_hash: null,
      server_execution_identity: null,
      preview_fingerprint: null,
      clarifications: [
        {
          code: "missing_required_information",
          field: "target_ref",
          message: "Choose the target run.",
          allowed_values: [],
        },
      ],
    };
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview: clarificationPreview }));

    renderPanel();
    await compileRequest("检查当前运行");

    expect(screen.getByLabelText("Plan clarifications")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm and execute" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("agent-cutover-confirmation")).not.toBeInTheDocument();
  });

  it("locks clarification answers while their normalized_fields recompile is in flight", async () => {
    const clarificationPreview = {
      ...preview,
      operation_id: null,
      compilation_record_id: null,
      record_digest: null,
      semantic_plan_hash: null,
      server_execution_identity: null,
      preview_fingerprint: null,
      clarifications: [
        {
          code: "missing_required_information",
          field: "capability_id",
          message: "Choose the statistical capability.",
          allowed_values: ["model.ols", "model.logit"],
        },
        {
          code: "missing_required_information",
          field: "target_ref",
          message: "Choose the target run.",
          allowed_values: [],
        },
      ],
    };
    let resolveRecompile!: (response: Response) => void;
    const pendingRecompile = new Promise<Response>((resolve) => {
      resolveRecompile = resolve;
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview: clarificationPreview }))
      .mockImplementationOnce(() => pendingRecompile);

    renderPanel();
    await compileRequest("拟合一个模型");
    const capability = screen.getByLabelText("Capability");
    const target = screen.getByLabelText("Target");
    fireEvent.change(capability, { target: { value: "model.logit" } });
    fireEvent.change(target, { target: { value: "run:current" } });
    fireEvent.click(screen.getByRole("button", { name: "Recompile plan" }));

    await waitFor(() => {
      expect(capability).toBeDisabled();
      expect(target).toBeDisabled();
      expect(screen.getByRole("button", { name: "Recompiling…" })).toBeDisabled();
    });
    const body = JSON.parse(String((fetchMock.mock.calls[2][1] as RequestInit).body));
    expect(body.normalized_fields).toEqual({
      capability_id: "model.logit",
      target_ref: "run:current",
    });

    resolveRecompile(json({ preview, binding }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm and execute" })).toBeInTheDocument());
  });

  it("retries execute after confirmation without issuing a second confirmation", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }))
      .mockResolvedValueOnce(json({ confirmation }))
      .mockResolvedValueOnce(json({ detail: "execution interrupted" }, 503))
      .mockResolvedValueOnce(json({ result }));

    renderPanel();
    await compileRequest();
    fireEvent.click(screen.getByRole("button", { name: "Confirm and execute" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/execution interrupted/i);
    expect(screen.getByTestId("agent-cutover-confirmation")).toHaveTextContent(confirmation.confirmation_id);
    fireEvent.click(screen.getByRole("button", { name: "Retry execution" }));

    await waitFor(() => expect(screen.getByTestId("agent-cutover-result")).toHaveTextContent("completed"));
    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(urls.filter((url) => url.endsWith("/confirm"))).toHaveLength(1);
    expect(urls.filter((url) => url.endsWith("/execute"))).toHaveLength(2);
  });

  it("fails closed when the confirmation response is uncertain", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }))
      .mockResolvedValueOnce(json({ detail: "confirmation response lost" }, 503));

    renderPanel();
    await compileRequest();
    fireEvent.click(screen.getByRole("button", { name: "Confirm and execute" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/confirmation response lost/i);
    expect(screen.queryByRole("button", { name: "Confirm and execute" })).not.toBeInTheDocument();
    expect(screen.getByText(/confirmation status is uncertain.*compile a new plan/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/confirm"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/execute"))).toHaveLength(0);
  });

  it("sends only one confirmation for a synchronous double click", async () => {
    let resolveConfirmation!: (response: Response) => void;
    const pendingConfirmation = new Promise<Response>((resolve) => {
      resolveConfirmation = resolve;
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }))
      .mockImplementationOnce(() => pendingConfirmation)
      .mockResolvedValueOnce(json({ result }));

    renderPanel();
    await compileRequest();
    const confirmButton = screen.getByRole("button", { name: "Confirm and execute" });
    fireEvent.click(confirmButton);
    fireEvent.click(confirmButton);

    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/confirm"))).toHaveLength(1);
    resolveConfirmation(json({ confirmation }));
    await waitFor(() => expect(screen.getByTestId("agent-cutover-result")).toHaveTextContent("completed"));
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/execute"))).toHaveLength(1);
  });

  it("keeps the active request immutable while confirmed execution is in flight", async () => {
    let resolveExecute!: (response: Response) => void;
    const pendingExecute = new Promise<Response>((resolve) => {
      resolveExecute = resolve;
    });
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }))
      .mockResolvedValueOnce(json({ confirmation }))
      .mockImplementationOnce(() => pendingExecute);

    renderPanel();
    await compileRequest("保留正在执行的任务");
    fireEvent.click(screen.getByRole("button", { name: "Confirm and execute" }));

    const input = screen.getByRole("textbox", { name: "Agent request" });
    await waitFor(() => expect(input).toBeDisabled());
    fireEvent.change(input, { target: { value: "不应覆盖执行中的任务" } });
    expect(input).toHaveValue("保留正在执行的任务");
    expect(screen.getByTestId("agent-cutover-confirmation")).toHaveTextContent(
      confirmation.confirmation_id,
    );

    resolveExecute(json({ result }));
    await waitFor(() => expect(screen.getByTestId("agent-cutover-result")).toHaveTextContent("completed"));
  });

  it("does not offer execution retry for a terminal server state", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }))
      .mockResolvedValueOnce(json({ confirmation }))
      .mockResolvedValueOnce(json({
        error: {
          code: "OPERATION_EXECUTION_STATE_INVALID",
          message: "The confirmed operation is already terminal",
        },
      }, 409));

    renderPanel();
    await compileRequest();
    fireEvent.click(screen.getByRole("button", { name: "Confirm and execute" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already terminal");
    expect(screen.queryByRole("button", { name: "Retry execution" })).not.toBeInTheDocument();
    expect(screen.getByText(/compile a new plan/i)).toBeInTheDocument();
  });

  it("offers at most one transient execution retry", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }))
      .mockResolvedValueOnce(json({ confirmation }))
      .mockResolvedValueOnce(json({ detail: "execution interrupted" }, 503))
      .mockResolvedValueOnce(json({ detail: "execution interrupted again" }, 503));

    renderPanel();
    await compileRequest();
    fireEvent.click(screen.getByRole("button", { name: "Confirm and execute" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry execution" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("interrupted again");
    expect(screen.queryByRole("button", { name: "Retry execution" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/confirm"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/execute"))).toHaveLength(2);
  });

  it("shows the formal operation, execution identity, and evidence references", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(identity))
      .mockResolvedValueOnce(json({ preview, binding }))
      .mockResolvedValueOnce(json({ confirmation }))
      .mockResolvedValueOnce(json({ result }));

    renderPanel();
    await compileRequest();
    fireEvent.click(screen.getByRole("button", { name: "Confirm and execute" }));

    const renderedResult = await screen.findByTestId("agent-cutover-result");
    expect(renderedResult).toHaveTextContent("completed");
    expect(renderedResult).toHaveTextContent(result.operation_id);
    expect(renderedResult).toHaveTextContent(result.execution_instance_hash);
    expect(renderedResult).toHaveTextContent("evidence:agent:1");
    expect(renderedResult).toHaveTextContent("evidence:lineage:1");
  });

  it("discards an old compile response after projectRoot or runId changes", async () => {
    let resolveCompile!: (response: Response) => void;
    const pendingCompile = new Promise<Response>((resolve) => {
      resolveCompile = resolve;
    });
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/identity")) {
        const projectRef = url.includes("%2Ftmp%2Fnew") ? "project:local:new" : "project:local:old";
        return Promise.resolve(json({ ...identity, project_ref: projectRef }));
      }
      if (url.endsWith("/compile")) return pendingCompile;
      throw new Error(`Unexpected request: ${url}`);
    });

    const rendered = renderPanel("/tmp/old", "run-old");
    const input = await screen.findByRole("textbox", { name: "Agent request" });
    await waitFor(() => expect(screen.getByTestId("agent-scope-identity")).toHaveTextContent("project:local:old"));
    fireEvent.change(input, { target: { value: "旧范围任务" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile plan" }));

    rendered.rerender(
      <MemoryRouter>
        <AgentCutoverPanel projectRoot="/tmp/new" runId="run-new" />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("agent-cutover-preview")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm and execute" })).not.toBeInTheDocument();
    expect(screen.getByTestId("agent-scope-identity")).toHaveTextContent(
      "Resolving server identity · run-new",
    );
    await waitFor(() => expect(screen.getByTestId("agent-scope-identity")).toHaveTextContent("project:local:new"));
    resolveCompile(json({ preview, binding }));

    await waitFor(() => expect(screen.queryByTestId("agent-cutover-preview")).not.toBeInTheDocument());
    expect(screen.queryByText("run:current")).not.toBeInTheDocument();
  });

  it("rejects an old A response after an A to B to A scope cycle", async () => {
    let resolveOldCompile!: (response: Response) => void;
    const oldCompile = new Promise<Response>((resolve) => {
      resolveOldCompile = resolve;
    });
    let identityCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.includes("/identity")) {
        identityCalls += 1;
        const projectRef = url.includes("%2Ftmp%2Fb") ? "project:local:b" : "project:local:a";
        return Promise.resolve(json({ ...identity, project_ref: projectRef }));
      }
      if (url.endsWith("/compile")) return oldCompile;
      throw new Error(`Unexpected request: ${url}`);
    });

    const rendered = renderPanel("/tmp/a", "run-a");
    const input = await screen.findByRole("textbox", { name: "Agent request" });
    await waitFor(() => expect(screen.getByTestId("agent-scope-identity")).toHaveTextContent("project:local:a"));
    fireEvent.change(input, { target: { value: "旧 A 请求" } });
    fireEvent.click(screen.getByRole("button", { name: "Compile plan" }));

    rendered.rerender(
      <MemoryRouter><AgentCutoverPanel projectRoot="/tmp/b" runId="run-b" /></MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("agent-scope-identity")).toHaveTextContent("project:local:b"));
    rendered.rerender(
      <MemoryRouter><AgentCutoverPanel projectRoot="/tmp/a" runId="run-a" /></MemoryRouter>,
    );
    await waitFor(() => expect(identityCalls).toBe(3));
    resolveOldCompile(json({ preview, binding }));

    await waitFor(() => expect(screen.queryByTestId("agent-cutover-preview")).not.toBeInTheDocument());
    expect(screen.queryByText("旧 A 请求")).not.toBeInTheDocument();
  });
});
