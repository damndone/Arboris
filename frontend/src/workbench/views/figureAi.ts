import { apiUrl } from "../../api";
import type { RequestOf, ResponseOf, Schema } from "../../apiTypes";

/** Serve-time context that lets the AI interpret a chart from its numbers. */
export type FigureAiContext = Schema<"FigureAiContext">;

/** What the AI is told about a figure: the server's context, or one a chart
 * builds from its own persisted numeric artifact with its own notice and
 * guardrails. /llm/chat takes the packet as client-declared context. */
export type FigureAiPacket = Omit<FigureAiContext, "context_visibility_notice" | "response_guardrails"> & {
  context_visibility_notice: Record<string, unknown>;
  response_guardrails: Record<string, unknown>;
};
export type FigureAiAnswer = ResponseOf<"/llm/chat", "post">;

export async function fetchFigureAiContext(
  projectRoot: string,
  runId: string,
  artifactId: string,
): Promise<FigureAiContext> {
  const params = new URLSearchParams({
    project_root: projectRoot,
    run_id: runId,
    artifact_id: artifactId,
  });
  const response = await fetch(apiUrl(`/figures/ai-context?${params.toString()}`));
  if (!response.ok) {
    throw new Error(await extractError(response));
  }
  return response.json() as Promise<FigureAiContext>;
}

export async function askAiAboutFigure(
  context: FigureAiPacket,
  question: string,
  /** G2 step 2: only set after the user explicitly opted into sending the PNG. */
  imageDataUrl?: string,
): Promise<FigureAiAnswer> {
  const response = await fetch(apiUrl("/llm/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: "workbench_figure_context_v1",
      question,
      packet: context,
      response_guardrails: context.response_guardrails,
      ...(imageDataUrl ? { image_data_url: imageDataUrl } : {}),
    } satisfies RequestOf<"/llm/chat", "post">),
  });
  if (!response.ok) {
    throw new Error(await extractError(response));
  }
  return response.json() as Promise<FigureAiAnswer>;
}

/** Read a rendered figure as a PNG data URL. Only called on explicit opt-in. */
export async function figureAsDataUrl(url: string): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Could not read the figure image (${response.status})`);
  }
  const blob = await response.blob();
  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not encode the figure image"));
    reader.onload = () => resolve(String(reader.result));
    reader.readAsDataURL(blob);
  });
}

async function extractError(response: Response): Promise<string> {
  const fallback = `Request failed (${response.status})`;
  try {
    const body: unknown = await response.json();
    const message = (body as { error?: { message?: unknown } }).error?.message;
    return typeof message === "string" && message.trim() !== "" ? message : fallback;
  } catch {
    return fallback;
  }
}
