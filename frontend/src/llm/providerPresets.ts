import type { LlmProviderPreset } from "./llmTypes";

export const providerPresets: LlmProviderPreset[] = [
  { name: "DeepSeek", baseUrl: "https://api.deepseek.com" },
  { name: "OpenAI", baseUrl: "https://api.openai.com/v1" },
  { name: "GLM", baseUrl: "https://open.bigmodel.cn/api/paas/v4" },
  { name: "Moonshot", baseUrl: "https://api.moonshot.cn/v1" },
  {
    name: "Qwen",
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  },
  { name: "Custom", baseUrl: "" },
];
