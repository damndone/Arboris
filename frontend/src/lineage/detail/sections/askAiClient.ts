import type { AskAIContextPacket } from "./askAiContextPacket";

export interface AskAIResponse {
  text: string;
}

export async function askAiForNode(
  packet: AskAIContextPacket,
  question: string,
): Promise<AskAIResponse> {
  const response = await fetch("/llm/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: "workbench_node_context_v1",
      question,
      packet,
      response_guardrails: packet.response_guardrails,
    }),
  });
  if (!response.ok) throw new Error(`Ask AI failed (${response.status})`);
  return response.json() as Promise<AskAIResponse>;
}
