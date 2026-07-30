// frontend/src/workbench/views/TableView.tsx
//
// v1.6.6 ② — Table result-preview. Switching from the Graph view to Table
// shows a fast read-only preview of what the run PRODUCED:
//   1. model coefficient tables (fetchRunDetail),
//   2. a gallery of every generated figure rendered inline (fetchRunArtifacts
//      + the /runs/{id}/artifacts/{artifact_id} file endpoint),
//   3. download links for the remaining (non-figure) artifacts.
//
// Non-goals: in-table editing, variable-level DAG tabulation (future). The
// SET of figures shown is whatever the run's `visualization` step emitted —
// widening that coverage (violin/pairplot/…) is a backend concern (roadmap
// §3.5 V).

import { useEffect, useMemo, useRef, useState } from "react";
import {
  appendAiActivity,
  askAiHistoryForNode,
  makeActivityId,
} from "../../aiActivity/aiActivityLog";
import { useSearchParams } from "react-router-dom";
import { useLineage } from "../../lineage/LineageContext";
import { useForest } from "../ForestContext";
import { useProjectRootOptional } from "../ProjectRootContext";
import {
  artifactDownloadUrl,
  fetchArtifactJson,
  fetchRunArtifacts,
  fetchRunDetail,
} from "../../api";
import type { ArtifactGroup, ArtifactItem, ModelResult, RunDetail } from "../../api";
import { buildRepeatedMeasuresViewModel } from "../repeatedMeasures/repeatedMeasuresViewModel";
import { askAiAboutFigure, fetchFigureAiContext, figureAsDataUrl } from "./figureAi";
import { fetchLlmConfig } from "../../llm/llmApi";
import type { LlmConfigInfo } from "../../llm/llmTypes";
import { renderMarkdown } from "../../report/markdown";
import { ArmaGarchChartGallery } from "../../runResult/ArmaGarchChartGallery";
import {
  ARMA_GARCH_CHART_IDS,
  useArmaGarchCharts,
} from "../../runResult/useArmaGarchCharts";
import { StatisticalExplorationTable } from "./StatisticalExplorationTable";
import { resolveTableRunScope } from "./tableRunScope";

/** Run ids look like 20260703_065622_030010_92222fe1 — the last hex segment is
 *  the unique tail, matching the run-rail's short label so the two line up. */
function shortRunId(id: string): string {
  const tail = id.split("_").pop() ?? id;
  return tail.slice(0, 8);
}

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return String(Number(n.toPrecision(4)));
}

function confidenceIntervalText(coefficient: {
  ci_lower?: number | null;
  ci_upper?: number | null;
  confidence_interval?: readonly [number, number] | null;
}): string {
  const lower = typeof coefficient.ci_lower === "number" ? coefficient.ci_lower : coefficient.confidence_interval?.[0];
  const upper = typeof coefficient.ci_upper === "number" ? coefficient.ci_upper : coefficient.confidence_interval?.[1];
  if (typeof lower !== "number" || typeof upper !== "number") return "—";
  return `[${fmt(lower)}, ${fmt(upper)}]`;
}

/** "correlation_heatmap" → "Correlation heatmap" for captions/alt text. */
function humanize(id: string): string {
  const s = id.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function CoefficientTable({ model }: { model: ModelResult }) {
  const repeatedMeasures = buildRepeatedMeasuresViewModel(model);
  const rows = repeatedMeasures.kind === "complete"
    ? [[repeatedMeasures.primaryCoefficient.result_id, repeatedMeasures.primaryCoefficient] as const]
    : Object.entries(model.coefficients ?? {});
  const diagnostics = repeatedMeasures.kind === "complete"
    ? repeatedMeasures.diagnostics.map((diagnostic) => diagnostic.code)
    : [];
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: "var(--label)", marginBottom: 4 }}>
        {model.model_id}
        {model.model_type ? ` · ${model.model_type}` : ""}
      </div>
      <div style={{ fontSize: 11, color: "var(--label-tertiary)", marginBottom: 6 }}>
        {model.nobs !== undefined ? `n=${model.nobs}` : null}
        {model.r_squared != null ? ` · R²=${fmt(model.r_squared)}` : null}
        {model.r_squared_adj != null ? ` · adj. R²=${fmt(model.r_squared_adj)}` : null}
      </div>
      <div
        className="wb-result-table-scroll"
        data-testid="table-view-coefficient-scroll"
        tabIndex={0}
        aria-label="Coefficient table scroll region"
      >
      <table className="wb-result-table" style={{ borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ textAlign: "left", color: "var(--label-secondary)" }}>
            <th style={{ padding: "2px 8px" }}>term</th>
            <th style={{ padding: "2px 8px" }}>estimate</th>
            <th style={{ padding: "2px 8px" }}>std. error</th>
            <th style={{ padding: "2px 8px" }}>p-value</th>
            <th style={{ padding: "2px 8px" }}>95% CI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([term, c]) => (
            <tr key={term} style={{ borderTop: "1px solid var(--separator)" }}>
              <td style={{ padding: "2px 8px", fontFamily: "var(--font-mono, monospace)" }}>{term}</td>
              <td style={{ padding: "2px 8px" }}>{fmt(c.estimate)}</td>
              <td style={{ padding: "2px 8px" }}>{fmt(c.std_error)}</td>
              <td style={{ padding: "2px 8px" }}>
                {("p_value_display" in c ? c.p_value_display : undefined) ?? fmt(c.p_value)}
              </td>
              <td style={{ padding: "2px 8px", whiteSpace: "nowrap" }}>{confidenceIntervalText(c)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {diagnostics.length > 0 && (
        <div
          data-testid="table-view-lmm-diagnostics"
          style={{ marginTop: 8, fontSize: 11, color: "var(--orange, #b35c00)" }}
        >
          Diagnostic: {diagnostics.join(", ")}
        </div>
      )}
    </div>
  );
}

function FigureCard({
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
          background: "var(--surface, #fff)",
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
function figureActivityKey(artifactId: string): string {
  return `figure:${artifactId}`;
}

function FigureAskAi({
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
      const response = await askAiAboutFigure(context, question, imageDataUrl);
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
          style={{ fontSize: 11, color: "var(--accent-negative, #d33)", marginTop: 4 }}
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
            background: "var(--bg-card-2, rgba(0,0,0,0.03))",
            borderRadius: 6,
          }}
        >
          {renderMarkdown(answer)}
        </div>
      )}
    </div>
  );
}

const CONTAINER_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  padding: "12px 24px 24px",
  gap: 20,
  height: "100%",
  minHeight: 0,
  minWidth: 0,
  overflow: "auto",
};

const FIGURE_GRID: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
  gap: 16,
};

export function TableView({ projectRoot: projectRootProp }: { projectRoot?: string }) {
  const { model } = useLineage();
  const forest = useForest();
  const [searchParams] = useSearchParams();
  const contextProjectRoot = useProjectRootOptional();
  const projectRoot = projectRootProp ?? contextProjectRoot ?? searchParams.get("project_root") ?? "";

  // Table is the project-wide result browser: selecting a Graph node must not
  // hide sibling Run results. The active Run chooses the one visible result
  // panel, and the same ForestContext setter drives the Graph highlight.
  const runIds = useMemo(
    () =>
      resolveTableRunScope({
        forest: forest?.forest ?? null,
        activeRunId: forest?.activeRunId ?? null,
        selectedKey: null,
        fallbackRunId: forest?.activeRunId ?? model.runId,
      }),
    [forest, model.runId],
  );
  const activeRunId = runIds.includes(forest?.activeRunId ?? "")
    ? forest?.activeRunId ?? null
    : runIds[0] ?? null;

  return (
    <div data-testid="view-table" data-view="table" style={CONTAINER_STYLE}>
      {runIds.length > 0 && activeRunId && (
        <nav
          data-testid="table-view-run-picker"
          className="wb-run-version-picker"
          aria-label="Run results"
          style={{ margin: "-12px -24px 0" }}
        >
          <span className="wb-run-version-picker__label">Versions:</span>
          {runIds.map((runId) => (
            <button
              key={runId}
              type="button"
              className="wb-run-version-picker__button"
              aria-pressed={runId === activeRunId}
              aria-label={`Show results for run ${runId}`}
              title={runId}
              onClick={() => forest?.setActiveRunId(runId)}
            >
              {shortRunId(runId)}
            </button>
          ))}
        </nav>
      )}
      {activeRunId && (
        <RunResultsPanel
          runId={activeRunId}
          projectRoot={projectRoot}
          scopeSize={1}
        />
      )}
    </div>
  );
}

function RunResultsPanel({
  runId,
  projectRoot,
  scopeSize,
}: {
  runId: string;
  projectRoot: string;
  scopeSize: number;
}) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [explorations, setExplorations] = useState<Array<{ item: ArtifactItem; payload: unknown }>>([]);
  const [artifactGroups, setArtifactGroups] = useState<ArtifactGroup[] | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Table already owns the artifact listing request. Reusing that listing
  // avoids a second request while letting the same chart loader used by the
  // run-detail dashboard draw structured `ts.chart.*` evidence here too.
  const armaGarchCharts = useArmaGarchCharts(
    projectRoot,
    artifactGroups === undefined ? null : runId,
    artifactGroups,
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setArtifactGroups(undefined);
    setExplorations([]);
    Promise.all([
      fetchRunDetail(projectRoot, runId),
      fetchRunArtifacts(projectRoot, runId),
    ])
      .then(async ([d, a]) => {
        const explorationItems = a.groups
          .filter((group) => group.artifact_type === "statistical_exploration")
          .flatMap((group) => group.items);
        const explorationResults = (await Promise.all(
          explorationItems.map(async (item) => {
            try {
              return { item, payload: await fetchArtifactJson(projectRoot, runId, item.artifact_id) };
            } catch {
              return null;
            }
          }),
        )).filter((entry): entry is { item: ArtifactItem; payload: unknown } => entry !== null);
        if (cancelled) return;
        setDetail(d);
        setArtifactGroups(a.groups);
        setArtifacts(a.groups.flatMap((g) => g.items));
        setExplorations(explorationResults);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, projectRoot]);

  const models = detail?.model_results ?? [];
  const figures = artifacts.filter((a) => a.artifact_type === "figure");
  const loadedExplorationIds = new Set(explorations.map(({ item }) => item.artifact_id));
  const otherArtifacts = artifacts.filter((a) =>
    a.artifact_type !== "figure" && !loadedExplorationIds.has(a.artifact_id),
  );
  const chartArtifactIds = new Set<string>(Object.values(ARMA_GARCH_CHART_IDS));
  const hasArmaGarchChartArtifacts = artifacts.some((artifact) =>
    chartArtifactIds.has(artifact.artifact_id),
  );
  const isEmpty =
    !loading &&
    !error &&
    models.length === 0 &&
    explorations.length === 0 &&
    figures.length === 0 &&
    otherArtifacts.length === 0;

  // An empty run is noise when several runs are on screen; on its own it is the
  // honest answer to "what did this run produce?".
  if (isEmpty && scopeSize > 1) return null;

  return (
    <div data-run-id={runId}>
      <header
        data-testid="table-view-run-header"
        title={runId}
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 8,
          paddingBottom: 8,
          borderBottom: "1px solid var(--separator)",
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--label)" }}>
          Results
        </span>
        <span
          style={{
            fontSize: 12,
            fontFamily: "var(--font-mono, monospace)",
            color: "var(--label-secondary)",
          }}
        >
          run {shortRunId(runId)}
        </span>
      </header>

      {loading && (
        <div data-testid="table-view-loading" style={{ color: "var(--label-secondary)" }}>
          Loading results…
        </div>
      )}

      {error && (
        <div data-testid="table-view-error" style={{ color: "var(--red, #c00)" }}>
          Failed to load results: {error}
        </div>
      )}

      {!loading && !error && models.length > 0 && (
        <section data-testid="table-view-coefficients">
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Coefficients</h3>
          {models.map((m) => (
            <CoefficientTable key={m.model_id} model={m} />
          ))}
        </section>
      )}

      {!loading && !error && explorations.length > 0 && (
        <StatisticalExplorationTable explorations={explorations} />
      )}

      {!loading && !error && figures.length > 0 && (
        <section data-testid="table-view-figures">
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>
            Figures ({figures.length})
          </h3>
          <div style={FIGURE_GRID}>
            {figures.map((f) => (
              <FigureCard key={f.artifact_id} item={f} projectRoot={projectRoot} runId={runId} />
            ))}
          </div>
        </section>
      )}

      {!loading && !error && hasArmaGarchChartArtifacts && (
        <section data-testid="table-view-time-series-charts">
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>
            Time-series charts
          </h3>
          <div
            className="wb-result-artifact-scroll"
            data-testid="table-view-time-series-scroll"
            tabIndex={0}
            aria-label="Time-series chart scroll region"
          >
            <div className="wb-result-artifact-scroll__content">
              <ArmaGarchChartGallery charts={armaGarchCharts} />
            </div>
          </div>
        </section>
      )}

      {!loading && !error && otherArtifacts.length > 0 && (
        <section data-testid="table-view-artifacts">
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Artifacts</h3>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: "var(--label-secondary)" }}>
            {otherArtifacts.map((a) => (
              <li key={a.artifact_id} style={{ marginBottom: 2 }}>
                <a
                  href={artifactDownloadUrl(projectRoot, runId, a.artifact_id)}
                  target="_blank"
                  rel="noreferrer"
                  style={{ color: "var(--tint, #0a84ff)" }}
                >
                  {a.artifact_id}
                </a>{" "}
                <span style={{ color: "var(--label-tertiary)" }}>· {a.artifact_type}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {isEmpty && (
        <div
          data-testid="table-view-empty"
          style={{ color: "var(--label-tertiary)", fontSize: 13 }}
        >
          This run produced no model results or artifacts yet.
        </div>
      )}
    </div>
  );
}
