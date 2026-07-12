import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LlmProviderEditor } from "./LlmProviderEditor";
import {
  createLlmProvider,
  probeLlmProvider,
  refreshLlmProviderModels,
  updateLlmProvider,
} from "./llmApi";
import { providerPresets } from "./providerPresets";
import type { LlmProvider } from "./llmTypes";

vi.mock("./llmApi", () => ({
  activateLlmProvider: vi.fn(),
  createLlmProvider: vi.fn(),
  deleteLlmProvider: vi.fn(),
  fetchLlmProviders: vi.fn(),
  probeLlmProvider: vi.fn(),
  refreshLlmProviderModels: vi.fn(),
  updateLlmProvider: vi.fn(),
}));

const provider: LlmProvider = {
  id: "openai",
  name: "OpenAI",
  icon: "openai-mark",
  notes: "Primary coding provider",
  website_url: "https://openai.com",
  base_url: "https://api.openai.com/v1",
  model: "gpt-4o",
  timeout_s: 60,
  models: [
    {
      display_name: "GPT-4o",
      request_model: "gpt-4o",
      context_window_tokens: 128000,
      supports_1m: false,
    },
  ],
  key_present: true,
};

const savedProvider = { ...provider, name: "Saved provider" };

describe("LlmProviderEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(createLlmProvider).mockResolvedValue(savedProvider);
    vi.mocked(updateLlmProvider).mockResolvedValue(savedProvider);
    vi.mocked(probeLlmProvider).mockResolvedValue(provider);
    vi.mocked(refreshLlmProviderModels).mockResolvedValue({
      ...provider,
      model: "gpt-4.1",
      models: [
        {
          display_name: "GPT-4.1",
          request_model: "gpt-4.1",
          context_window_tokens: 1048576,
          supports_1m: true,
        },
      ],
    });
  });

  it("renders the full-height editor with basic, advanced, mapping, and sanitized preview sections", () => {
    render(<LlmProviderEditor provider={provider} onSaved={vi.fn()} onBack={vi.fn()} />);

    expect(screen.getByTestId("llm-provider-editor")).toHaveAttribute("role", "dialog");
    expect(screen.getByRole("button", { name: /back/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/provider name/i)).toHaveValue("OpenAI");
    expect(screen.getByLabelText(/website url/i)).toHaveValue("https://openai.com");
    expect(screen.getByLabelText("api key")).toHaveAttribute("type", "password");
    expect(screen.getByText("Advanced options")).toBeInTheDocument();
    expect(screen.getByTestId("llm-provider-model-row-gpt-4o")).toHaveTextContent("128,000");
    expect(screen.getByTestId("llm-provider-model-row-gpt-4o")).toHaveTextContent("No");
    expect(screen.getByLabelText("icon")).toHaveValue("openai-mark");
    expect(screen.getByLabelText("notes")).toHaveValue("Primary coding provider");
    expect(screen.getByRole("combobox", { name: "api format" })).toBeDisabled();
    expect(screen.getByTestId("llm-provider-config-preview")).toHaveTextContent("Primary coding provider");
    expect(screen.getByTestId("llm-provider-config-preview")).not.toHaveTextContent("api_key");
    expect(screen.getByTestId("llm-provider-config-preview")).not.toHaveTextContent("secret");
  });

  it("sanitizes a newly typed API key in the config preview", () => {
    const secret = "new-secret-value";
    render(<LlmProviderEditor onSaved={vi.fn()} onBack={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("api key"), { target: { value: secret } });

    const preview = screen.getByTestId("llm-provider-config-preview");
    expect(preview).not.toHaveTextContent(secret);
    expect(preview).not.toHaveTextContent("api_key");
  });

  it("requires name, absolute HTTP(S) Base URL, and model", async () => {
    render(<LlmProviderEditor onSaved={vi.fn()} onBack={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByText("Provider name is required")).toBeInTheDocument();
    expect(screen.getByText("Provider ID is required")).toBeInTheDocument();
    expect(screen.getByText("Base URL is required")).toBeInTheDocument();
    expect(screen.getByText("Default model is required")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/provider name/i), { target: { value: "Custom" } });
    fireEvent.change(screen.getByLabelText(/provider id/i), { target: { value: "custom-provider" } });
    fireEvent.change(screen.getByLabelText(/base url/i), { target: { value: "localhost:9000" } });
    fireEvent.change(screen.getByLabelText(/default model/i), { target: { value: "model" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(await screen.findByText("Base URL must be an absolute http(s) URL")).toBeInTheDocument();
    expect(createLlmProvider).not.toHaveBeenCalled();
  });

  it("validates a new provider id and includes it with management metadata", async () => {
    const onSaved = vi.fn();
    render(<LlmProviderEditor onSaved={onSaved} onBack={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/provider id/i), { target: { value: "bad/id" } });
    fireEvent.change(screen.getByLabelText(/provider name/i), { target: { value: "Custom" } });
    fireEvent.change(screen.getByLabelText(/icon/i), { target: { value: "custom-mark" } });
    fireEvent.change(screen.getByLabelText(/notes/i), { target: { value: "Context notes" } });
    fireEvent.change(screen.getByLabelText(/base url/i), { target: { value: "https://example.com" } });
    fireEvent.change(screen.getByLabelText(/default model/i), { target: { value: "model" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByText("Provider ID must be a route-safe slug")).toBeInTheDocument();
    expect(createLlmProvider).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/provider id/i), { target: { value: "custom-provider" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(createLlmProvider).toHaveBeenCalledWith(expect.objectContaining({
      id: "custom-provider",
      icon: "custom-mark",
      notes: "Context notes",
    })));
    expect(vi.mocked(createLlmProvider).mock.calls[0][0]).not.toHaveProperty("api_key");
  });

  it("fills only name and Base URL from each preset", () => {
    render(<LlmProviderEditor onSaved={vi.fn()} onBack={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/provider preset/i), { target: { value: providerPresets[0].name } });

    expect(screen.getByLabelText(/provider name/i)).toHaveValue("DeepSeek");
    expect(screen.getByLabelText(/base url/i)).toHaveValue("https://api.deepseek.com");
    expect(screen.getByLabelText(/default model/i)).toHaveValue("");
  });

  it("reveals a masked key and supports an explicit clear action", () => {
    render(<LlmProviderEditor provider={provider} onSaved={vi.fn()} onBack={vi.fn()} />);
    const key = screen.getByLabelText("api key");
    fireEvent.click(screen.getByRole("button", { name: /show api key/i }));
    expect(key).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: /clear api key/i }));
    expect(screen.getByTestId("llm-provider-key-cleared")).toHaveTextContent("will be cleared");
  });

  it("omits a blank api_key when updating an existing provider", async () => {
    render(<LlmProviderEditor provider={provider} onSaved={vi.fn()} onBack={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(updateLlmProvider).toHaveBeenCalledWith(
      "openai",
      expect.not.objectContaining({ api_key: expect.anything(), clear_api_key: expect.anything() }),
    ));
  });

  it("sends clear_api_key only for an explicit clear", async () => {
    render(<LlmProviderEditor provider={provider} onSaved={vi.fn()} onBack={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /clear api key/i }));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(updateLlmProvider).toHaveBeenCalledWith(
      "openai",
      expect.objectContaining({ clear_api_key: true }),
    ));
    expect(vi.mocked(updateLlmProvider).mock.calls[0][1]).not.toHaveProperty("api_key");
  });

  it("probes the provider and refreshes model mappings including context and 1M", async () => {
    render(<LlmProviderEditor provider={provider} onSaved={vi.fn()} onBack={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /test connection/i }));
    await waitFor(() => expect(probeLlmProvider).toHaveBeenCalledWith("openai"));
    expect(await screen.findByText("Connection successful")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /refresh models/i }));
    await waitFor(() => expect(refreshLlmProviderModels).toHaveBeenCalledWith("openai"));
    expect(await screen.findByTestId("llm-provider-model-row-gpt-4.1")).toHaveTextContent("1,048,576");
    expect(screen.getByTestId("llm-provider-model-row-gpt-4.1")).toHaveTextContent("Yes");
    expect(screen.getByLabelText(/default model/i)).toHaveValue("gpt-4.1");
  });

  it("shows loading, API errors, and success feedback", async () => {
    let resolve: (value: LlmProvider) => void = () => undefined;
    vi.mocked(createLlmProvider).mockImplementationOnce(
      () => new Promise<LlmProvider>((res) => { resolve = res; }),
    );
    render(<LlmProviderEditor onSaved={vi.fn()} onBack={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/provider id/i), { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText(/provider name/i), { target: { value: "Custom" } });
    fireEvent.change(screen.getByLabelText(/base url/i), { target: { value: "https://example.com" } });
    fireEvent.change(screen.getByLabelText(/default model/i), { target: { value: "model" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
    resolve(savedProvider);
    expect(await screen.findByText("Provider saved")).toBeInTheDocument();

    vi.mocked(createLlmProvider).mockRejectedValueOnce(new Error("save failed"));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("save failed");
  });
});
