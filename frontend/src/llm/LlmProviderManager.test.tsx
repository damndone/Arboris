import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LlmProviderManager } from "./LlmProviderManager";
import {
  activateLlmProvider,
  createLlmProvider,
  deleteLlmProvider,
  fetchLlmProviders,
  probeLlmProvider,
} from "./llmApi";
import type { LlmProvider, LlmProvidersResponse } from "./llmTypes";

vi.mock("./llmApi", () => ({
  activateLlmProvider: vi.fn(),
  createLlmProvider: vi.fn(),
  deleteLlmProvider: vi.fn(),
  fetchLlmProviders: vi.fn(),
  probeLlmProvider: vi.fn(),
  refreshLlmProviderModels: vi.fn(),
  updateLlmProvider: vi.fn(),
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
      {
        display_name: "DeepSeek Chat",
        request_model: "deepseek-chat",
        context_window_tokens: 128000,
        supports_1m: false,
      },
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
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchLlmProviders).mockResolvedValue(response());
    vi.mocked(activateLlmProvider).mockResolvedValue(providers[1]);
    vi.mocked(deleteLlmProvider).mockResolvedValue(providers[0]);
    vi.mocked(probeLlmProvider).mockResolvedValue(providers[0]);
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
    expect(manager).toHaveTextContent("LLM Providers");
    expect(screen.getByTestId("llm-provider-list")).toBeInTheDocument();
    expect(screen.getByTestId("llm-provider-active-deepseek")).toHaveTextContent("Active");
    expect(screen.getByText("API key configured")).toBeInTheDocument();
    expect(screen.getByText("API key missing")).toBeInTheDocument();
    expect(screen.getByText("deepseek-chat")).toBeInTheDocument();
    expect(screen.getByText(/https:\/\/api\.deepseek\.com/)).toBeInTheDocument();
    expect(screen.getAllByText(/Not tested/)).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: /add provider/i })).toBeInTheDocument();
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
