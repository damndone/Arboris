import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createLlmProvider } from "./llmApi";

describe("llmApi", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a provider without exposing its API key in the public type", async () => {
    const publicProvider = {
      id: "deepseek",
      name: "DeepSeek",
      website_url: null,
      base_url: "https://api.deepseek.com",
      model: "deepseek-chat",
      timeout_s: 60,
      models: [],
      key_present: true,
    };
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(publicProvider), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const result = await createLlmProvider({
      id: "deepseek",
      name: "DeepSeek",
      base_url: "https://api.deepseek.com",
      model: "deepseek-chat",
      api_key: "secret-key",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/llm/providers",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: "deepseek",
          name: "DeepSeek",
          base_url: "https://api.deepseek.com",
          model: "deepseek-chat",
          api_key: "secret-key",
        }),
      }),
    );
    expect(result.key_present).toBe(true);
    expect("api_key" in result).toBe(false);
  });
});
