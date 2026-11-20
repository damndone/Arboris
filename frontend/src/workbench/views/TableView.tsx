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

import { ResultTableExport } from "../../workspace/result/ResultTableExport";
import { CrossRunTable } from "../../workspace/result/CrossRunTable";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useLineage } from "../../lineage/LineageContext";
import { useForest } from "../ForestContext";
import { useProjectRootOptional } from "../ProjectRootContext";
import { artifactDownloadUrl, fetchArtifactJson, fetchRunArtifacts, fetchRunDetail } from "../../api";
import type { ArtifactGroup, ArtifactItem, ModelResult, RunDetail } from "../../api";
import { DEFAULT_SIGNIFICANCE_LEVELS } from "../../report/RegressionTable";
import type { SignificanceLevels } from "../../report/RegressionTable";
import { FamilyEvidence, type FamilyModelResult } from "../../report/FamilyEvidence";
import { ArmaGarchChartGallery } from "../../runResult/ArmaGarchChartGallery";
import { ARMA_GARCH_CHART_IDS, useArmaGarchCharts } from "../../runResult/useArmaGarchCharts";
import { DatasetExportPanel } from "./DatasetExportPanel";
import { StatisticalExplorationTable } from "./StatisticalExplorationTable";
import { resolveTableRunScope } from "./tableRunScope";
import { PredictionResearchEvidenceCard } from "../../runResult/PredictionResearchEvidenceCard";
import { EngineProvenanceNotice } from "../../runResult/EngineProvenanceNotice";
import { shortRunId, type StatisticalEvidencePacket, normalizeSignificanceLevels, normalizeTableOne, normalizeStatisticalEvidence, tableViewExtensions, variableLabelsForTable } from "./tableViewData";
import { TableViewEvidenceStatus, SignificanceControls, TableOnePreview, StatisticalEvidenceTable, PostEstimationResultTable, CoefficientTable, RegressionTablePreview } from "./TableViewTables";
import { FigureCard } from "./TableViewFigures";
/** Run ids look like 20260703_065622_030010_92222fe1 — the last hex segment is
 *  the unique tail, matching the run-rail's short label so the two line up. */
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
      {activeRunId && <ResultTableExport key={`${projectRoot}:${activeRunId}`} projectRoot={projectRoot} runId={activeRunId}/>}
      <CrossRunTable key={projectRoot} projectRoot={projectRoot} runIds={runIds}/>
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
  const [statisticalEvidence, setStatisticalEvidence] = useState<StatisticalEvidencePacket | null>(null);
  const [significanceLevels, setSignificanceLevels] = useState<SignificanceLevels>(
    DEFAULT_SIGNIFICANCE_LEVELS,
  );
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
    setStatisticalEvidence(null);
    setSignificanceLevels(DEFAULT_SIGNIFICANCE_LEVELS);
    Promise.all([
      fetchRunDetail(projectRoot, runId),
      fetchRunArtifacts(projectRoot, runId),
    ])
      .then(async ([d, a]) => {
        const explorationItems = a.groups
          .filter((group) => group.artifact_type === "statistical_exploration")
          .flatMap((group) => group.items);
        const statisticalEvidenceItem = a.groups
          .filter((group) => group.artifact_type === "statistical_test")
          .flatMap((group) => group.items)
          .find((item) => item.artifact_id === "statistical_tests_evidence");
        const explorationResults = (await Promise.all(
          explorationItems.map(async (item) => {
            try {
              return { item, payload: await fetchArtifactJson(projectRoot, runId, item.artifact_id) };
            } catch {
              return null;
            }
          }),
        )).filter((entry): entry is { item: ArtifactItem; payload: unknown } => entry !== null);
        const artifactEvidence = statisticalEvidenceItem
          ? await fetchArtifactJson(projectRoot, runId, statisticalEvidenceItem.artifact_id)
            .then(normalizeStatisticalEvidence)
            .catch(() => null)
          : null;
        if (cancelled) return;
        setDetail(d);
        setArtifactGroups(a.groups);
        setArtifacts(a.groups.flatMap((g) => g.items));
        setExplorations(explorationResults);
        const extensions = tableViewExtensions(d);
        setSignificanceLevels(normalizeSignificanceLevels(extensions.significance_levels));
        setStatisticalEvidence(
          normalizeStatisticalEvidence(extensions.statistical_evidence) ?? artifactEvidence,
        );
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
  const familyModels = models.filter((model) =>
    ["ordinal_logit", "multinomial_logit", "survival_cox", "quantile_regression"]
      .includes(model.model_type ?? ""),
  );
  const familyEvidenceModels = familyModels.length > 0
    ? familyModels
    : detail?.model_family_evidence && typeof detail.model_family_evidence.model_type === "string"
      ? [detail.model_family_evidence as unknown as ModelResult]
      : [];
  const extensions = tableViewExtensions(detail);
  const variableLabels = variableLabelsForTable(detail);
  const tableOne = normalizeTableOne(extensions.table_1);
  const postEstimation = detail?.post_estimation_results ?? [];
  const figures = artifacts.filter((a) => a.artifact_type === "figure");
  const loadedExplorationIds = new Set(explorations.map(({ item }) => item.artifact_id));
  const statisticalEvidenceArtifactId = artifacts.find(
    (artifact) => artifact.artifact_id === "statistical_tests_evidence",
  )?.artifact_id;
  const otherArtifacts = artifacts.filter((a) =>
    a.artifact_type !== "figure"
      // Read by post-estimation, not by people; listing it would show an
      // internal file name next to the results.
      && a.artifact_type !== "inference_kernel"
      && !loadedExplorationIds.has(a.artifact_id)
      && a.artifact_id !== statisticalEvidenceArtifactId,
  );
  const chartArtifactIds = new Set<string>(Object.values(ARMA_GARCH_CHART_IDS));
  const hasArmaGarchChartArtifacts = artifacts.some((artifact) =>
    chartArtifactIds.has(artifact.artifact_id),
  );
  const isEmpty =
    !loading &&
    !error &&
    models.length === 0 &&
    tableOne.length === 0 &&
    statisticalEvidence === null &&
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

      <PredictionResearchEvidenceCard evidence={detail?.prediction_evidence} />

      {loading && (
        <div data-testid="table-view-loading" style={{ color: "var(--label-secondary)" }}>
          Loading results…
        </div>
      )}

      {error && (
        <div data-testid="table-view-error" style={{ color: "var(--red)" }}>
          Failed to load results: {error}
        </div>
      )}

      {!loading && !error && detail && models.length > 1 && (
        <section data-testid="table-view-regression">
          <SignificanceControls
            levels={significanceLevels}
            onChange={(marker, value) => {
              setSignificanceLevels((current) => ({ ...current, [marker]: value }));
            }}
          />
          <RegressionTablePreview
            models={models}
            significanceLevels={significanceLevels}
            variableLabels={variableLabels}
          />
        </section>
      )}

      {!loading && !error && models.map(model => <EngineProvenanceNotice key={`engine:${model.model_id}`} modelId={model.model_id} value={model.engine_provenance}/>)}

      {!loading && !error && models.length === 1 && (
        <section data-testid="table-view-coefficients">
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>Coefficients</h3>
          {models.map((m) => (
            <CoefficientTable key={m.model_id} model={m} termLabels={variableLabels} />
          ))}
        </section>
      )}

      {!loading && !error && tableOne.length > 0 && (
        <TableOnePreview rows={tableOne} />
      )}

      {!loading && !error && statisticalEvidence && (
        <StatisticalEvidenceTable packet={statisticalEvidence} />
      )}

      {!loading && !error && familyEvidenceModels.length > 0 && (
        <FamilyEvidence
          modelResults={familyEvidenceModels as unknown as FamilyModelResult[]}
        />
      )}

      {!loading && !error && detail && (models.length > 0 || tableOne.length > 0 || statisticalEvidence !== null) && (
        <TableViewEvidenceStatus
          detail={detail}
          tableOne={tableOne}
          statisticalEvidence={statisticalEvidence}
        />
      )}

      {!loading && !error && postEstimation.length > 0 && (
        <section data-testid="table-view-post-estimation" style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 14, margin: "0 0 8px", color: "var(--label)" }}>
            Post-estimation
          </h3>
          {postEstimation.map((entry) => (
            <PostEstimationResultTable key={entry.artifact_id} entry={entry} />
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

      {!loading && !error && detail && projectRoot && (
        <DatasetExportPanel projectRoot={projectRoot} runId={runId} />
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
                  style={{ color: "var(--tint)" }}
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
