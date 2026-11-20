import { useEffect, useRef, useState } from "react";
import { appendAiActivity, askAiHistoryForNode, makeActivityId } from "../../aiActivity/aiActivityLog";
import { artifactDownloadUrl } from "../../api";
import type { ArtifactItem } from "../../api";
import { askAiAboutFigure, fetchFigureAiContext, figureAsDataUrl } from "./figureAi";
import { fetchLlmConfig } from "../../llm/llmApi";
import type { LlmConfigInfo } from "../../llm/llmTypes";
import { renderMarkdown } from "../../report/markdown";
import { humanize } from "./tableViewData";

export function FigureCard({
  item,
  projectRoot,
  runId,
}: {
  item: ArtifactItem;
  projectRoot: string;
  runId: string;
}) {
  const label = humanize(item.artifact_id);
  const imageUrl = artifactDownloadUrl(projectRoot, runId, item.artifact_id);
  const [menuOpen, setMenuOpen] = useState(false);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const closeWhenOutside = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && menuRef.current?.contains(target)) return;
      setMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeWhenOutside, true);
    document.addEventListener("keydown", closeOnEscape, true);
    return () => {
      document.removeEventListener("pointerdown", closeWhenOutside, true);
      document.removeEventListener("keydown", closeOnEscape, true);
    };
  }, [menuOpen]);

  async function copyChart() {
    setMenuOpen(false);
    try {
      const response = await fetch(imageUrl);
      if (!response.ok) throw new Error("chart download failed");
      const blob = await response.blob();
      if (!("clipboard" in navigator) || !("ClipboardItem" in window)) {
        throw new Error("clipboard is unavailable");
      }
      await navigator.clipboard.write([new ClipboardItem({ [blob.type || "image/png"]: blob })]);
      setCopyMessage("Chart copied");
    } catch {
      setCopyMessage("Copy is unavailable here — download the chart instead.");
    }
  }

  return (
    <figure style={{ margin: 0, position: "relative" }}>
      <img
        src={imageUrl}
        alt={`${item.artifact_id} figure`}
        loading="lazy"
        style={{
          width: "100%",
          height: "auto",
          borderRadius: 6,
          border: "1px solid var(--separator)",
          background: "var(--bg-card)",
        }}
        onContextMenu={(event) => {
          event.preventDefault();
          setCopyMessage(null);
          setMenuOpen(true);
        }}
      />
      {menuOpen && (
        <div ref={menuRef} className="wb-chart-context-menu" role="menu" aria-label="Chart actions">
          <button type="button" role="menuitem" onClick={() => void copyChart()}>Copy chart</button>
          <a role="menuitem" href={imageUrl} download={`${item.artifact_id}.png`} onClick={() => setMenuOpen(false)}>Download chart</a>
        </div>
      )}
      {copyMessage && <div role="status" style={{ fontSize: 11, marginTop: 4 }}>{copyMessage}</div>}
      <figcaption
        style={{ fontSize: 12, color: "var(--label-secondary)", marginTop: 4 }}
      >
        {label}
      </figcaption>
      <FigureAskAi item={item} projectRoot={projectRoot} runId={runId} />
    </figure>
  );
}

/** G2: interpret a chart from the numbers it was drawn from (not the pixels). */
/** Activity key for a figure explanation, so it shares the node Ask AI log. */
export function figureActivityKey(artifactId: string): string {
  return `figure:${artifactId}`;
}

export function FigureAskAi({
  item,
  projectRoot,
  runId,
}: {
  item: ArtifactItem;
  projectRoot: string;
  runId: string;
}) {
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [answer, setAnswer] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chartType, setChartType] = useState<string | null>(null);
  const [sendImage, setSendImage] = useState(false);
  const [llmConfig, setLlmConfig] = useState<LlmConfigInfo | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchLlmConfig()
      .then((config) => {
        if (!cancelled) setLlmConfig(config);
      })
      .catch(() => {
        /* vision opt-in simply stays hidden when the config is unreadable */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // A tab switch unmounts this component, so an answer held only in local
  // state disappeared the moment the user looked at the graph and came back.
  // The explanation is a real AI exchange: it belongs in the durable log, and
  // restoring from that log is what makes it survive.
  useEffect(() => {
    if (!projectRoot) return;
    const previous = askAiHistoryForNode(projectRoot, figureActivityKey(item.artifact_id));
    const latest = previous[previous.length - 1];
    if (latest?.status === "answered" && latest.answer) {
      setAnswer(latest.answer);
      setStatus("done");
    }
  }, [projectRoot, item.artifact_id]);

  const visionAvailable = llmConfig?.configured === true && llmConfig.supports_vision === true;

  async function handleAsk() {
    if (!projectRoot) return;
    setStatus("loading");
    setError(null);
    setAnswer(null);
    try {
      const context = await fetchFigureAiContext(projectRoot, runId, item.artifact_id);
      setChartType(context.figure.chart_type);
      const question = sendImage
        ? `Interpret this ${context.figure.chart_type} for me: what does it show about the analysis, and what should I watch out for? Take every number from the numeric source; use the image only for visual structure.`
        : `Interpret this ${context.figure.chart_type} for me: what does it show about the analysis, and what should I watch out for? Use only the numeric source in the context.`;
      const imageDataUrl =
        sendImage && visionAvailable
          ? await figureAsDataUrl(artifactDownloadUrl(projectRoot, runId, item.artifact_id))
          : undefined;
      const response = await askAiAboutFigure(context, question, imageDataUrl, projectRoot);
      setAnswer(response.text);
      setStatus("done");
      logFigureExchange({
        question,
        status: "answered",
        answer: response.text,
        chartType: context.figure.chart_type,
      });
    } catch (reason: unknown) {
      const message = reason instanceof Error ? reason.message : String(reason);
      setError(message);
      setStatus("error");
      // Failures are logged too: an AI activity trail that only records
      // successes is not a record of what the AI was asked to do.
      logFigureExchange({ question: "", status: "error", error: message });
    }
  }

  function logFigureExchange(record: {
    question: string;
    status: "answered" | "error";
    answer?: string;
    error?: string;
    chartType?: string | null;
  }) {
    if (!projectRoot) return;
    appendAiActivity(projectRoot, {
      kind: "ask_ai",
      id: makeActivityId(),
      at: new Date().toISOString(),
      node_key: figureActivityKey(item.artifact_id),
      node_label: record.chartType
        ? `Figure · ${record.chartType}`
        : `Figure · ${item.artifact_id}`,
      question: record.question,
      status: record.status,
      answer: record.answer,
      error: record.error,
    });
  }

  return (
    <div data-testid={`figure-ask-ai-${item.artifact_id}`} style={{ marginTop: 6 }}>
      <button
        type="button"
        data-testid={`figure-ask-ai-button-${item.artifact_id}`}
        disabled={status === "loading"}
        onClick={() => void handleAsk()}
        style={{ fontSize: 11 }}
      >
        {status === "loading" ? "Asking AI…" : "Ask AI about this figure"}
      </button>
      {/* G2 step 2 — opt-in only, default off, and it names the destination:
       *  this is the one place the binaries-excluded policy is broken, so the
       *  user must see exactly what leaves the machine and to whom. */}
      {visionAvailable && (
        <label
          data-testid={`figure-send-image-${item.artifact_id}`}
          style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 11, marginTop: 4 }}
        >
          <input
            type="checkbox"
            aria-label={`Also send the ${humanize(item.artifact_id)} image to the model`}
            checked={sendImage}
            disabled={status === "loading"}
            onChange={(event) => setSendImage(event.target.checked)}
          />
          <span style={{ color: "var(--label-tertiary)" }}>
            Also send the rendered image to {llmConfig?.provider_name ?? "the provider"} (
            {llmConfig?.model ?? "vision model"}) — leaves your machine
          </span>
        </label>
      )}
      {chartType && status !== "idle" && (
        <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginTop: 4 }}>
          Interpreting from numeric source · {chartType}
        </div>
      )}
      {status === "error" && (
        <div
          data-testid={`figure-ask-ai-error-${item.artifact_id}`}
          role="alert"
          style={{ fontSize: 11, color: "var(--status-fails-fg)", marginTop: 4 }}
        >
          {error}
        </div>
      )}
      {status === "done" && answer && (
        <div
          data-testid={`figure-ask-ai-answer-${item.artifact_id}`}
          style={{
            fontSize: 12,
            marginTop: 6,
            padding: 8,
            whiteSpace: "pre-wrap",
            background: "var(--bg-card-2)",
            borderRadius: 6,
          }}
        >
          {renderMarkdown(answer)}
        </div>
      )}
    </div>
  );
}
