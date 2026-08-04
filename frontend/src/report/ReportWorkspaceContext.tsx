import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useForest } from "../workbench/ForestContext";
import { useWorkbenchOptional } from "../workbench/WorkbenchStateProvider";
import { REPORT_REVIEW_TAB_ID } from "../workbench/state/tabsSchema";
import {
  buildFactTable,
  buildFigureFacts,
  buildPostEstimationFacts,
  buildTimeSeriesFacts,
  type CitableFact,
} from "./factTable";
import {
  displayEvidenceLabel,
  reportCapabilityManifestForFacts,
  reportCapabilitiesForFacts,
} from "./reportEvidence";
import {
  DEFAULT_REPORT_INSTRUCTION,
  exportReport as exportReportRequest,
  exportResultTable as exportResultTableRequest,
  fetchAiReports,
  generateReport as generateReportRequest,
  saveAiReport,
  type ReportFigure,
} from "./reportClient";
import {
  defaultExcludedFigureIds,
  includedReportFacts,
  includedReportFigures,
} from "./reportSelection";
import {
  deleteReportRecord,
  loadReportHistory,
  makeRecordId,
  saveReportRecord,
  type ReportRecord,
} from "./reportHistory";
import {
  createReportRevision,
  editReportRevision,
} from "./reportDocument";
import {
  fetchArtifactJson,
  fetchRunArtifacts,
  fetchRunDetail,
} from "../api";
import type { ModelResult, PostEstimationResult, PredictionResearchEvidence } from "../api";
import { fetchFigureAiContext } from "../workbench/views/figureAi";
import { appendAiActivity, makeActivityId } from "../aiActivity/aiActivityLog";

const REPORT_TIME_SERIES_ARTIFACT_IDS = new Set([
  "ts.analysis_contract",
  "ts.data_audit",
  "ts.arma_selection",
  "ts.volatility_selection",
  "ts.final_model",
  "ts.parameters",
  "ts.final_diagnostics",
  "ts.forecast_metrics",
  "ts.next_forecast",
]);

type FactTable = ReturnType<typeof buildFactTable>;

function reportsForRun(records: ReportRecord[], runId: string | null): ReportRecord[] {
  if (!runId) return [];
  return records.filter((record) => record.scope.run_id === runId);
}

function sameStrings(left: string[] | undefined, right: string[]): boolean {
  return !!left && left.length === right.length && left.every((value, index) => value === right[index]);
}

export interface ReportGenerationEvidence {
  facts: CitableFact[];
  scope: ReportRecord["scope"];
  fingerprints: string[];
  figures: ReportFigure[];
  excludedFactIds: string[];
  excludedFigureIds: string[];
}

export interface ReportGenerationOptions {
  requestInstruction?: string;
  recordInstruction?: string;
  preserveCurrentOnError?: boolean;
  evidence?: ReportGenerationEvidence;
}

function cloneJson<T>(value: T): T {
  try {
    return JSON.parse(JSON.stringify(value)) as T;
  } catch {
    return value;
  }
}

function cloneFact(fact: CitableFact): CitableFact {
  return {
    ...fact,
    value: cloneJson(fact.value),
    ...(fact.artifact_ids ? { artifact_ids: [...fact.artifact_ids] } : {}),
    ...(fact.claim_types ? { claim_types: [...fact.claim_types] } : {}),
    ...(fact.qualifiers ? { qualifiers: cloneJson(fact.qualifiers) } : {}),
  };
}

function cloneReportFigure(figure: ReportFigure): ReportFigure {
  return cloneJson(figure);
}

function generationEvidenceFromRecord(record: ReportRecord): ReportGenerationEvidence {
  const source = record.revision?.source;
  const facts = source?.facts ?? record.facts;
  const scope = source?.scope ?? record.scope;
  const figures = source?.figures ?? record.figures ?? [];
  return {
    facts: facts.map((fact) => cloneFact(fact as CitableFact)),
    scope: {
      run_id: scope.run_id,
      node_count: scope.node_count,
      node_keys: Array.isArray(scope.node_keys) ? [...scope.node_keys] : [],
    },
    fingerprints: [...(source?.context_fingerprints ?? record.context_fingerprints ?? [])],
    figures: figures.map((figure) => cloneReportFigure(figure as ReportFigure)),
    excludedFactIds: [...(source?.excluded_fact_ids ?? record.excluded_fact_ids)],
    excludedFigureIds: [...(source?.excluded_figure_ids ?? record.excluded_figure_ids ?? [])],
  };
}

function canonicalJson(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "undefined") return "undefined";
  if (typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`).join(",")}}`;
}

function hashText(value: string): string {
  let hash = 2_166_136_261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16_777_619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function reportEvidenceFingerprint(input: {
  scope: ReportRecord["scope"];
  facts: CitableFact[];
  figures: ReportFigure[];
  modelResults: ModelResult[];
  timeSeriesArtifacts: Record<string, unknown>;
  postEstimation: PostEstimationResult[];
}): string {
  return `report-evidence-v1:${hashText(canonicalJson(input))}`;
}

function contextValue(value: unknown): string {
  const text = typeof value === "string" ? value : canonicalJson(value);
  return text.length > 100 ? `${text.slice(0, 99)}…` : text;
}

function contextDetailsForFacts(facts: CitableFact[]): string[] {
  const preview = facts.slice(0, 8).map(
    (fact) => `${fact.id} · ${displayEvidenceLabel(fact)} = ${contextValue(fact.value)}`,
  );
  if (facts.length > preview.length) preview.push(`… ${facts.length - preview.length} more facts`);
  return preview;
}

export interface ReportWorkspaceContextValue {
  projectRoot?: string;
  activeRunId: string | null;
  table: FactTable | null;
  current: ReportRecord | null;
  history: ReportRecord[];
  reportFigures: ReportFigure[];
  allFacts: CitableFact[];
  includedFacts: CitableFact[];
  includedFigures: ReportFigure[];
  currentIncludedFacts: CitableFact[];
  currentIncludedFigures: ReportFigure[];
  currentFactsById: ReadonlyMap<string, CitableFact>;
  excludedFactIds: readonly string[];
  excludedFigureIds: readonly string[];
  instruction: string;
  revisionInstruction: string;
  editing: boolean;
  editorText: string;
  error: string | null;
  reportLoadError: string | null;
  generating: boolean;
  generatingRunId: string | null;
  exporting: boolean;
  resultTableExporting: boolean;
  figureContextLoading: boolean;
  figureInventoryError: string | null;
  predictionEvidence: PredictionResearchEvidence | null;
  postEstimation: PostEstimationResult[];
  modelResults: ModelResult[];
  familyEvidenceArtifacts: Record<string, unknown>;
  reportContextLines: string[];
  reportContextDetails: string[];
  reportContextUsedTokens: number;
  currentContextLines: string[];
  currentContextDetails: string[];
  currentContextUsedTokens: number;
  currentIsStale: boolean;
  currentQualityStatus: ReportRecord["validation_status"] | undefined;
  reportExportAllowed: boolean;
  onInstructionChange: (value: string) => void;
  onRevisionInstructionChange: (value: string) => void;
  onEditorTextChange: (value: string) => void;
  toggleFact: (factId: string) => void;
  toggleFigure: (artifactId: string) => void;
  useRecommendedFigures: () => void;
  includeAllFigures: () => void;
  jumpToNode: (nodeKey: string) => void;
  generateReport: (options?: ReportGenerationOptions) => Promise<boolean>;
  reviseReport: () => Promise<void>;
  exportReport: (format: "html" | "docx" | "tex" | "pdf-print") => Promise<void>;
  exportResultTable: () => Promise<void>;
  beginEditing: () => void;
  cancelEditing: () => void;
  resetEditor: () => void;
  saveRevision: () => Promise<void>;
  startNewReport: () => void;
  openReport: (record: ReportRecord) => void;
  deleteReport: (record: ReportRecord) => void;
}

const ReportWorkspaceContext = createContext<ReportWorkspaceContextValue | null>(null);

export function useReportWorkspace(): ReportWorkspaceContextValue {
  const value = useContext(ReportWorkspaceContext);
  if (!value) {
    throw new Error("useReportWorkspace must be used inside ReportWorkspaceProvider");
  }
  return value;
}

export function useReportWorkspaceOptional(): ReportWorkspaceContextValue | null {
  return useContext(ReportWorkspaceContext);
}

export function ReportWorkspaceProvider({
  projectRoot,
  children,
}: {
  projectRoot?: string;
  children: ReactNode;
}) {
  const forest = useForest();
  const wb = useWorkbenchOptional();
  const activeRunId = forest?.activeRunId ?? null;
  const reportWorkspaceRequested = wb === null
    || wb.state.view === undefined
    || wb.state.view === "report"
    || wb.state.activeTabId === REPORT_REVIEW_TAB_ID;
  const activeRunIdRef = useRef(activeRunId);
  activeRunIdRef.current = activeRunId;
  const projectRootRef = useRef(projectRoot);
  projectRootRef.current = projectRoot;
  const reportWorkspaceEverRequestedRef = useRef(false);
  if (reportWorkspaceRequested) reportWorkspaceEverRequestedRef.current = true;
  const reportInteractionRef = useRef(0);
  const markReportInteraction = () => {
    reportInteractionRef.current += 1;
  };
  const historyRoot = projectRoot ?? "unknown-project";

  const [instruction, setInstruction] = useState("");
  const [revisionInstruction, setRevisionInstruction] = useState("");
  const [current, setCurrent] = useState<ReportRecord | null>(null);
  const [editing, setEditing] = useState(false);
  const [editorText, setEditorText] = useState("");
  const [history, setHistory] = useState<ReportRecord[]>([]);
  const [excludedIds, setExcludedIds] = useState<Set<string>>(new Set());
  const [excludedFigureIds, setExcludedFigureIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [reportLoadError, setReportLoadError] = useState<string | null>(null);
  const [generatingRunId, setGeneratingRunId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [resultTableExporting, setResultTableExporting] = useState(false);
  const [reportFigures, setReportFigures] = useState<ReportFigure[]>([]);
  const [timeSeriesArtifacts, setTimeSeriesArtifacts] = useState<Record<string, unknown>>({});
  const [figureContextLoading, setFigureContextLoading] = useState(false);
  const [figureInventoryError, setFigureInventoryError] = useState<string | null>(null);
  const [postEstimation, setPostEstimation] = useState<PostEstimationResult[]>([]);
  const [predictionEvidence, setPredictionEvidence] = useState<PredictionResearchEvidence | null>(null);
  const [modelResults, setModelResults] = useState<ModelResult[]>([]);
  const [familyEvidenceArtifacts, setFamilyEvidenceArtifacts] = useState<Record<string, unknown>>({});

  useEffect(() => {
    if (!reportWorkspaceRequested) return undefined;
    const runId = activeRunId;
    if (!runId || !projectRoot) {
      setPostEstimation([]);
      setPredictionEvidence(null);
      setModelResults([]);
      return;
    }
    let cancelled = false;
    void fetchRunDetail(projectRoot, runId)
      .then((detail) => {
        if (!cancelled) {
          setPostEstimation(detail.post_estimation_results ?? []);
          setPredictionEvidence(detail.prediction_evidence ?? null);
          setModelResults(detail.model_results ?? []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPostEstimation([]);
          setPredictionEvidence(null);
          setModelResults([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeRunId, projectRoot, reportWorkspaceRequested]);

  useEffect(() => {
    setEditing(false);
    setEditorText(current?.text ?? "");
    setRevisionInstruction("");
    if (current) setExcludedIds(new Set(current.excluded_fact_ids));
  }, [current?.id]);

  useEffect(() => {
    setExcludedFigureIds(
      current
        ? new Set(current.excluded_figure_ids ?? [])
        : new Set(defaultExcludedFigureIds(reportFigures)),
    );
  }, [activeRunId, current?.id, reportFigures]);

  useEffect(() => {
    if (!reportWorkspaceRequested) return undefined;
    const runId = activeRunId;
    if (!runId || !projectRoot) {
      setFamilyEvidenceArtifacts({});
      return;
    }
    let cancelled = false;
    setFamilyEvidenceArtifacts({});
    const familyArtifactIds = new Set([
      "diagnostics_ordinal_logit_1",
      "diagnostics_multinomial_logit_1",
      "survival_evidence",
    ]);
    void fetchRunArtifacts(projectRoot, runId)
      .then(async (response) => {
        const items = response.groups
          .flatMap((group) => group.items)
          .filter((item) => familyArtifactIds.has(item.artifact_id));
        const loaded = await Promise.all(items.map(async (item) => {
          try {
            return [item.artifact_id, await fetchArtifactJson(projectRoot, runId, item.artifact_id)] as const;
          } catch {
            return null;
          }
        }));
        if (!cancelled) {
          setFamilyEvidenceArtifacts(
            Object.fromEntries(loaded.filter((entry): entry is readonly [string, unknown] => entry !== null)),
          );
        }
      })
      .catch(() => {
        if (!cancelled) setFamilyEvidenceArtifacts({});
      });
    return () => {
      cancelled = true;
    };
  }, [activeRunId, projectRoot, reportWorkspaceRequested]);

  useEffect(() => {
    if (!reportWorkspaceRequested) return;
    const stored = loadReportHistory(historyRoot);
    const scoped = reportsForRun(stored, activeRunId);
    setHistory(scoped);
    setCurrent(scoped[0] ?? null);
  }, [activeRunId, historyRoot, reportWorkspaceRequested]);

  useEffect(() => {
    if (!reportWorkspaceRequested) return undefined;
    const runId = activeRunId;
    if (!projectRoot || !runId) {
      setReportLoadError(null);
      return;
    }
    let cancelled = false;
    const interactionAtRequest = reportInteractionRef.current;
    setReportLoadError(null);
    void fetchAiReports({ projectRoot, runId })
      .then((records) => {
        if (
          cancelled
          || reportInteractionRef.current !== interactionAtRequest
          || activeRunIdRef.current !== runId
          || projectRootRef.current !== projectRoot
          || records.length === 0
        ) return;
        const durable = reportsForRun(records as unknown as ReportRecord[], runId);
        setHistory(durable);
        setCurrent(durable[0] ?? null);
      })
      .catch((err) => {
        if (cancelled || activeRunIdRef.current !== runId || projectRootRef.current !== projectRoot) return;
        const message = err instanceof Error ? err.message : "报告暂时无法加载";
        setReportLoadError(`报告加载失败：${message}`);
      });
    return () => {
      // A floating review remains mounted after the user leaves Report. Let a
      // request that already started finish, while the run/root guards above
      // prevent stale data from crossing project or run boundaries.
      if (!reportWorkspaceEverRequestedRef.current) cancelled = true;
    };
  }, [activeRunId, projectRoot, reportWorkspaceRequested]);

  useEffect(() => {
    if (!reportWorkspaceRequested) return undefined;
    const runId = activeRunId;
    if (!runId || !projectRoot) {
      setReportFigures([]);
      setTimeSeriesArtifacts({});
      setFigureContextLoading(false);
      setFigureInventoryError(null);
      return;
    }
    let cancelled = false;
    setFigureContextLoading(true);
    setFigureInventoryError(null);
    void fetchRunArtifacts(projectRoot, runId)
      .then(async (response) => {
        const allItems = response.groups.flatMap((group) => group.items);
        const items = allItems.filter((item) => item.artifact_type === "figure");
        const timeSeriesItems = allItems.filter((item) => REPORT_TIME_SERIES_ARTIFACT_IDS.has(item.artifact_id));
        const [resolved, resolvedTimeSeries] = await Promise.all([
          Promise.all(items.map(async (item) => {
            try {
              const context = await fetchFigureAiContext(projectRoot, runId, item.artifact_id);
              return {
                artifact_id: item.artifact_id,
                chart_type: context.figure.chart_type,
                path: context.figure.path,
                source: context.source,
              } satisfies ReportFigure;
            } catch {
              return {
                artifact_id: item.artifact_id,
                chart_type: item.artifact_id,
                source: null,
              } satisfies ReportFigure;
            }
          })),
          Promise.all(timeSeriesItems.map(async (item) => {
            try {
              const value = await fetchArtifactJson(projectRoot, runId, item.artifact_id);
              return [item.artifact_id, value] as const;
            } catch {
              return null;
            }
          })),
        ]);
        if (!cancelled) {
          setReportFigures(resolved);
          setTimeSeriesArtifacts(Object.fromEntries(resolvedTimeSeries.filter((item) => item !== null)));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setReportFigures([]);
          setTimeSeriesArtifacts({});
          setFigureInventoryError("Unable to load the run figure inventory; report generation is disabled.");
        }
      })
      .finally(() => {
        if (!cancelled) setFigureContextLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeRunId, projectRoot, reportWorkspaceRequested]);

  const table = useMemo<FactTable | null>(() => {
    if (!forest || !forest.activeRunId) return null;
    return buildFactTable(forest.forest, forest.activeRunId);
  }, [forest]);

  const figureFacts = useMemo(
    () => buildFigureFacts(reportFigures, table?.facts.length ?? 0),
    [reportFigures, table?.facts.length],
  );
  const timeSeriesProvenance = useMemo(() => {
    const modelNode = forest?.forest.nodes.find(
      (node) =>
        (node.runs ?? []).includes(forest.activeRunId ?? "")
        && node.opType === "time_series.arma_garch"
        && node.kind === "model",
    );
    return modelNode
      ? { nodeKey: modelNode.nodeKey, nodeLabel: modelNode.title }
      : { nodeKey: "model:arma_garch_1", nodeLabel: "ARMA-GARCH" };
  }, [forest]);
  const timeSeriesFacts = useMemo(
    () => buildTimeSeriesFacts(
      timeSeriesArtifacts,
      (table?.facts.length ?? 0) + figureFacts.length,
      timeSeriesProvenance,
    ),
    [figureFacts.length, table?.facts.length, timeSeriesArtifacts, timeSeriesProvenance],
  );
  const postEstimationFacts = useMemo(
    () => buildPostEstimationFacts(
      postEstimation,
      (table?.facts.length ?? 0) + figureFacts.length + timeSeriesFacts.length,
    ),
    [figureFacts.length, postEstimation, table?.facts.length, timeSeriesFacts.length],
  );
  const allFacts = useMemo(
    () => (table ? [...table.facts, ...figureFacts, ...timeSeriesFacts, ...postEstimationFacts] : []),
    [figureFacts, postEstimationFacts, table, timeSeriesFacts],
  );
  const includedFigures = includedReportFigures(reportFigures, [...excludedFigureIds]);
  const includedFacts = includedReportFacts(allFacts, [...excludedIds], [...excludedFigureIds]);
  const resultFamilies = [...new Set(modelResults.map((result) => result.model_type?.trim() || "unknown model"))];
  const activeEvidenceFingerprint = table
    ? reportEvidenceFingerprint({
        scope: table.scope,
        facts: allFacts,
        figures: reportFigures,
        modelResults,
        timeSeriesArtifacts,
        postEstimation,
      })
    : null;
  const activeReportFingerprints = table
    ? [...table.fingerprints, ...(activeEvidenceFingerprint ? [activeEvidenceFingerprint] : [])]
    : [];
  const reportContextLines = table
    ? [
        `Run ${table.scope.run_id} · ${table.scope.node_count} lineage nodes`,
        `Evidence inventory: ${allFacts.length} citable facts in provenance`,
        `Next writer packet: ${includedFacts.length} of ${allFacts.length} facts selected`,
        `Figure inventory: ${reportFigures.length} figure artifact${reportFigures.length === 1 ? "" : "s"} in provenance`,
        `Next writer packet: ${includedFigures.length} of ${reportFigures.length} figures selected`,
        `${resultFamilies.length} result famil${resultFamilies.length === 1 ? "y" : "ies"}: ${resultFamilies.join(", ") || "none"}`,
        `Evidence fingerprint: ${activeReportFingerprints.join(" · ").slice(0, 140) || "not available"}`,
      ]
    : [];
  const reportContextDetails = contextDetailsForFacts(includedFacts);
  const reportContextUsedTokens = table
    ? Math.max(
        1,
        Math.ceil(JSON.stringify({
          scope: table.scope,
          facts: includedFacts,
          figures: includedFigures,
          instruction,
        }).length / 4),
      )
    : 1;
  const currentIsStale = Boolean(
    current
    && table
    && (
      current.scope.run_id !== table.scope.run_id
      || (
        current.context_fingerprints
        && !sameStrings(current.context_fingerprints, activeReportFingerprints)
      )
    ),
  );
  const currentEvidence = current ? generationEvidenceFromRecord(current) : null;
  const currentIncludedFigures = currentEvidence
    ? includedReportFigures(currentEvidence.figures, currentEvidence.excludedFigureIds)
    : includedFigures;
  const currentIncludedFacts = currentEvidence
    ? includedReportFacts(currentEvidence.facts, currentEvidence.excludedFactIds, currentEvidence.excludedFigureIds)
    : includedFacts;
  const currentContextDetails = contextDetailsForFacts(currentIncludedFacts);
  const currentContextLines = currentEvidence
    ? [
        `Run ${currentEvidence.scope.run_id} · ${currentEvidence.scope.node_count} lineage nodes`,
        `Evidence inventory: ${currentEvidence.facts.length} citable facts in provenance`,
        `Report sent packet: ${currentIncludedFacts.length} of ${currentEvidence.facts.length} facts sent`,
        `Figure inventory: ${currentEvidence.figures.length} figure artifact${currentEvidence.figures.length === 1 ? "" : "s"} in provenance`,
        `Report sent packet: ${currentIncludedFigures.length} of ${currentEvidence.figures.length} figures sent`,
        `${resultFamilies.length} result famil${resultFamilies.length === 1 ? "y" : "ies"}: ${resultFamilies.join(", ") || "none"}`,
        `Evidence fingerprint: ${currentEvidence.fingerprints.join(" · ").slice(0, 140) || "not available"}`,
      ]
    : reportContextLines;
  const currentContextUsedTokens = current
    ? Math.max(1, Math.ceil(JSON.stringify({ facts: currentIncludedFacts, draft: current.text }).length / 4))
    : reportContextUsedTokens;
  const currentQualityStatus = current?.validation_status ?? current?.report_quality?.status;
  const reportExportAllowed = !currentIsStale
    && (!currentQualityStatus || currentQualityStatus === "exportable");

  const jumpToNode = (nodeKey: string) => {
    if (!wb) return;
    wb.dispatch.setView("graph");
    wb.dispatch.selectByCanvasClick(nodeKey);
  };
  const toggleFact = (factId: string) => {
    markReportInteraction();
    setExcludedIds((previous) => {
      const next = new Set(previous);
      if (next.has(factId)) next.delete(factId);
      else next.add(factId);
      return next;
    });
  };
  const toggleFigure = (artifactId: string) => {
    markReportInteraction();
    setExcludedFigureIds((previous) => {
      const next = new Set(previous);
      if (next.has(artifactId)) next.delete(artifactId);
      else next.add(artifactId);
      return next;
    });
  };
  const useRecommendedFigures = () => {
    markReportInteraction();
    setExcludedFigureIds(new Set(defaultExcludedFigureIds(reportFigures)));
  };
  const includeAllFigures = () => {
    markReportInteraction();
    setExcludedFigureIds(new Set());
  };

  async function handleGenerate(options: ReportGenerationOptions = {}): Promise<boolean> {
    if (!table) return false;
    const evidence = options.evidence ?? {
      facts: allFacts.map(cloneFact),
      scope: {
        run_id: table.scope.run_id,
        node_count: table.scope.node_count,
        node_keys: [...table.scope.node_keys],
      },
      fingerprints: activeReportFingerprints,
      figures: reportFigures.map(cloneReportFigure),
      excludedFactIds: [...excludedIds],
      excludedFigureIds: [...excludedFigureIds],
    } satisfies ReportGenerationEvidence;
    const includedEvidenceFigures = includedReportFigures(evidence.figures, evidence.excludedFigureIds);
    const includedEvidenceFacts = includedReportFacts(
      evidence.facts,
      evidence.excludedFactIds,
      evidence.excludedFigureIds,
    );
    const requiredCapabilities = reportCapabilitiesForFacts(includedEvidenceFacts);
    const capabilityManifest = reportCapabilityManifestForFacts(includedEvidenceFacts);
    const runId = evidence.scope.run_id;
    const normalizedInstruction = options.requestInstruction?.trim()
      || instruction.trim()
      || DEFAULT_REPORT_INSTRUCTION;
    const recordInstruction = options.recordInstruction?.trim() || normalizedInstruction;
    markReportInteraction();
    setGeneratingRunId(runId);
    setError(null);
    try {
      const response = await generateReportRequest({
        facts: includedEvidenceFacts,
        scope: evidence.scope,
        fingerprints: evidence.fingerprints,
        figures: includedEvidenceFigures,
        instruction: normalizedInstruction,
        reportStandard: "journal_full_v1",
        requiredCapabilities,
        capabilityManifest,
        excludedFactIds: evidence.excludedFactIds,
      });
      const baseRecord: ReportRecord = {
        id: makeRecordId(),
        generatedAt: new Date().toISOString(),
        model: response.model,
        instruction: recordInstruction,
        text: response.text,
        generatedText: response.text,
        scope: evidence.scope,
        context_fingerprints: evidence.fingerprints,
        facts: evidence.facts,
        excluded_fact_ids: evidence.excludedFactIds,
        figures: evidence.figures,
        excluded_figure_ids: evidence.excludedFigureIds,
        report_standard: "journal_full_v1",
        required_capabilities: requiredCapabilities,
        capability_manifest: capabilityManifest,
        report_quality: response.report_quality,
      };
      const isAgentRevision = Boolean(options.preserveCurrentOnError && current && options.evidence);
      const record: ReportRecord = isAgentRevision && current
        ? {
            ...current,
            id: baseRecord.id,
            generatedAt: baseRecord.generatedAt,
            model: response.model ?? current.model,
            instruction: recordInstruction,
            text: response.text,
            generatedText: current.generatedText ?? current.text,
            scope: evidence.scope,
            context_fingerprints: evidence.fingerprints,
            facts: evidence.facts,
            excluded_fact_ids: evidence.excludedFactIds,
            figures: evidence.figures,
            excluded_figure_ids: evidence.excludedFigureIds,
            report_quality: response.report_quality ?? current.report_quality,
            revision: editReportRevision(
              current.revision ?? createReportRevision(current),
              response.text,
            ),
          }
        : {
            ...baseRecord,
            revision: createReportRevision(baseRecord),
          };
      let persistedRecord = record;
      if (projectRoot) {
        const saved = await saveAiReport({ projectRoot, runId, record });
        persistedRecord = { ...record, ...(saved?.record ?? {}) };
      }
      if (activeRunIdRef.current === runId) {
        setCurrent(persistedRecord);
        setHistory(reportsForRun(saveReportRecord(historyRoot, persistedRecord), runId));
      } else {
        saveReportRecord(historyRoot, persistedRecord);
      }
      appendAiActivity(historyRoot, {
        kind: "report_generate",
        id: makeActivityId(),
        at: persistedRecord.generatedAt,
        run_id: runId,
        instruction: recordInstruction,
        model: response.model,
        fact_count: includedEvidenceFacts.length,
        excluded_count: evidence.excludedFactIds.length,
        report_record_id: persistedRecord.id,
        status: "completed",
      });
      return true;
    } catch (err) {
      const failure = err instanceof Error ? err.message : "Report generation failed";
      appendAiActivity(historyRoot, {
        kind: "report_generate",
        id: makeActivityId(),
        at: new Date().toISOString(),
        run_id: runId,
        instruction: recordInstruction,
        fact_count: includedEvidenceFacts.length,
        excluded_count: evidence.excludedFactIds.length,
        status: "error",
        error: failure.length <= 500 ? failure : `${failure.slice(0, 499)}…`,
      });
      if (activeRunIdRef.current === runId && !options.preserveCurrentOnError) {
        setCurrent(null);
        setError(failure);
      } else if (activeRunIdRef.current === runId) {
        setError(failure);
      }
      return false;
    } finally {
      setGeneratingRunId((currentRunId) => currentRunId === runId ? null : currentRunId);
    }
  }

  async function handleRevise(): Promise<void> {
    if (!current || revisionInstruction.trim() === "" || !table) return;
    if (currentIsStale || !currentEvidence || currentEvidence.scope.run_id !== table.scope.run_id) {
      setError("This report is stale because its source evidence changed; start a new report before revising it.");
      return;
    }
    const draft = current.text.length > 24_000
      ? `${current.text.slice(0, 24_000)}\n\n[Draft truncated for revision context.]`
      : current.text;
    const succeeded = await handleGenerate({
      requestInstruction: [
        "Revise the existing report draft according to the user's instruction.",
        "Keep every numeric claim grounded in the supplied fact table, preserve valid citation and figure markers, and return the complete revised report.",
        `User instruction:\n${revisionInstruction.trim()}`,
        `Existing draft:\n---\n${draft}\n---`,
      ].join("\n\n"),
      recordInstruction: revisionInstruction,
      preserveCurrentOnError: true,
      evidence: currentEvidence,
    });
    if (succeeded) setRevisionInstruction("");
  }

  async function handleExport(format: "html" | "docx" | "tex" | "pdf-print"): Promise<void> {
    if (!current || !projectRoot) return;
    if (!reportExportAllowed) {
      setError("This report revision is stale or has unresolved quality issues; fix it before exporting.");
      return;
    }
    setExporting(true);
    setError(null);
    try {
      const blob = await exportReportRequest({
        projectRoot,
        runId: current.scope.run_id,
        reportId: current.id,
        format,
        markdown: current.text,
        figures: current.figures ?? reportFigures,
      });
      const filename = format === "tex"
        ? `workbench-report-${current.scope.run_id}.zip`
        : format === "pdf-print"
          ? `workbench-report-${current.scope.run_id}-print.html`
          : `workbench-report-${current.scope.run_id}.${format}`;
      downloadBlob(blob, filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report export failed");
    } finally {
      setExporting(false);
    }
  }

  async function handleResultTableExport(): Promise<void> {
    if (!current || !projectRoot) return;
    setResultTableExporting(true);
    setError(null);
    try {
      const blob = await exportResultTableRequest({
        projectRoot,
        runId: current.scope.run_id,
        sections: [],
      });
      downloadBlob(blob, `workbench-result-table-${current.scope.run_id}.xlsx`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Result table export failed");
    } finally {
      setResultTableExporting(false);
    }
  }

  function beginEditing(): void {
    if (!current) return;
    markReportInteraction();
    setEditorText(current.revision?.markdown ?? current.text);
    setError(null);
    setEditing(true);
  }

  function resetEditor(): void {
    setEditorText(current?.generatedText ?? current?.text ?? "");
  }

  function startNewReport(): void {
    markReportInteraction();
    setEditing(false);
    setExcludedIds(new Set());
    setExcludedFigureIds(new Set(defaultExcludedFigureIds(reportFigures)));
    setRevisionInstruction("");
    setCurrent(null);
  }

  async function saveRevision(): Promise<void> {
    if (!current) return;
    setError(null);
    try {
      const baseRevision = current.revision ?? createReportRevision(current);
      const revision = editReportRevision(baseRevision, editorText);
      const record: ReportRecord = {
        ...current,
        id: makeRecordId(),
        generatedAt: new Date().toISOString(),
        text: revision.markdown,
        revision,
      };
      let persistedRecord = record;
      if (projectRoot) {
        const saved = await saveAiReport({ projectRoot, runId: record.scope.run_id, record });
        persistedRecord = { ...record, ...(saved?.record ?? {}) };
      }
      setCurrent(persistedRecord);
      setHistory(reportsForRun(saveReportRecord(historyRoot, persistedRecord), persistedRecord.scope.run_id));
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report revision could not be saved");
    }
  }

  const currentFactsById = new Map((current?.facts ?? allFacts).map((fact) => [fact.id, fact]));
  const value: ReportWorkspaceContextValue = {
    projectRoot,
    activeRunId,
    table,
    current,
    history,
    reportFigures,
    allFacts,
    includedFacts,
    includedFigures,
    currentIncludedFacts,
    currentIncludedFigures,
    currentFactsById,
    excludedFactIds: [...excludedIds],
    excludedFigureIds: [...excludedFigureIds],
    instruction,
    revisionInstruction,
    editing,
    editorText,
    error,
    reportLoadError,
    generating: generatingRunId === activeRunId,
    generatingRunId,
    exporting,
    resultTableExporting,
    figureContextLoading,
    figureInventoryError,
    predictionEvidence,
    postEstimation,
    modelResults,
    familyEvidenceArtifacts,
    reportContextLines,
    reportContextDetails,
    reportContextUsedTokens,
    currentContextLines,
    currentContextDetails,
    currentContextUsedTokens,
    currentIsStale,
    currentQualityStatus,
    reportExportAllowed,
    onInstructionChange: (value) => {
      markReportInteraction();
      setInstruction(value);
    },
    onRevisionInstructionChange: (value) => {
      markReportInteraction();
      setRevisionInstruction(value);
    },
    onEditorTextChange: setEditorText,
    toggleFact,
    toggleFigure,
    useRecommendedFigures,
    includeAllFigures,
    jumpToNode,
    generateReport: handleGenerate,
    reviseReport: handleRevise,
    exportReport: handleExport,
    exportResultTable: handleResultTableExport,
    beginEditing,
    cancelEditing: () => setEditing(false),
    resetEditor,
    saveRevision,
    startNewReport,
    openReport: (record) => {
      markReportInteraction();
      setCurrent(record);
    },
    deleteReport: (record) => {
      markReportInteraction();
      setHistory(reportsForRun(deleteReportRecord(historyRoot, record.id), activeRunId));
      if (current?.id === record.id) startNewReport();
    },
  };

  return <ReportWorkspaceContext.Provider value={value}>{children}</ReportWorkspaceContext.Provider>;
}

function downloadBlob(blob: Blob, filename: string): void {
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
