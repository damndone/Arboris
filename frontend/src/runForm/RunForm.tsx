import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  fetchArmaGarchTransformPreflight,
  previewFile,
  runWorkflow,
  waitForRunTerminal,
  type FilePreview,
  type ArmaGarchTransformPreflight,
  type RunResponse,
} from "../api";
import { RunResultView } from "../runResult";
import { useCapabilities } from "../capabilities/useCapabilities";
import { validatePanelPrediction } from "../App";
import { ModelTypeSelect } from "./ModelTypeSelect";
import { ImputationControls } from "./ImputationControls";
import { PanelControls } from "./PanelControls";
import { LmmControls, type LmmControlValue } from "./LmmControls";
import { PredictionControls } from "./PredictionControls";
import { IVControls, type IVRoleValue } from "./IVControls";
import { DIDControls, type DIDRoleValue } from "./DIDControls";
import { CSControls, type CSValue } from "./CSControls";
import { DCDHControls, type DCDHValue } from "./DCDHControls";
import { FocalSelect } from "./FocalSelect";
import {
  ArmaGarchControls,
  armaGarchValidationErrors,
  buildArmaGarchModelOptions,
  createDefaultArmaGarchValue,
  type ArmaGarchControlValue,
} from "./ArmaGarchControls";
import {
  V186ModelControls,
  isV186ModelType,
  normalizeV186ModelOptions,
  type V186ModelOptionsByType,
} from "./V186ModelControls";

type RequestState = "idle" | "working";

function parseColumns(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "");
}

export type RunFormProps = {
  projectRoot: string;
  setError: (msg: string | null) => void;
  setActivity: (text: string) => void;
  activity: string;
  requestState: RequestState;
  setRequestState: (state: RequestState) => void;
  onRan?: (r: RunResponse) => void;
};

export function RunForm(props: RunFormProps) {
  const {
    projectRoot,
    setError,
    setActivity,
    activity,
    requestState,
    setRequestState,
    onRan,
  } = props;
  const navigate = useNavigate();
  const { data: capabilities } = useCapabilities();

  const [mode, setMode] = useState("auto");
  const [modelType, setModelType] = useState("auto");
  // V1.5.4.1: imputation method key (null = not requested). Driven by the
  // same `capabilities` manifest as ModelTypeSelect.
  const [imputationMethod, setImputationMethod] = useState<string | null>(null);
  // V1.5.4.2: panel entity/time/covariance overrides + optional prediction.
  const [entityCol, setEntityCol] = useState("");
  const [timeCol, setTimeCol] = useState("");
  const [covariance, setCovariance] = useState("");
  const [lmmValue, setLmmValue] = useState<LmmControlValue>({
    subject_id: "",
    time: "",
    group: "",
    fit_method: "reml",
    random_slope: true,
  });
  const [armaGarchValue, setArmaGarchValue] = useState<ArmaGarchControlValue>(
    createDefaultArmaGarchValue,
  );
  const [armaGarchPreflight, setArmaGarchPreflight] =
    useState<ArmaGarchTransformPreflight | null>(null);
  const [armaGarchPreflightError, setArmaGarchPreflightError] =
    useState<string | null>(null);
  const [v186ModelOptionsByType, setV186ModelOptionsByType] =
    useState<V186ModelOptionsByType>({});
  // V1.5.4.4: IV role assignment (endog / instruments) over the X selection.
  const [ivRole, setIvRole] = useState<IVRoleValue>({
    endog: [],
    instruments: [],
  });
  // V1.5.5: DID role assignment (mode + entity/time/cohort/treat/post/status).
  const [didRole, setDidRole] = useState<DIDRoleValue>({
    mode: "cohort",
    entity: "",
    time: "",
    cohort: "",
    treat: "",
    post: "",
    status: "",
  });
  // V1.5.6: Callaway-Sant'Anna (cs_did) specific params. Entity/time/cohort
  // roles are shared with DID via `didRole`; these are the CS-only knobs.
  const [csValue, setCsValue] = useState<CSValue>({
    controlGroup: "never",
    estMethod: "dr",
    basePeriod: "varying",
    anticipation: 0,
    clusterVar: "",
    honestDid: false,
  });
  // V1.5.9: de Chaisemartin-D'Haultfoeuille (dcdh) self-contained roles
  // (entity/time/treatment-path), distinct from cohort-based DID roles.
  const [dcdhValue, setDcdhValue] = useState<DCDHValue>({
    entity: "",
    time: "",
    treatmentPath: "",
    clusterVar: "",
  });
  const [predictionEnabled, setPredictionEnabled] = useState(false);
  const [predictionModelType, setPredictionModelType] = useState("");
  const [predictionCvFolds, setPredictionCvFolds] = useState(5);
  const [predictionSampling, setPredictionSampling] = useState("");
  const [predictionDataStructure, setPredictionDataStructure] = useState("unknown");
  const [predictionEntityColumn, setPredictionEntityColumn] = useState("");
  const [predictionGroupColumn, setPredictionGroupColumn] = useState("");
  const [predictionTimeColumn, setPredictionTimeColumn] = useState("");
  const [predictionFinalHoldoutFraction, setPredictionFinalHoldoutFraction] = useState(0.2);
  const [predictionShuffle, setPredictionShuffle] = useState(true);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [sheetName, setSheetName] = useState<string | undefined>(undefined);
  const [transpose, setTranspose] = useState(false);
  const [y, setY] = useState("");
  const [x, setX] = useState("");
  const [xManuallySet, setXManuallySet] = useState(false);
  // v1.6.5 — user-declared focal explanatory columns (role layer). Only
  // meaningful for user-focal families; FocalSelect hides itself otherwise.
  const [focal, setFocal] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [previewState, setPreviewState] = useState<
    "idle" | "loading" | "error"
  >("idle");
  const [previewError, setPreviewError] = useState<string | null>(null);
  // V1.5.1 T1.3: live progress line under the Run button. Populated
  // from SSE step events (or a 3 s "connecting…" placeholder if no
  // event arrives — usually means we fell back to polling).
  const [progressLine, setProgressLine] = useState<string | null>(null);
  // V1.5.0.1 HF4: persist lastRun in sessionStorage so the "Open
  // Lineage" affordance and inline RunResultView survive when the
  // user navigates away (e.g. to History or to /runs/:id and back)
  // and the SubmitRoute component re-mounts. Before this, lastRun
  // lived in plain useState and was discarded on every unmount.
  const [lastRun, setLastRunState] = useState<RunResponse | null>(() => {
    try {
      const raw = sessionStorage.getItem("workbench:lastRun");
      return raw ? (JSON.parse(raw) as RunResponse) : null;
    } catch {
      return null;
    }
  });
  const setLastRun = useCallback((run: RunResponse | null) => {
    setLastRunState(run);
    try {
      if (run) {
        sessionStorage.setItem("workbench:lastRun", JSON.stringify(run));
      } else {
        sessionStorage.removeItem("workbench:lastRun");
      }
    } catch {
      // sessionStorage unavailable (private mode, quota): silently
      // degrade to in-memory only. The user just loses persistence.
    }
  }, []);

  const xColumns = useMemo(() => parseColumns(x), [x]);
  const columnNames = useMemo(
    () => preview?.columns?.map((c) => c.name) ?? [],
    [preview],
  );
  const isArmaGarch = modelType === "time_series.arma_garch";

  useEffect(() => {
    if (!isArmaGarch || !preview) return;
    const suggestedTime =
      preview.columns.find((column) => column.suggestedRole === "time")?.name
      ?? preview.columns.find((column) => column.dtype === "datetime")?.name
      ?? "";
    const suggestedValue =
      preview.columns.find(
        (column) => column.name === preview.suggestedY && column.dtype === "numeric",
      )?.name
      ?? preview.columns.find(
        (column) => column.dtype === "numeric" && column.name !== suggestedTime,
      )?.name
      ?? "";
    setArmaGarchValue((current) => {
      return {
        ...current,
        timeColumn: current.timeColumn || suggestedTime,
        valueColumn: current.valueColumn || suggestedValue,
      };
    });
    setY(armaGarchValue.valueColumn || suggestedValue);
    setX("");
  }, [isArmaGarch, preview, armaGarchValue.valueColumn]);

  useEffect(() => {
    if (
      !isArmaGarch
      || !file
      || !armaGarchValue.timeColumn
      || !armaGarchValue.valueColumn
      || !projectRoot.trim()
    ) {
      setArmaGarchPreflight(null);
      setArmaGarchPreflightError(null);
      return;
    }
    let cancelled = false;
    setArmaGarchPreflight(null);
    setArmaGarchPreflightError(null);
    fetchArmaGarchTransformPreflight(projectRoot.trim(), file, {
      timeColumn: armaGarchValue.timeColumn,
      valueColumn: armaGarchValue.valueColumn,
      timeIndexSemantics: armaGarchValue.timeIndexSemantics,
      missingValuePolicy: armaGarchValue.missingValuePolicy,
      sheetName,
      transpose,
    }).then((result) => {
      if (!cancelled) setArmaGarchPreflight(result);
    }).catch((error: unknown) => {
      if (!cancelled) {
        setArmaGarchPreflightError(
          error instanceof Error ? error.message : "Full-data transform profile failed",
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [
    armaGarchValue.missingValuePolicy,
    armaGarchValue.timeColumn,
    armaGarchValue.timeIndexSemantics,
    armaGarchValue.valueColumn,
    file,
    isArmaGarch,
    projectRoot,
    sheetName,
    transpose,
  ]);

  const runErrors: Record<string, string> = {};
  if (projectRoot.trim() === "") runErrors.projectRoot = "Create a project first";
  if (isArmaGarch) {
    armaGarchValidationErrors(armaGarchValue).forEach((error, index) => {
      runErrors[`armaGarch${index}`] = error;
    });
  } else {
    if (y.trim() === "") runErrors.y = "Required";
    if (modelType !== "linear_mixed_effects" && xColumns.length === 0) runErrors.x = "Provide at least one column";
  }
  if (isV186ModelType(modelType)) {
    const options = normalizeV186ModelOptions(modelType, v186ModelOptionsByType[modelType]);
    if (modelType === "survival_cox" && !String(options.event_column ?? "").trim()) {
      runErrors.survivalEvent = "Select an event column";
    }
  }
  if (modelType === "linear_mixed_effects") {
    for (const key of ["subject_id", "time", "group"] as const) {
      if (!lmmValue[key]) runErrors[key] = "Required";
    }
  }
  if (!file) runErrors.file = "Select a CSV or Excel file";

  const canRun =
    Object.keys(runErrors).length === 0 && requestState === "idle";

  async function onFileChange(nextFile: File | null) {
    setFile(nextFile);
    setPreview(null);
    setPreviewError(null);
    setSheetName(undefined);
    setTranspose(false);
    setXManuallySet(false);
    setArmaGarchValue(createDefaultArmaGarchValue());
    if (!nextFile) {
      setPreviewState("idle");
      return;
    }
    await refreshPreview(nextFile, undefined, false);
  }

  async function refreshPreview(
    sourceFile: File,
    sheet: string | undefined,
    transposed: boolean,
  ) {
    setPreviewState("loading");
    try {
      const nextPreview = await previewFile(sourceFile, sheet, transposed);
      setPreview(nextPreview);
      if (sheet === undefined) setSheetName(nextPreview.selectedSheet);
      if (nextPreview.suggestedY) setY(nextPreview.suggestedY);
      if (!xManuallySet) setX(nextPreview.suggestedX.join(", "));
      setPreviewState("idle");
    } catch (error) {
      setPreviewState("error");
      setPreviewError(
        error instanceof Error ? error.message : "File preview failed",
      );
    }
  }

  function setXSelection(column: string, selected: boolean) {
    const next = new Set(xColumns);
    if (selected) next.add(column);
    else next.delete(column);
    setX(Array.from(next).join(", "));
  }

  async function onRun() {
    if (!file) return;
    const err = validatePanelPrediction({
      modelType,
      entity: entityCol,
      time: timeCol,
      isPanelData: false, // no reliable client-side panel detection pre-run
      predictionEnabled,
      predictionModelType,
    });
    const predictionContractError = predictionEnabled
      ? predictionDataStructure === "unknown"
        ? "Prediction requires an explicit data structure declaration"
        : predictionDataStructure === "grouped" && !predictionGroupColumn
          ? "Grouped prediction requires a group column"
          : predictionDataStructure === "panel" && !predictionEntityColumn
            ? "Panel prediction requires an entity column"
          : (predictionDataStructure === "temporal" || predictionDataStructure === "panel") && !predictionTimeColumn
            ? "Temporal or panel prediction requires a time column"
            : null
      : null;
    const validationMessage = err ?? predictionContractError;
    setValidationError(validationMessage);
    if (validationMessage) return;
    setRequestState("working");
    setError(null);
    setActivity("Running workflow");
    try {
      // V1.5.4.1: imputation wire format is a JSON string {"method": key}
      // (docs/api-contracts/runs-post.md); empty -> backend config fallback.
      const imputationPayload = imputationMethod
        ? JSON.stringify({ method: imputationMethod })
        : undefined;
      // V1.5.4.4: for IV, the posted x is the exogenous remainder only
      // (X − endog − instruments); endog/instruments go as separate fields.
      // validate_iv_spec on the backend rejects overlap, so we must exclude.
      const isIV = modelType === "iv_2sls";
      // V1.5.5: for DID, the role columns (entity/time/cohort/treat/post/status,
      // whichever are set) carry the design and must NOT appear in x. Mirrors
      // the IV exog-remainder exclusion above.
      const isDID = modelType === "did";
      // V1.5.6: cs_did reuses the exact same entity/time/cohort role wiring as
      // classic DID (same capabilities group). The CS-only knobs go separately.
      const isCsDid = modelType === "cs_did";
      // V1.5.8: Sun-Abraham (sa_did) reuses the exact same entity/time/cohort
      // role wiring AND the CS-only knob channel (cluster var, honest_did) as
      // cs_did. The SA backend ignores the CS-specific control_group/est_method/
      // base_period/anticipation, so posting the same payload is harmless.
      const isSaDid = modelType === "sa_did";
      // V1.5.9: dcdh has its own self-contained roles (entity/time/treatment-path),
      // NOT the cohort-based DID role wiring.
      const isDcdh = modelType === "dcdh";
      const usesCsParams = isCsDid || isSaDid;
      const usesDidRoles = isDID || isCsDid || isSaDid;
      const dcdhRoleCols = isDcdh
        ? [dcdhValue.entity, dcdhValue.time, dcdhValue.treatmentPath].filter((c) => c !== "")
        : [];
      const didRoleCols = usesDidRoles
        ? [
            didRole.entity,
            didRole.time,
            didRole.cohort,
            didRole.treat,
            didRole.post,
            didRole.status,
          ].filter((c) => c !== "")
        : [];
      const exogColumns = isArmaGarch
        ? []
        : isIV
        ? xColumns.filter(
            (c) =>
              !ivRole.endog.includes(c) && !ivRole.instruments.includes(c),
          )
        : usesDidRoles
          ? xColumns.filter((c) => !didRoleCols.includes(c))
          : isDcdh
            ? xColumns.filter((c) => !dcdhRoleCols.includes(c))
            : xColumns;
      const result = await runWorkflow(
        projectRoot.trim(),
        mode,
        (isArmaGarch ? armaGarchValue.valueColumn : y).trim(),
        exogColumns.join(","),
        file,
        modelType,
        sheetName,
        transpose,
        imputationPayload,
        {
          entityCol: usesDidRoles ? didRole.entity : isDcdh ? dcdhValue.entity : entityCol,
          timeCol: usesDidRoles ? didRole.time : isDcdh ? dcdhValue.time : timeCol,
          covariance,
          predictionModelType: predictionEnabled ? predictionModelType : "",
          predictionCvFolds: predictionEnabled ? predictionCvFolds : undefined,
          predictionSamplingMethod: predictionEnabled ? predictionSampling : "",
          predictionDataStructure: predictionEnabled ? predictionDataStructure : undefined,
          predictionEntityColumn: predictionEnabled ? predictionEntityColumn : undefined,
          predictionGroupColumn: predictionEnabled && predictionDataStructure === "grouped" ? predictionGroupColumn : undefined,
          predictionTimeColumn: predictionEnabled ? predictionTimeColumn : undefined,
          predictionFinalHoldoutFraction: predictionEnabled ? predictionFinalHoldoutFraction : undefined,
          predictionShuffle: predictionEnabled ? predictionShuffle : undefined,
          ivEndog: isIV ? ivRole.endog : undefined,
          ivInstruments: isIV ? ivRole.instruments : undefined,
          didMode: usesDidRoles ? didRole.mode : undefined,
          didCohortCol: usesDidRoles ? didRole.cohort : undefined,
          didTreatCol: usesDidRoles ? didRole.treat : undefined,
          didPostCol: usesDidRoles ? didRole.post : undefined,
          didStatusCol: usesDidRoles ? didRole.status : undefined,
          csControlGroup: usesCsParams ? csValue.controlGroup : undefined,
          csEstMethod: usesCsParams ? csValue.estMethod : undefined,
          csBasePeriod: usesCsParams ? csValue.basePeriod : undefined,
          csAnticipation: usesCsParams ? csValue.anticipation : undefined,
          csClusterVar: usesCsParams
            ? csValue.clusterVar
            : isDcdh
              ? dcdhValue.clusterVar
              : undefined,
          honestDid: usesCsParams ? csValue.honestDid : undefined,
          didTreatmentPath: isDcdh ? dcdhValue.treatmentPath : undefined,
          modelOptions:
            modelType === "linear_mixed_effects"
              ? lmmValue
              : isArmaGarch
                ? buildArmaGarchModelOptions(
                    armaGarchValue,
                    `upload:${file.name}`,
                  )
                : isV186ModelType(modelType)
                  ? normalizeV186ModelOptions(modelType, v186ModelOptionsByType[modelType])
                  : undefined,
          // v1.6.5 role layer: declare focal only for user-focal families and
          // only over the columns actually posted as x. Structural families
          // (IV/DID/CS/SA/dCDH) get nothing — focal/treatment is structural.
          focalX:
            isIV || usesDidRoles || isDcdh
              ? undefined
              : focal.filter((c) => exogColumns.includes(c)),
        },
      );
      setLastRun(result);
      onRan?.(result);
      // P0 + race fix: POST /runs returns immediately with
      // status="running" because the orchestrator executes in a
      // background thread. If we navigate now, the Lineage view's
      // graph fetch beats graph.json being written → the user sees
      // the `legacy=true` empty-graph fallback (false "no lineage"
      // state). Poll the run-detail endpoint until terminal first.
      // V1.5.0.1 HF1: do NOT auto-navigate to /runs/:id?tab=lineage.
      // The V1.5.0 P0 behaviour flipped users from the light Submit
      // surface to the dark Lineage view without warning, skipping
      // past the V1.4 result summary (coefficients, trust, diagnostics)
      // that lives in the "Last run" section below. Users complained
      // they couldn't see the result they just ran. We still wait for
      // the run to terminate (so RunResultView fetches a finished run,
      // not a half-baked one), but we stay on Submit and let the user
      // click "Open Lineage →" themselves if they want the graph.
      let finalStatus = result.status;
      if (result.run_id && result.status === "running") {
        setActivity("Running workflow — waiting for completion");
        setProgressLine(null);
        let sawEvent = false;
        const connectingTimer = window.setTimeout(() => {
          if (!sawEvent) setProgressLine("Connecting to event stream…");
        }, 3000);
        try {
          const terminal = await waitForRunTerminal(
            projectRoot.trim(),
            result.run_id,
            {
              onTick: (_detail, lastEvent) => {
                if (!lastEvent) return;
                sawEvent = true;
                window.clearTimeout(connectingTimer);
                const step = lastEvent.step?.trim() ?? "";
                setProgressLine(
                  step ? `${step}: ${lastEvent.message}` : lastEvent.message,
                );
              },
            },
          );
          finalStatus = terminal.status;
        } catch (waitError) {
          const msg =
            waitError instanceof Error
              ? waitError.message
              : "Polling failed";
          setError(msg);
        } finally {
          window.clearTimeout(connectingTimer);
          setProgressLine(null);
        }
      }
      setActivity(
        finalStatus === "blocked"
          ? "Workflow returned blocked"
          : finalStatus === "running"
            ? "Workflow still running"
            : "Workflow completed"
      );
    } catch (error) {
      const message =
        error instanceof ApiError
          ? `[HTTP ${error.status}] ${error.message}`
          : error instanceof Error
            ? error.message
            : "Workflow request failed";
      setError(message);
      setActivity("Workflow request failed");
    } finally {
      setRequestState("idle");
    }
  }

  return (
    <>
      <section className="panel" aria-labelledby="run-heading">
        <div className="panel-heading">
          <h2 id="run-heading">Run</h2>
          <span>Upload CSV or Excel; preview data; submit workflow.</span>
        </div>
        <div className="control-grid run-grid">
          <label>
            Mode
            <select
              aria-label="run mode"
              value={mode}
              onChange={(event) => setMode(event.target.value)}
            >
              <option value="auto">Auto</option>
              <option value="stepped">Stepped</option>
            </select>
          </label>
          <label>
            Model type
            <ModelTypeSelect
              capabilities={capabilities}
              value={modelType}
              onChange={setModelType}
            />
          </label>
          {isV186ModelType(modelType) && (
            <>
              <V186ModelControls
                modelType={modelType}
                columns={columnNames}
                options={normalizeV186ModelOptions(modelType, v186ModelOptionsByType[modelType])}
                onChange={(next) => setV186ModelOptionsByType((current) => ({
                  ...current,
                  [modelType]: next,
                }))}
              />
              {runErrors.survivalEvent && (
                <span className="field-error">{runErrors.survivalEvent}</span>
              )}
            </>
          )}
          <ImputationControls
            capabilities={capabilities}
            value={imputationMethod}
            onChange={setImputationMethod}
          />
          {modelType === "panel_ols" && (
            <PanelControls
              capabilities={capabilities}
              columns={columnNames}
              entity={entityCol}
              time={timeCol}
              covariance={covariance}
              onEntity={setEntityCol}
              onTime={setTimeCol}
              onCovariance={setCovariance}
            />
          )}
          {modelType === "linear_mixed_effects" && (
            <LmmControls columns={columnNames} value={lmmValue} onChange={setLmmValue} />
          )}
          {isArmaGarch && (
            <ArmaGarchControls
              columns={columnNames}
              preview={preview}
              transformPreflight={armaGarchPreflight}
              transformPreflightError={armaGarchPreflightError}
              value={armaGarchValue}
              onChange={(next) => {
                setArmaGarchValue(next);
                setY(next.valueColumn);
                setX("");
              }}
            />
          )}
          {modelType === "iv_2sls" && (
            <div className="ios-group" aria-label="IV controls">
              <p className="ios-hint">
                把控制变量、内生变量、工具变量都加入 X，再在下方为每个变量指派角色
              </p>
              <IVControls
                columns={xColumns}
                value={ivRole}
                onChange={setIvRole}
              />
              {(capabilities?.covariance_options ?? []).length > 0 && (
                <label className="ios-field">
                  <span>标准误 covariance</span>
                  <select
                    aria-label="covariance"
                    value={covariance}
                    onChange={(e) => setCovariance(e.target.value)}
                  >
                    {(capabilities?.covariance_options ?? []).map((c) => (
                      <option key={c.key} value={c.key}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          )}
          {/* DID role cols (entity/time/cohort) are panel identifiers chosen from ALL columns, not the x subset */}
          {(modelType === "did" ||
            modelType === "cs_did" ||
            modelType === "sa_did") && (
            <DIDControls
              columns={columnNames}
              value={didRole}
              onChange={setDidRole}
            />
          )}
          {(modelType === "cs_did" || modelType === "sa_did") && (
            <CSControls
              value={csValue}
              columns={columnNames}
              onChange={setCsValue}
            />
          )}
          {modelType === "dcdh" && (
            <DCDHControls
              value={dcdhValue}
              columns={columnNames}
              onChange={setDcdhValue}
            />
          )}
          {!isArmaGarch && (
            <PredictionControls
              capabilities={capabilities}
              enabled={predictionEnabled}
              modelType={predictionModelType}
              cvFolds={predictionCvFolds}
              sampling={predictionSampling}
              columns={columnNames}
              dataStructure={predictionDataStructure}
              entityColumn={predictionEntityColumn}
              groupColumn={predictionGroupColumn}
              timeColumn={predictionTimeColumn}
              finalHoldoutFraction={predictionFinalHoldoutFraction}
              shuffle={predictionShuffle}
              onEnabled={setPredictionEnabled}
              onModelType={setPredictionModelType}
              onCvFolds={setPredictionCvFolds}
              onSampling={setPredictionSampling}
              onDataStructure={setPredictionDataStructure}
              onEntityColumn={setPredictionEntityColumn}
              onGroupColumn={setPredictionGroupColumn}
              onTimeColumn={setPredictionTimeColumn}
              onFinalHoldoutFraction={setPredictionFinalHoldoutFraction}
              onShuffle={setPredictionShuffle}
            />
          )}
          {validationError && (
            <div className="ios-warning" role="alert">{validationError}</div>
          )}
          {preview && preview.sheetNames.length > 1 && (
            <label>
              Sheet
              <select
                aria-label="sheet selector"
                value={sheetName ?? preview.selectedSheet}
                onChange={(event) => {
                  const next = event.target.value;
                  setSheetName(next);
                  setY("");
                  setX("");
                  if (file) refreshPreview(file, next, transpose);
                }}
              >
                {preview.sheetNames.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </label>
          )}
          {file && (
            <label className="inline-choice">
              <input
                type="checkbox"
                checked={transpose}
                onChange={(event) => {
                  const next = event.target.checked;
                  setTranspose(next);
                  setY("");
                  setX("");
                  if (file) refreshPreview(file, sheetName, next);
                }}
              />
              Transpose (swap rows/columns)
            </label>
          )}
          {file && (
            <span className="field-hint">
              Use this when rows are variables and columns are observations;
              leave it off for the usual one-row-per-observation layout.
            </span>
          )}
          {!isArmaGarch && <label>
            Dependent variable (y)
            <input
              aria-label="dependent variable"
              aria-invalid={Boolean(runErrors.y)}
              placeholder="y"
              value={y}
              onChange={(event) => setY(event.target.value)}
            />
            {runErrors.y && <span className="field-error">{runErrors.y}</span>}
          </label>}
          {!isArmaGarch && <label>
            Regressors (x, comma-separated)
            <input
              aria-label="independent variables"
              aria-invalid={Boolean(runErrors.x)}
              placeholder="x1, x2"
              value={x}
              onChange={(event) => {
                setX(event.target.value);
                setXManuallySet(true);
              }}
            />
            <span className={runErrors.x ? "field-error" : "field-hint"}>
              {runErrors.x ?? `${xColumns.length} column${xColumns.length === 1 ? "" : "s"}`}
            </span>
          </label>}
          {preview && preview.excludedColumns.length > 0 && (
            <details className="excluded-columns">
              <summary>
                {preview.excludedColumns.length} column(s) excluded from auto-suggest
              </summary>
              <ul>
                {preview.excludedColumns.map((col) => (
                  <li key={col.name}>
                    <span className="excluded-name">{col.name}</span>
                    <span className="excluded-reason"> — {col.reason}</span>
                    <button
                      type="button"
                      className="add-back-btn"
                      onClick={() => {
                        const current = xColumns;
                        if (!current.includes(col.name)) {
                          setX([...current, col.name].join(", "));
                          setXManuallySet(true);
                        }
                      }}
                    >
                      + add to X
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {!isArmaGarch && <FocalSelect
            xColumns={xColumns}
            focal={focal.filter((c) => xColumns.includes(c))}
            onChange={setFocal}
            family={modelType}
          />}
          <label>
            Data file (.csv, .xlsx, .xls)
            <input
              aria-label="data file"
              aria-invalid={Boolean(runErrors.file)}
              type="file"
              accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
              onChange={(event) => {
                void onFileChange(event.target.files?.[0] ?? null);
              }}
            />
            {file && (
              <span className="field-hint">
                {file.name} · {(file.size / 1024).toFixed(1)} KB
              </span>
            )}
            {runErrors.file && (
              <span className="field-error">{runErrors.file}</span>
            )}
          </label>
          <button type="button" disabled={!canRun} onClick={onRun}>
            {requestState === "working" && activity === "Running workflow"
              ? "Running…"
              : "Run workflow"}
          </button>
        </div>
        {progressLine && (
          <p
            className="run-progress-line"
            aria-live="polite"
            data-testid="run-progress-line"
          >
            └─ {progressLine}
          </p>
        )}
        {runErrors.projectRoot && (
          <p className="field-error inline-error">{runErrors.projectRoot}</p>
        )}
        {previewState === "loading" && (
          <p className="muted">Previewing file…</p>
        )}
        {previewState === "error" && previewError && (
          <p className="field-error inline-error">{previewError}</p>
        )}
        {preview && (
          <section className="preview-panel" aria-labelledby="preview-heading">
            <div className="panel-heading compact-heading">
              <h3 id="preview-heading" className="subhead">
                Data preview
              </h3>
              <span>
                {preview.fileName} · {preview.rowCount} rows ·{" "}
                {preview.columnCount} columns
              </span>
            </div>
            {preview.transpose_warning && (
              <div className="transpose-warning" role="alert">
                {preview.transpose_warning}
              </div>
            )}
            <div className="preview-table-wrap">
              <table className="preview-table">
                <thead>
                  <tr>
                    {preview.columns.map((column) => (
                      <th key={column.name}>{column.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.previewRows.map((row, index) => (
                    <tr key={index}>
                      {preview.columns.map((column) => (
                        <td key={column.name}>{String(row[column.name] ?? "")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!isArmaGarch && <div className="column-selector" aria-label="column selector">
              {preview.columns.map((column) => (
                <div key={column.name} className="column-option">
                  <div>
                    <strong>{column.name}</strong>
                    <span className="column-meta">
                      {column.dtype} · {column.uniqueCount} unique ·{" "}
                      {column.mean !== undefined
                        ? `mean ${column.mean.toFixed(2)} / std ${(column.std ?? 0).toFixed(2)}`
                        : `${(column.missingRate * 100).toFixed(0)}% missing`}
                    </span>
                  </div>
                  <label className="inline-choice">
                    <input
                      type="radio"
                      name="dependent-column"
                      checked={y === column.name}
                      onChange={() => setY(column.name)}
                    />
                    y
                  </label>
                  <label className="inline-choice">
                    <input
                      type="checkbox"
                      checked={xColumns.includes(column.name)}
                      disabled={y === column.name}
                      onChange={(event) =>
                        setXSelection(column.name, event.target.checked)
                      }
                    />
                    x
                  </label>
                </div>
              ))}
            </div>}
          </section>
        )}
      </section>

      <section className="panel" aria-labelledby="result-heading">
        <div className="panel-heading">
          <h2 id="result-heading">Last run</h2>
          {lastRun ? (
            <button
              type="button"
              onClick={() => {
                const params = new URLSearchParams({
                  project_root: projectRoot,
                  tab: "lineage",
                });
                navigate(`/runs/${lastRun.run_id}?${params.toString()}`);
              }}
            >
              Open Lineage →
            </button>
          ) : (
            <span>No run yet.</span>
          )}
        </div>
        {lastRun ? (
          <RunResultView
            projectRoot={projectRoot}
            runId={lastRun.run_id}
            onError={setError}
            onFailureAction={(action) => {
              // V1.5.4.1: apply a recovery action's form_overrides to the
              // form. Minimum behavior — set model_type back; the user then
              // clicks "Run analysis" again to re-submit.
              const overrides = action.form_overrides;
              if (overrides && typeof overrides.model_type === "string") {
                setModelType(overrides.model_type);
              }
            }}
          />
        ) : (
          <p className="muted">
            Submit a workflow to see run details and output paths.
          </p>
        )}
      </section>
    </>
  );
}
