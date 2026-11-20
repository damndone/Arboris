import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LlmProviderManager } from "./LlmProviderManager";
import {
  activateLlmProvider,
  createLlmProvider,
  deleteLlmProvider,
  detectLlmProviderModels,
  fetchLlmProviders,
  probeLlmProvider,
  refreshLlmProviderModels,
  updateLlmProvider,
} from "./llmApi";
import {
  fetchDomainMemorySettings,
  listDomainMemoryLibrary,
} from "../notebook/domainMemoryApi";
import type { LlmProvider, LlmProvidersResponse } from "./llmTypes";
import { llmModelFixture } from "../apiFixtures";
import * as agentApi from "../workbench/agent/agentApi";

vi.mock("./llmApi", () => ({
  activateLlmProvider: vi.fn(),
  createLlmProvider: vi.fn(),
  deleteLlmProvider: vi.fn(),
  detectLlmProviderModels: vi.fn(),
  fetchLlmProviders: vi.fn(),
  probeLlmProvider: vi.fn(),
  refreshLlmProviderModels: vi.fn(),
  updateLlmProvider: vi.fn(),
}));

vi.mock("../notebook/domainMemoryApi", () => ({
  fetchDomainMemorySettings: vi.fn(),
  listDomainMemoryLibrary: vi.fn(),
  issueMemorySettingsConfirmation: vi.fn(),
  updateGlobalMemorySettings: vi.fn(),
  updateProjectMemorySetting: vi.fn(),
  issueArchiveMemoryConfirmation: vi.fn(),
  archiveMemoryLibraryEntries: vi.fn(),
}));

vi.mock("../workbench/agent/agentApi", async (importOriginal) => ({
  ...await importOriginal<typeof agentApi>(),
  getProjectAgentPermissions: vi.fn(),
  saveProjectAgentPermissions: vi.fn(),
}));

const providers: LlmProvider[] = [
  {
    id: "deepseek",
    name: "DeepSeek",
    icon: "deepseek-mark",
    notes: "Primary research provider",
    website_url: "https://deepseek.com",
    base_url: "https://api.deepseek.com",
    model: "deepseek-chat",
    timeout_s: 60,
    models: [
      llmModelFixture({
        display_name: "DeepSeek Chat",
        request_model: "deepseek-chat",
        context_window_tokens: 128000,
        supports_1m: false,
      }),
      llmModelFixture({
        display_name: "DeepSeek V4 Flash",
        request_model: "deepseek-v4-flash",
        context_window_tokens: null,
        supports_1m: false,
      }),
      llmModelFixture({
        display_name: "DeepSeek V4 Pro",
        request_model: "deepseek-v4-pro",
        context_window_tokens: null,
        supports_1m: false,
      }),
    ],
    key_present: true,
  },
  {
    id: "openai",
    name: "OpenAI",
    icon: "",
    notes: "",
    website_url: null,
    base_url: "https://api.openai.com/v1",
    model: "gpt-4o",
    timeout_s: 45,
    models: [],
    key_present: false,
  },
];

const response = (active_provider_id: string | null = "deepseek"): LlmProvidersResponse => ({
  active_provider_id,
  providers,
});

describe("LlmProviderManager", () => {
  it("detects capabilities on demand and leaves the mapped model list intact", async () => {
    vi.mocked(detectLlmProviderModels).mockResolvedValue({
      ...providers[0],
      models: providers[0].models.map((model, index) => index === 0
        ? { ...model, context_window_tokens: 256000 } : model),
    });
    render(<LlmProviderManager onBack={vi.fn()} />);
    const card = await screen.findByRole("group", { name: "Mapped models for DeepSeek" });
    expect(detectLlmProviderModels).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("llm-provider-detect-models-deepseek"));
    expect(await screen.findByText("DeepSeek model capabilities checked")).toBeVisible();
    expect(detectLlmProviderModels).toHaveBeenCalledWith("deepseek");
    expect(within(card).getByRole("button", { name: "Use model DeepSeek Chat" }))
      .toHaveAttribute("title", expect.stringContaining("256,000 tokens"));
    expect(within(card).getAllByRole("button")).toHaveLength(3);
    expect(refreshLlmProviderModels).not.toHaveBeenCalled();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchLlmProviders).mockResolvedValue(response());
    vi.mocked(activateLlmProvider).mockResolvedValue(providers[1]);
    vi.mocked(deleteLlmProvider).mockResolvedValue(providers[0]);
    vi.mocked(probeLlmProvider).mockResolvedValue(providers[0]);
    vi.mocked(refreshLlmProviderModels).mockResolvedValue({
      ...providers[0],
      models: [
        llmModelFixture({ display_name: "DeepSeek V4 Flash", request_model: "deepseek-v4-flash", context_window_tokens: null, supports_1m: false }),
        llmModelFixture({ display_name: "DeepSeek V4 Pro", request_model: "deepseek-v4-pro", context_window_tokens: null, supports_1m: false }),
      ],
    });
    vi.mocked(updateLlmProvider).mockResolvedValue({
      ...providers[0],
      model: "deepseek-v4-pro",
    });
    vi.mocked(fetchDomainMemorySettings).mockResolvedValue({
      global: { revision: 0, library_enabled: false },
      project: { revision: 0, library_enabled: false, inherit_global: false, candidate_generation_enabled: false },
      memory_authority: "server_owned",
    });
    vi.mocked(listDomainMemoryLibrary).mockResolvedValue({ library: "global", entries: [], memory_authority: "server_owned" });
  });

  it("renders provider status rows in a full-height manager dialog", async () => {
    render(<LlmProviderManager onBack={vi.fn()} />);

    const manager = await screen.findByTestId("llm-provider-manager");
    expect(manager).toHaveAttribute("role", "dialog");
    expect(manager).toHaveStyle({
      height: "100%",
      flex: "1 1 0",
      maxHeight: "100%",
      overflowY: "auto",
    });
    expect(manager).toHaveTextContent("Settings");
    expect(screen.getByTestId("llm-provider-list")).toBeInTheDocument();
    expect(screen.getByTestId("llm-provider-active-deepseek")).toHaveTextContent("Active");
    expect(screen.getByText("API key configured")).toBeInTheDocument();
    expect(screen.getByText("API key missing")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Model for DeepSeek" })).toHaveValue("deepseek-chat");
    expect(screen.getByText(/https:\/\/api\.deepseek\.com/)).toBeInTheDocument();
    expect(screen.getAllByText(/Not tested/)).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: /add provider/i })).toBeInTheDocument();
  });

  it("keeps memory management in the same Settings surface", async () => {
    render(<LlmProviderManager projectRoot="/project-a" onBack={vi.fn()} />);
    await screen.findByTestId("llm-provider-manager");

    const providersSection = screen.getByRole("button", { name: "LLM providers" });
    const memorySection = screen.getByRole("button", { name: "Memory" });
    expect(providersSection).toHaveAttribute("aria-pressed", "true");
    expect(memorySection).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByRole("button", { name: "Memory" }));

    expect(await screen.findByTestId("memory-settings-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("llm-provider-list")).not.toBeInTheDocument();
    expect(providersSection).toHaveAttribute("aria-pressed", "false");
    expect(memorySection).toHaveAttribute("aria-pressed", "true");
    expect(memorySection).toHaveStyle({ background: "var(--tint-fill)", color: "var(--on-tint)" });
  });

  it("edits the selected project's Agent permissions and saves all rule groups", async () => {
    vi.mocked(agentApi.getProjectAgentPermissions)
      .mockResolvedValueOnce({
        revision: "revision-a",
        rules: { allow: [{ class: "analyze" }], ask: [{ class: "high" }], deny: [] },
      })
      .mockResolvedValueOnce({ revision: "revision-c", rules: { allow: [], ask: [], deny: [] } });
    vi.mocked(agentApi.saveProjectAgentPermissions).mockImplementation(async (_root, body) => ({
      revision: "revision-b", rules: body.rules,
    }));
    const { rerender } = render(<LlmProviderManager onBack={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Agent permissions" })).not.toBeInTheDocument();
    rerender(<LlmProviderManager projectRoot="/project-a" onBack={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Agent permissions" }));
    const addDeny = await screen.findByRole("button", { name: "Add deny rule" });
    const save = screen.getByRole("button", { name: "Save rules" });
    expect(save).toBeDisabled();
    fireEvent.click(addDeny);
    fireEvent.change(screen.getByLabelText("Deny rule 1 permission class"), { target: { value: "derive" } });
    fireEvent.change(screen.getByLabelText("Deny rule 1 operation ID"), { target: { value: "model.genesis" } });
    fireEvent.click(save);
    expect(await screen.findByText("Rules saved.")).toBeVisible();
    expect(agentApi.getProjectAgentPermissions).toHaveBeenCalledWith("/project-a");
    expect(agentApi.saveProjectAgentPermissions).toHaveBeenCalledWith("/project-a", {
      expected_revision: "revision-a",
      rules: {
        allow: [{ class: "analyze" }], ask: [{ class: "high" }],
        deny: [{ class: "derive", operation_id: "model.genesis" }],
      },
    });
    expect(save).toBeDisabled();
    rerender(<LlmProviderManager projectRoot="/project-b" onBack={vi.fn()} />);
    await screen.findByRole("button", { name: "Add deny rule" });
    expect(agentApi.getProjectAgentPermissions).toHaveBeenLastCalledWith("/project-b");
    expect(screen.queryByLabelText("Deny rule 1 operation ID")).not.toBeInTheDocument();
  });

  it("keeps unsaved permission changes visible when saving fails", async () => {
    vi.mocked(agentApi.getProjectAgentPermissions).mockResolvedValue({
      revision: "revision-a", rules: { allow: [], ask: [], deny: [{ class: "derive" }] },
    });
    vi.mocked(agentApi.saveProjectAgentPermissions).mockRejectedValue(new Error("The project rules changed."));
    render(<LlmProviderManager projectRoot="/project-a" onBack={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Agent permissions" }));
    fireEvent.click(await screen.findByRole("button", { name: "Remove deny rule 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Save rules" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The project rules changed.");
    expect(screen.queryByRole("button", { name: "Remove deny rule 1" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload rules" })).toBeEnabled();
  });

  it("backs out and opens the editor for add and edit", async () => {
    const onBack = vi.fn();
    render(<LlmProviderManager onBack={onBack} />);
    await screen.findByTestId("llm-provider-manager");

    fireEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(onBack).toHaveBeenCalledOnce();

    fireEvent.click(screen.getByRole("button", { name: /add provider/i }));
    expect(screen.getByTestId("llm-provider-editor")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.getByTestId("llm-provider-manager")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("llm-provider-edit-openai"));
    expect(screen.getByTestId("llm-provider-editor")).toHaveTextContent("Edit provider");
  });

  it("activates through the API and refreshes the provider list", async () => {
    vi.mocked(fetchLlmProviders)
      .mockResolvedValueOnce(response())
      .mockResolvedValueOnce(response("openai"));
    render(<LlmProviderManager onBack={vi.fn()} />);
    await screen.findByTestId("llm-provider-manager");

    fireEvent.click(screen.getByTestId("llm-provider-activate-openai"));

    await waitFor(() => expect(activateLlmProvider).toHaveBeenCalledWith("openai"));
    await waitFor(() => expect(fetchLlmProviders).toHaveBeenCalledTimes(2));
    expect(await screen.findByTestId("llm-provider-active-openai")).toHaveTextContent("Active");
  });

  it("reloads externally updated provider settings and all mapped models without switching the default", async () => {
    const nvidia = {
      ...providers[0],
      id: "nvidia",
      name: "NVIDIA · Nemotron 3 Ultra (Free Trial)",
      model: "nvidia/nemotron-3-ultra-550b-a55b",
      models: [llmModelFixture({ display_name: "Nemotron 3 Ultra", request_model: "nvidia/nemotron-3-ultra-550b-a55b", context_window_tokens: 1048576, supports_1m: true })],
    };
    const updated = {
      ...nvidia,
      name: "NVIDIA NIM",
      models: [
        ...nvidia.models,
        llmModelFixture({ display_name: "GLM 5.3", request_model: "z-ai/glm-5.3", context_window_tokens: 1048576, supports_1m: true }),
        llmModelFixture({ display_name: "DeepSeek V4.1 Flash", request_model: "deepseek-ai/deepseek-v4.1-flash", context_window_tokens: 1048576, supports_1m: true }),
        llmModelFixture({ display_name: "GLM 5.3 Flash", request_model: "z-ai/glm-5.3-flash", context_window_tokens: 1048576, supports_1m: true }),
      ],
    };
    vi.mocked(fetchLlmProviders)
      .mockResolvedValueOnce({ active_provider_id: nvidia.id, providers: [nvidia] })
      .mockResolvedValueOnce({ active_provider_id: nvidia.id, providers: [updated] });
    render(<LlmProviderManager onBack={vi.fn()} />);
    await screen.findByText(nvidia.name);

    fireEvent.click(screen.getByRole("button", { name: "Reload providers" }));

    await screen.findByText(updated.name);
    expect(fetchLlmProviders).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(nvidia.name)).not.toBeInTheDocument();
    const selector = screen.getByRole("combobox", { name: "Model for NVIDIA NIM" });
    expect(selector).toHaveValue(nvidia.model);
    expect(within(selector).getAllByRole("option")).toHaveLength(4);
    const modelList = screen.getByTestId("llm-provider-models-nvidia");
    for (const model of updated.models) {
      expect(within(selector).getByRole("option", { name: model.display_name })).toHaveValue(model.request_model);
      expect(within(modelList).getByRole("button", { name: `Use model ${model.display_name}` }))
        .toHaveAttribute("title", expect.stringContaining(model.request_model));
    }
    expect(screen.getByTestId("llm-provider-active-nvidia")).toHaveTextContent("Active");
    expect(refreshLlmProviderModels).not.toHaveBeenCalled();
    expect(probeLlmProvider).not.toHaveBeenCalled();
    expect(activateLlmProvider).not.toHaveBeenCalled();
    expect(updateLlmProvider).not.toHaveBeenCalled();
  });

  it("deletes only after confirmation and refreshes after deletion", async () => {
    const confirm = vi.spyOn(window, "confirm");
    confirm.mockReturnValueOnce(false);
    render(<LlmProviderManager onBack={vi.fn()} />);
    await screen.findByTestId("llm-provider-manager");

    fireEvent.click(screen.getByTestId("llm-provider-delete-openai"));
    expect(confirm).toHaveBeenCalled();
    expect(deleteLlmProvider).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    fireEvent.click(screen.getByTestId("llm-provider-delete-openai"));
    await waitFor(() => expect(deleteLlmProvider).toHaveBeenCalledWith("openai"));
    await waitFor(() => expect(fetchLlmProviders).toHaveBeenCalledTimes(2));
    confirm.mockRestore();
  });

  it("shows API errors in the status region", async () => {
    vi.mocked(activateLlmProvider).mockRejectedValueOnce(new Error("activation failed"));
    render(<LlmProviderManager onBack={vi.fn()} />);
    await screen.findByTestId("llm-provider-manager");

    fireEvent.click(screen.getByTestId("llm-provider-activate-openai"));
    expect(await screen.findByRole("alert")).toHaveTextContent("activation failed");
  });

  it("refreshes and persists the provider model mapping from the manager", async () => {
    render(<LlmProviderManager onBack={vi.fn()} />);
    await screen.findByTestId("llm-provider-manager");

    fireEvent.click(screen.getByTestId("llm-provider-refresh-models-deepseek"));

    await waitFor(() => expect(refreshLlmProviderModels).toHaveBeenCalledWith("deepseek"));
    expect(await screen.findByTestId("llm-provider-models-deepseek")).toHaveTextContent("DeepSeek V4 Pro");
    expect(screen.getByTestId("llm-provider-manager-status")).toHaveTextContent("models refreshed");
  });

  it("switches the active provider model directly and exposes Configure", async () => {
    render(<LlmProviderManager onBack={vi.fn()} />);
    await screen.findByTestId("llm-provider-manager");

    expect(screen.getByTestId("llm-provider-configure-deepseek")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "Model for DeepSeek" }), {
      target: { value: "deepseek-v4-pro" },
    });

    await waitFor(() => expect(updateLlmProvider).toHaveBeenCalledWith("deepseek", {
      model: "deepseek-v4-pro",
    }));
    expect(await screen.findByTestId("llm-provider-manager-status")).toHaveTextContent(
      /model switched/i,
    );
  });

  it("lets each of eighteen model cards select a default without probing or activating another provider", async () => {
    const models = Array.from({ length: 18 }, (_, index) => llmModelFixture({
      display_name: `Nemotron variant ${index + 1}`,
      request_model: `nvidia/variant-${index + 1}`,
      context_window_tokens: 1_048_576,
      supports_1m: true,
    }));
    vi.mocked(fetchLlmProviders).mockResolvedValue({ active_provider_id: "deepseek", providers: [{ ...providers[0], models, model: models[0].request_model }] });
    vi.mocked(updateLlmProvider).mockResolvedValue({ ...providers[0], models, model: models[17].request_model });
    render(<LlmProviderManager onBack={vi.fn()} />);
    const list = await screen.findByTestId("llm-provider-models-deepseek");
    expect(within(list).getAllByRole("button")).toHaveLength(18);
    expect(within(list).getByRole("button", { name: "Use model Nemotron variant 18" }))
      .toHaveAttribute("title", `Nemotron variant 18\nnvidia/variant-18\nContext: 1,048,576 tokens`);
    expect(within(list).getByRole("button", { name: "Use model Nemotron variant 1" })).toHaveAttribute("aria-pressed", "true");
    expect(updateLlmProvider).not.toHaveBeenCalled();
    fireEvent.click(within(list).getByRole("button", { name: "Use model Nemotron variant 18" }));
    await waitFor(() => expect(updateLlmProvider).toHaveBeenCalledWith("deepseek", { model: models[17].request_model }));
    await waitFor(() => expect(within(list).getByRole("button", { name: "Use model Nemotron variant 18" })).toHaveAttribute("aria-pressed", "true"));
    expect(activateLlmProvider).not.toHaveBeenCalled();
    expect(probeLlmProvider).not.toHaveBeenCalled();
    expect(refreshLlmProviderModels).not.toHaveBeenCalled();
  });

  it("opens a fresh create editor for copy without carrying the API key", async () => {
    vi.mocked(createLlmProvider).mockResolvedValue({ ...providers[0], id: "deepseek-copy", name: "DeepSeek Copy", key_present: false });
    render(<LlmProviderManager onBack={vi.fn()} />);
    await screen.findByTestId("llm-provider-manager");

    fireEvent.click(screen.getByTestId("llm-provider-copy-deepseek"));

    expect(screen.getByText("Add provider")).toBeInTheDocument();
    expect(screen.getByLabelText(/provider id/i)).toHaveValue("deepseek-copy");
    expect(screen.getByLabelText(/provider name/i)).toHaveValue("DeepSeek Copy");
    expect(screen.getByLabelText("api key")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(createLlmProvider).toHaveBeenCalledWith(expect.objectContaining({
      id: "deepseek-copy",
      name: "DeepSeek Copy",
      icon: "deepseek-mark",
      notes: "Primary research provider",
    })));
    expect(vi.mocked(createLlmProvider).mock.calls[0][0]).not.toHaveProperty("api_key");
  });
});
