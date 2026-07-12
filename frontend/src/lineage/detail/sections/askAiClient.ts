import { apiUrl } from "../../../api";
import type { AskAIContextPacket } from "./askAiContextPacket";

export interface AskAIResponse {
  text: string;
  model?: string;
  context_fingerprint?: string | null;
}

export async function askAiForNode(
  packet: AskAIContextPacket,
  question: string,
): Promise<AskAIResponse> {
  const response = await fetch(apiUrl("/llm/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: "workbench_node_context_v1",
      question,
      packet,
      response_guardrails: packet.response_guardrails,
    }),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return response.json() as Promise<AskAIResponse>;
}

// v1.6.12 T5 (A4) — read-only provider info. The backend never sends the key
// (only key_present); the panel shows which model answers and where to
// configure it, key management stays in the env file.
export interface LlmConfigInfo {
  configured: boolean;
  base_url: string | null;
  model: string | null;
  key_present: boolean;
}

export async function fetchLlmConfig(): Promise<LlmConfigInfo> {
  const response = await fetch(apiUrl("/llm/config"));
  if (!response.ok) throw new Error(`LLM config unavailable (${response.status})`);
  return response.json() as Promise<LlmConfigInfo>;
}

async function extractErrorMessage(response: Response): Promise<string> {
  const fallback = `Ask AI failed (${response.status})`;
  try {
    const body: unknown = await response.json();
    const message = (body as { error?: { message?: unknown } }).error?.message;
    return typeof message === "string" && message.trim() !== ""
      ? message
      : fallback;
  } catch {
    return fallback;
  }
}
