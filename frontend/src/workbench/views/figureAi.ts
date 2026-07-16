import { apiUrl } from "../../api";

/** Serve-time context that lets the AI interpret a chart from its numbers. */
export interface FigureAiContext {
  figure_context_version: string;
  run_id: string;
  figure: { artifact_id: string; path: string; chart_type: string; sha256: string | null };
  source:
    | {
        artifact_id: string;
        path: string;
        kind: string;
        sha256: string | null;
        preview_json: string;
        preview_truncated: boolean;
      }
    | null;
  guidance: string;
  context_visibility_notice: Record<string, unknown>;
  response_guardrails: Record<string, unknown>;
}

export interface FigureAiAnswer {
  text: string;
  model?: string;
}

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
  context: FigureAiContext,
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
    }),
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
