import { apiUrl } from "../../../api";
import type { RequestOf, ResponseOf } from "../../../apiTypes";
import type { AskAIContextPacket } from "./askAiContextPacket";
export { fetchLlmConfig } from "../../../llm/llmApi";
export type { LlmConfigInfo } from "../../../llm/llmTypes";

export type AskAIResponse = ResponseOf<"/llm/chat", "post">;

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
    } satisfies RequestOf<"/llm/chat", "post">),
  });
  if (!response.ok) {
    throw new Error(await extractErrorMessage(response));
  }
  return response.json() as Promise<AskAIResponse>;
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
