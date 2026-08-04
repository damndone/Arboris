import { useEffect, useMemo, useState } from "react";
import {
  createGenesisDraft,
  executePipelineDraft,
  fetchArmaGarchTransformPreflight,
  getPipelineDraft,
  listPipelineDrafts,
  patchDraftNode,
  previewFile,
  uploadDataset,
  validatePipelineDraft,
  type DraftExecutionResult,
  type DraftValidationResult,
  type ArmaGarchTransformPreflight,
  type FilePreview,
  type PipelineDraftNode,
  type PipelineDraftResponse,
  type PipelineDraftV1,
} from "../../api";
import { useCapabilities } from "../../capabilities/useCapabilities";
import { ModelTypeSelect } from "../../runForm/ModelTypeSelect";
import { ImputationControls } from "../../runForm/ImputationControls";
import { PanelControls } from "../../runForm/PanelControls";
import { LmmControls, type LmmControlValue } from "../../runForm/LmmControls";
import { PredictionControls } from "../../runForm/PredictionControls";
import { FocalSelect } from "../../runForm/FocalSelect";
import { IVControls, type IVRoleValue } from "../../runForm/IVControls";
import { DIDControls, type DIDRoleValue } from "../../runForm/DIDControls";
import { CSControls, type CSValue } from "../../runForm/CSControls";
import { DCDHControls, type DCDHValue } from "../../runForm/DCDHControls";
import { ColumnRolePicker } from "../../runForm/ColumnRolePicker";
import { CovarianceSelect, covarianceDefault } from "../../runForm/CovarianceSelect";
import {
  ArmaGarchControls,
  armaGarchValidationErrors,
  armaGarchValueFromModelOptions,
  buildArmaGarchModelOptions,
  createDefaultArmaGarchValue,
  type ArmaGarchControlValue,
} from "../../runForm/ArmaGarchControls";
import {
  V186ModelControls,
  defaultV186ModelOptions,
  isV186ModelType,
  normalizeV186ModelOptions,
  type V186ModelOptionsByType,
} from "../../runForm/V186ModelControls";

type BusyState =
  | "resume"
  | "file"
  | "table"
  | "model"
  | "validate"
  | "execute"
  | null;

export interface GenesisWizardProps {
  projectRoot: string;
  onClose: () => void;
  onDraftUpdated?: (response: PipelineDraftResponse) => void;
  onDraftValidated?: (draftId: string, validation: DraftValidationResult) => void;
  onDraftExecuting?: (draftId: string) => void;
  onDraftFailed?: (draftId: string) => void;
  onDraftExecuted?: (result: DraftExecutionResult, draftId: string) => void;
}

function parseColumns(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "");
}

function previewColumns(preview: FilePreview | null): string[] {
  return preview?.columns.map((column) => column.name) ?? [];
}

function findNode<T extends PipelineDraftNode["node_type"]>(
  draft: PipelineDraftV1 | null,
  nodeType: T,
): Extract<PipelineDraftNode, { node_type: T }> | null {
  return (
    draft?.graph.nodes.find((node) => node.node_type === nodeType) as
      | Extract<PipelineDraftNode, { node_type: T }>
      | undefined
  ) ?? null;
}

function isGenesisDraft(draft: PipelineDraftV1): boolean {
  return draft.created_from?.source_type === "genesis";
}

function firstString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function firstNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

export function GenesisWizard({
  projectRoot,
  onClose,
  onDraftUpdated,
  onDraftValidated,
  onDraftExecuting,
  onDraftFailed,
  onDraftExecuted,
}: GenesisWizardProps) {
  const { data: capabilities } = useCapabilities();
  const [busy, setBusy] = useState<BusyState>(null);
  const [error, setError] = useState<string | null>(null);
  const [resumeCandidate, setResumeCandidate] =
    useState<PipelineDraftResponse | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [draft, setDraft] = useState<PipelineDraftV1 | null>(null);
  const [draftHash, setDraftHash] = useState("");
  const [sheetName, setSheetName] = useState("");
  const [transpose, setTranspose] = useState(false);
  const [tableConfigured, setTableConfigured] = useState(false);
  const [modelConfigured, setModelConfigured] = useState(false);
  const [modelType, setModelType] = useState("auto");
  const [imputationMethod, setImputationMethod] = useState<string | null>(null);
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
  const [v186ModelOptionsByType, setV186ModelOptionsByType] =
    useState<V186ModelOptionsByType>({});
  const [armaGarchPreflight, setArmaGarchPreflight] =
    useState<ArmaGarchTransformPreflight | null>(null);
  const [armaGarchPreflightError, setArmaGarchPreflightError] =
    useState<string | null>(null);
  const [ivRole, setIvRole] = useState<IVRoleValue>({
    endog: [],
    instruments: [],
  });
  const [didRole, setDidRole] = useState<DIDRoleValue>({
    mode: "cohort",
    entity: "",
    time: "",
    cohort: "",
    treat: "",
    post: "",
    status: "",
  });
  const [csValue, setCsValue] = useState<CSValue>({
    controlGroup: "never",
    estMethod: "dr",
    basePeriod: "varying",
    anticipation: 0,
    clusterVar: "",
    honestDid: false,
  });
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
  const [frequencyWeight, setFrequencyWeight] = useState("");
  const [analysisWeight, setAnalysisWeight] = useState("");
  const [samplingWeight, setSamplingWeight] = useState("");
  const [weightParamsPresent, setWeightParamsPresent] = useState({
    frequency: false,
    analysis: false,
    sampling: false,
  });
  const [y, setY] = useState("");
  const [x, setX] = useState("");
  const [focal, setFocal] = useState<string[]>([]);
  const [validation, setValidation] = useState<DraftValidationResult | null>(null);

  const xColumns = useMemo(() => parseColumns(x), [x]);
  const columnNames = useMemo(() => {
    const fromPreview = previewColumns(preview);
    if (fromPreview.length > 0) return fromPreview;
    return findNode(draft, "table")?.columns ?? [];
  }, [draft, preview]);

  useEffect(() => {
    let cancelled = false;
    listPipelineDrafts(projectRoot)
      .then(async (summaries) => {
        const open = summaries.find(
          (summary) =>
            summary.status !== "executed" &&
            !summary.source_node_hash &&
            !summary.source_op_node_id,
        );
        if (!open) return;
        const response = await getPipelineDraft(projectRoot, open.draft_id);
        if (!cancelled && isGenesisDraft(response.draft)) {
          setResumeCandidate(response);
        }
      })
      .catch(() => {
        /* resume is best-effort */
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot]);

  function applyPreview(nextPreview: FilePreview, overwriteModel = true) {
    setPreview(nextPreview);
    setSheetName(nextPreview.selectedSheet);
    if (overwriteModel) {
      setY(nextPreview.suggestedY ?? "");
      setX(nextPreview.suggestedX.join(", "));
      setFocal([]);
    }
  }

  function adoptDraft(response: PipelineDraftResponse, notify = true) {
    setDraft(response.draft);
    setDraftHash(response.draft_hash);
    const source = findNode(response.draft, "input.upload");
    const table = findNode(response.draft, "table");
    const model = findNode(response.draft, "model");
    const tableParams = table?.params ?? {};
    const modelParams = model?.params ?? {};
    setSheetName(
      (current) =>
        firstString(tableParams.sheet_name) || current || source?.sheet_names[0] || "",
    );
    setTranspose(Boolean(tableParams.transpose));
    setTableConfigured(table?.status === "configured");
    setModelConfigured(model?.status === "configured");
    const savedType = firstString(modelParams.model_type) || model?.model_type || "";
    setModelType((current) => savedType || current);
    const nextY = firstString(modelParams.y);
    if (nextY) setY(nextY);
    const modelX = stringList(modelParams.x);
    const modelFocal = stringList(modelParams.focal_x);
    if (modelFocal.length > 0) setFocal(modelFocal);

    // B2 (2026-07-08): saved model params must round-trip into the FULL form
    // state, not just y/x/focal. Otherwise resuming a structural draft
    // (IV/DID/CS/SA/dCDH/panel/prediction) and pressing "保存模型配置" rebuilds
    // params from pristine role state and silently strips the saved roles.
    // Convention (matches the y/x guards above): restore only what is present;
    // never reset absent fields, because adoptDraft also runs after table-only
    // patches while the user is still mid-edit.
    const savedCovariance = firstString(modelParams.covariance);
    if (savedCovariance) setCovariance(savedCovariance);
    if (savedType === "linear_mixed_effects") {
      const savedOptions = modelParams.model_options;
      if (savedOptions && typeof savedOptions === "object" && !Array.isArray(savedOptions)) {
        const options = savedOptions as Record<string, unknown>;
        setLmmValue((current) => ({
          subject_id: firstString(options.subject_id) || current.subject_id,
          time: firstString(options.time) || current.time,
          group: firstString(options.group) || current.group,
          fit_method:
            options.fit_method === "ml" || options.fit_method === "reml"
              ? options.fit_method
              : current.fit_method,
          random_slope:
            typeof options.random_slope === "boolean"
              ? options.random_slope
              : current.random_slope,
        }));
      }
    }
    if (savedType === "time_series.arma_garch") {
      const savedOptions = modelParams.model_options;
      if (savedOptions && typeof savedOptions === "object" && !Array.isArray(savedOptions)) {
        setArmaGarchValue((current) =>
          armaGarchValueFromModelOptions(savedOptions as Record<string, unknown>, current),
        );
      }
    }
    if (isV186ModelType(savedType)) {
      setV186ModelOptionsByType((current) => ({
        ...current,
        [savedType]: normalizeV186ModelOptions(savedType, modelParams.model_options),
      }));
    }
    const savedImputation = firstString(modelParams.imputation);
    if (savedImputation) {
      try {
        const parsed: unknown = JSON.parse(savedImputation);
        const method =
          parsed && typeof parsed === "object"
            ? firstString((parsed as Record<string, unknown>).method)
            : "";
        if (method) setImputationMethod(method);
      } catch {
        /* malformed imputation payload — leave the control untouched */
      }
    }
    const savedEntity = firstString(modelParams.entity_col);
    const savedTime = firstString(modelParams.time_col);
    const ivEndog = stringList(modelParams.iv_endog);
    const ivInstruments = stringList(modelParams.iv_instruments);
    if (ivEndog.length > 0 || ivInstruments.length > 0) {
      setIvRole({ endog: ivEndog, instruments: ivInstruments });
    }
    // The saved `x` is the exog remainder; the IV picker UI expects endog and
    // instruments back inside X so their role chips render.
    const uiX =
      savedType === "iv_2sls"
        ? [
            ...modelX,
            ...ivEndog.filter((col) => !modelX.includes(col)),
            ...ivInstruments.filter((col) => !modelX.includes(col)),
          ]
        : modelX;
    if (uiX.length > 0) setX(uiX.join(", "));
    if (savedType === "did" || savedType === "cs_did" || savedType === "sa_did") {
      setDidRole((current) => ({
        mode:
          (firstString(modelParams.did_mode) as DIDRoleValue["mode"]) ||
          current.mode,
        entity: savedEntity || current.entity,
        time: savedTime || current.time,
        cohort: firstString(modelParams.did_cohort_col) || current.cohort,
        treat: firstString(modelParams.did_treat_col) || current.treat,
        post: firstString(modelParams.did_post_col) || current.post,
        status: firstString(modelParams.did_status_col) || current.status,
      }));
    } else if (savedType === "dcdh") {
      setDcdhValue((current) => ({
        entity: savedEntity || current.entity,
        time: savedTime || current.time,
        treatmentPath:
          firstString(modelParams.did_treatment_path) || current.treatmentPath,
        clusterVar: firstString(modelParams.cs_cluster_var) || current.clusterVar,
      }));
    } else {
      if (savedEntity) setEntityCol(savedEntity);
      if (savedTime) setTimeCol(savedTime);
    }
    if (savedType === "cs_did" || savedType === "sa_did") {
      setCsValue((current) => ({
        controlGroup:
          (firstString(modelParams.cs_control_group) as CSValue["controlGroup"]) ||
          current.controlGroup,
        estMethod:
          (firstString(modelParams.cs_est_method) as CSValue["estMethod"]) ||
          current.estMethod,
        basePeriod:
          (firstString(modelParams.cs_base_period) as CSValue["basePeriod"]) ||
          current.basePeriod,
        anticipation:
          firstNumber(modelParams.cs_anticipation) ?? current.anticipation,
        clusterVar: firstString(modelParams.cs_cluster_var) || current.clusterVar,
        honestDid: modelParams.honest_did === true ? true : current.honestDid,
      }));
    }
    const savedPredictionType = firstString(modelParams.prediction_model_type);
    if (savedPredictionType) {
      setPredictionEnabled(true);
      setPredictionModelType(savedPredictionType);
      const savedFolds = firstNumber(modelParams.prediction_cv_folds);
      if (savedFolds !== null) setPredictionCvFolds(savedFolds);
      const savedSampling = firstString(modelParams.prediction_sampling_method);
      if (savedSampling) setPredictionSampling(savedSampling);
      const savedStructure = firstString(modelParams.prediction_data_structure);
      if (savedStructure) setPredictionDataStructure(savedStructure);
      const savedGroup = firstString(modelParams.prediction_group_column);
      if (savedGroup) setPredictionGroupColumn(savedGroup);
      const savedEntity = firstString(modelParams.prediction_entity_column);
      if (savedEntity) setPredictionEntityColumn(savedEntity);
      const savedTime = firstString(modelParams.prediction_time_column);
      if (savedTime) setPredictionTimeColumn(savedTime);
      const savedHoldout = firstNumber(modelParams.prediction_final_holdout_fraction);
      if (savedHoldout !== null) setPredictionFinalHoldoutFraction(savedHoldout);
      if (typeof modelParams.prediction_shuffle === "boolean") {
        setPredictionShuffle(modelParams.prediction_shuffle);
      }
    }
    setFrequencyWeight(firstString(modelParams.frequency_weight));
    setAnalysisWeight(firstString(modelParams.analysis_weight));
    setSamplingWeight(firstString(modelParams.sampling_weight));
    setWeightParamsPresent({
      frequency: Object.prototype.hasOwnProperty.call(modelParams, "frequency_weight"),
      analysis: Object.prototype.hasOwnProperty.call(modelParams, "analysis_weight"),
      sampling: Object.prototype.hasOwnProperty.call(modelParams, "sampling_weight"),
    });
    if (notify) onDraftUpdated?.(response);
  }

  async function handleFileChange(nextFile: File | null) {
    setFile(nextFile);
    setPreview(null);
    setDraft(null);
    setDraftHash("");
    setTableConfigured(false);
    setModelConfigured(false);
    setValidation(null);
    setError(null);
    setWeightParamsPresent({ frequency: false, analysis: false, sampling: false });
    if (!nextFile) return;
    setBusy("file");
    try {
      const nextPreview = await previewFile(nextFile);
      applyPreview(nextPreview);
      const upload = await uploadDataset(projectRoot, nextFile);
      const created = await createGenesisDraft(projectRoot, {
        upload_sha256: upload.sha256,
        filename: upload.filename,
        sheet_names: nextPreview.sheetNames,
        columns: previewColumns(nextPreview),
      });
      adoptDraft(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建创世 draft 失败");
    } finally {
      setBusy(null);
    }
  }

  async function handleResume() {
    if (!resumeCandidate) return;
    setBusy("resume");
    setError(null);
    try {
      adoptDraft(resumeCandidate);
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    if (modelType !== "time_series.arma_garch" || !preview) return;
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
    setArmaGarchValue((current) => ({
      ...current,
      timeColumn: current.timeColumn || suggestedTime,
      valueColumn: current.valueColumn || suggestedValue,
    }));
  }, [modelType, preview]);

  useEffect(() => {
    if (
      modelType !== "time_series.arma_garch"
      || !file
      || !armaGarchValue.timeColumn
      || !armaGarchValue.valueColumn
    ) {
      setArmaGarchPreflight(null);
      setArmaGarchPreflightError(null);
      return;
    }
    let cancelled = false;
    setArmaGarchPreflight(null);
    setArmaGarchPreflightError(null);
    fetchArmaGarchTransformPreflight(projectRoot, file, {
      timeColumn: armaGarchValue.timeColumn,
      valueColumn: armaGarchValue.valueColumn,
      timeIndexSemantics: armaGarchValue.timeIndexSemantics,
      missingValuePolicy: armaGarchValue.missingValuePolicy,
      sheetName,
      transpose,
    }).then((result) => {
      if (!cancelled) setArmaGarchPreflight(result);
    }).catch((err: unknown) => {
      if (!cancelled) {
        setArmaGarchPreflightError(
          err instanceof Error ? err.message : "Full-data transform profile failed",
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
    modelType,
    projectRoot,
    sheetName,
    transpose,
  ]);

  async function saveTable() {
    if (!draft) return;
    setBusy("table");
    setError(null);
    try {
      let nextPreview = preview;
      if (file) {
        nextPreview = await previewFile(file, sheetName || undefined, transpose);
        applyPreview(nextPreview, false);
      }
      const columns =
        previewColumns(nextPreview).length > 0
          ? previewColumns(nextPreview)
          : columnNames;
      const response = await patchDraftNode(projectRoot, draft.draft_id, "table_1", {
        // CSV sources have no worksheet name.  Keep that fact explicit rather
        // than forcing users to choose a meaningless value before they can
        // continue the genesis flow.
        params: { sheet_name: sheetName || undefined, transpose },
        columns,
      });
      setValidation(null);
      adoptDraft(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存表格配置失败");
    } finally {
      setBusy(null);
    }
  }

  function modelParams(): Record<string, unknown> {
    const isIV = modelType === "iv_2sls";
    const isDID = modelType === "did";
    const isCsDid = modelType === "cs_did";
    const isSaDid = modelType === "sa_did";
    const isDcdh = modelType === "dcdh";
    const usesCsParams = isCsDid || isSaDid;
    const usesDidRoles = isDID || isCsDid || isSaDid;
    const didRoleCols = usesDidRoles
      ? [
          didRole.entity,
          didRole.time,
          didRole.cohort,
          didRole.treat,
          didRole.post,
          didRole.status,
        ].filter((col) => col !== "")
      : [];
    const dcdhRoleCols = isDcdh
      ? [dcdhValue.entity, dcdhValue.time, dcdhValue.treatmentPath].filter(
          (col) => col !== "",
        )
      : [];
    const exogColumns = isIV
      ? xColumns.filter(
          (col) =>
            !ivRole.endog.includes(col) && !ivRole.instruments.includes(col),
        )
      : usesDidRoles
        ? xColumns.filter((col) => !didRoleCols.includes(col))
        : isDcdh
          ? xColumns.filter((col) => !dcdhRoleCols.includes(col))
          : xColumns;
    const defaultCovariance = covariance || covarianceDefault(capabilities);
    const params: Record<string, unknown> = {
      model_type: modelType,
      y: modelType === "time_series.arma_garch" ? armaGarchValue.valueColumn : y.trim(),
      x: modelType === "time_series.arma_garch" ? [] : exogColumns,
    };
    if (imputationMethod) params.imputation = JSON.stringify({ method: imputationMethod });
    if (!isDID && !usesCsParams && !isDcdh && defaultCovariance) {
      params.covariance = defaultCovariance;
    }
    if (modelType === "panel_ols") {
      if (entityCol) params.entity_col = entityCol;
      if (timeCol) params.time_col = timeCol;
    }
    if (modelType === "linear_mixed_effects") {
      params.model_options = lmmValue;
    }
    if (modelType === "time_series.arma_garch") {
      const sourceFilename = file?.name
        ?? findNode(draft, "input.upload")?.upload.filename
        ?? "dataset";
      params.model_options = buildArmaGarchModelOptions(
        armaGarchValue,
        `upload:${sourceFilename}`,
      );
    }
    if (isV186ModelType(modelType)) {
      params.model_options =
        v186ModelOptionsByType[modelType] ?? defaultV186ModelOptions(modelType);
    }
    if (isIV) {
      if (ivRole.endog.length > 0) params.iv_endog = ivRole.endog;
      if (ivRole.instruments.length > 0) params.iv_instruments = ivRole.instruments;
    }
    if (usesDidRoles) {
      if (didRole.entity) params.entity_col = didRole.entity;
      if (didRole.time) params.time_col = didRole.time;
      params.did_mode = didRole.mode;
      if (didRole.cohort) params.did_cohort_col = didRole.cohort;
      if (didRole.treat) params.did_treat_col = didRole.treat;
      if (didRole.post) params.did_post_col = didRole.post;
      if (didRole.status) params.did_status_col = didRole.status;
    }
    if (usesCsParams) {
      params.cs_control_group = csValue.controlGroup;
      params.cs_est_method = csValue.estMethod;
      params.cs_base_period = csValue.basePeriod;
      params.cs_anticipation = csValue.anticipation;
      if (csValue.clusterVar) params.cs_cluster_var = csValue.clusterVar;
      if (csValue.honestDid) params.honest_did = true;
    }
    if (isDcdh) {
      if (dcdhValue.entity) params.entity_col = dcdhValue.entity;
      if (dcdhValue.time) params.time_col = dcdhValue.time;
      if (dcdhValue.treatmentPath) params.did_treatment_path = dcdhValue.treatmentPath;
      if (dcdhValue.clusterVar) params.cs_cluster_var = dcdhValue.clusterVar;
    }
    if (predictionEnabled) {
      if (predictionModelType) params.prediction_model_type = predictionModelType;
      params.prediction_cv_folds = predictionCvFolds;
      if (predictionSampling) params.prediction_sampling_method = predictionSampling;
      params.prediction_data_structure = predictionDataStructure;
      if (predictionEntityColumn) params.prediction_entity_column = predictionEntityColumn;
      if (predictionGroupColumn) params.prediction_group_column = predictionGroupColumn;
      if (predictionTimeColumn) params.prediction_time_column = predictionTimeColumn;
      params.prediction_final_holdout_fraction = predictionFinalHoldoutFraction;
      params.prediction_shuffle = predictionShuffle;
    }
    if (frequencyWeight || weightParamsPresent.frequency) {
      params.frequency_weight = frequencyWeight;
    }
    if (analysisWeight || weightParamsPresent.analysis) {
      params.analysis_weight = analysisWeight;
    }
    if (samplingWeight || weightParamsPresent.sampling) {
      params.sampling_weight = samplingWeight;
    }
    if (!isIV && !usesDidRoles && !isDcdh && focal.length > 0) {
      params.focal_x = focal.filter((col) => exogColumns.includes(col));
    }
    return params;
  }

  function setXSelection(column: string, checked: boolean) {
    const current = xColumns;
    if (checked) {
      if (!current.includes(column)) setX([...current, column].join(", "));
      return;
    }
    setX(current.filter((col) => col !== column).join(", "));
    setFocal((items) => items.filter((col) => col !== column));
    setIvRole((role) => ({
      endog: role.endog.filter((col) => col !== column),
      instruments: role.instruments.filter((col) => col !== column),
    }));
  }

  async function saveModel() {
    if (!draft) return;
    if (modelType === "time_series.arma_garch") {
      const issues = armaGarchValidationErrors(armaGarchValue);
      if (issues.length > 0) {
        setError(issues[0]);
        return;
      }
    } else if (!y.trim() || (modelType !== "linear_mixed_effects" && xColumns.length === 0)) {
      setError("请选择 y，并至少选择一个 x。");
      return;
    }
    if (
      modelType === "linear_mixed_effects" &&
      (!lmmValue.subject_id || !lmmValue.time || !lmmValue.group)
    ) {
      setError("LMM 需要指定受试者、时间和组别列。");
      return;
    }
    if (
      modelType === "survival_cox" &&
      (!v186ModelOptionsByType.survival_cox?.event_column ||
        typeof v186ModelOptionsByType.survival_cox.event_column !== "string")
    ) {
      setError("Survival / Cox 需要指定 event 列。");
      return;
    }
    if (modelType === "panel_ols" && entityCol && timeCol && entityCol === timeCol) {
      setError("个体列与时间列不能是同一列 (entity == time)。");
      return;
    }
    if (predictionEnabled && !predictionModelType) {
      setError("已开启预测，请选择算法 (algorithm)。");
      return;
    }
    if (predictionEnabled && predictionDataStructure === "unknown") {
      setError("预测必须声明数据结构 (IID、分组、时间或面板)。");
      return;
    }
    if (
      predictionEnabled &&
      predictionDataStructure === "grouped" &&
      !predictionGroupColumn
    ) {
      setError("分组预测必须指定分组列。");
      return;
    }
    if (
      predictionEnabled &&
      predictionDataStructure === "panel" &&
      !predictionEntityColumn
    ) {
      setError("面板预测必须指定个体列。");
      return;
    }
    if (
      predictionEnabled &&
      (predictionDataStructure === "temporal" || predictionDataStructure === "panel") &&
      !predictionTimeColumn
    ) {
      setError("时间或面板预测必须指定时间列。");
      return;
    }
    setBusy("model");
    setError(null);
    try {
      const response = await patchDraftNode(projectRoot, draft.draft_id, "model_1", {
        params: modelParams(),
      });
      setValidation(null);
      adoptDraft(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存模型配置失败");
    } finally {
      setBusy(null);
    }
  }

  async function validateAndExecute() {
    if (!draft) return;
    let executing = false;
    setBusy("validate");
    setError(null);
    try {
      const nextValidation = await validatePipelineDraft(
        projectRoot,
        draft.draft_id,
        "genesis",
      );
      setValidation(nextValidation);
      onDraftValidated?.(draft.draft_id, nextValidation);
      if (!nextValidation.executable) {
        setError("创世链路还不能执行，请先处理校验问题。");
        return;
      }
      setBusy("execute");
      executing = true;
      onDraftExecuting?.(draft.draft_id);
      const result = await executePipelineDraft(projectRoot, draft.draft_id, {
        validated_draft_hash: nextValidation.validated_draft_hash ?? draftHash,
        execution_mode: "genesis",
      });
      onDraftExecuted?.(result, draft.draft_id);
    } catch (err) {
      if (executing) onDraftFailed?.(draft.draft_id);
      setError(err instanceof Error ? err.message : "执行创世链路失败");
    } finally {
      setBusy(null);
    }
  }

  const draftId = draft?.draft_id ?? null;
  const sourceSheetNames = findNode(draft, "input.upload")?.sheet_names ?? [];
  // An empty sheet list is the normal CSV case, not an incomplete table
  // configuration.  Spreadsheet uploads still require their selected sheet.
  const canSaveTable = Boolean(draftId && (sheetName || sourceSheetNames.length === 0));
  const lmmRolesConfigured = Boolean(lmmValue.subject_id && lmmValue.time && lmmValue.group);
  const armaGarchConfigured = armaGarchValidationErrors(armaGarchValue).length === 0;
  const canSaveModel = Boolean(
    draftId &&
      tableConfigured &&
      (modelType === "time_series.arma_garch"
        ? armaGarchConfigured
        : y.trim() &&
          (modelType === "linear_mixed_effects" ? lmmRolesConfigured : xColumns.length > 0)),
  );
  const canRun = Boolean(draftId && modelConfigured);
  const activeV186ModelOptions = isV186ModelType(modelType)
    ? v186ModelOptionsByType[modelType] ?? defaultV186ModelOptions(modelType)
    : null;

  return (
    <div data-testid="genesis-wizard" style={{ display: "grid", gap: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 16 }}>新链路</h2>
          {draftId && (
            <p className="mono" style={{ margin: "4px 0 0", fontSize: 11 }}>
              {draftId}
            </p>
          )}
        </div>
        <button type="button" aria-label="Close" onClick={onClose}>
          ×
        </button>
      </div>

      {resumeCandidate && !draft && (
        <section className="ios-group" data-testid="genesis-resume">
          <div className="ios-group-label">继续上次的链路</div>
          <p className="ios-hint" style={{ marginTop: 0 }}>
            文件已保存到项目中；换表或重新预览时需要重新选择本地文件。
          </p>
          <button
            type="button"
            onClick={handleResume}
            disabled={busy !== null}
          >
            继续
          </button>
        </section>
      )}

      <section className="ios-group">
        <div className="ios-group-label">1. 数据文件</div>
        <label className="ios-field">
          <span>Dataset file</span>
          <input
            aria-label="Dataset file"
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(event) => handleFileChange(event.currentTarget.files?.[0] ?? null)}
            disabled={busy !== null}
          />
        </label>
        {preview && (
          <p className="ios-hint" style={{ marginBottom: 0 }}>
            {preview.rowCount} rows · {preview.columnCount} columns
          </p>
        )}
      </section>

      {draft && (
        <section className="ios-group">
          <div className="ios-group-label">2. 表格</div>
          <label className="ios-field">
            <span>Sheet</span>
            <select
              aria-label="sheet selector"
              value={sheetName}
              onChange={(event) => setSheetName(event.target.value)}
            >
              {(preview?.sheetNames ?? findNode(draft, "input.upload")?.sheet_names ?? []).map(
                (name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ),
              )}
            </select>
          </label>
          <label className="ios-row">
            <span>Transpose</span>
            <input
              aria-label="transpose"
              type="checkbox"
              checked={transpose}
              onChange={(event) => setTranspose(event.target.checked)}
            />
          </label>
          <p className="ios-hint" style={{ marginTop: -4 }}>
            Treat rows as variables and columns as observations. Use this when
            the file is stored sideways; leave it off for the usual one-row-per-observation layout.
          </p>
          <button
            type="button"
            data-testid="genesis-save-table"
            onClick={saveTable}
            disabled={!canSaveTable || busy !== null}
          >
            保存表格
          </button>
        </section>
      )}

      {draft && (
        <section className="ios-group">
          <div className="ios-group-label">3. 模型</div>
          <label className="ios-field">
            <span>Model type</span>
            <ModelTypeSelect
              capabilities={capabilities}
              value={modelType}
              onChange={setModelType}
            />
          </label>
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
            <LmmControls
              columns={columnNames}
              value={lmmValue}
              onChange={setLmmValue}
            />
          )}
          {modelType === "time_series.arma_garch" && (
            <ArmaGarchControls
              columns={columnNames}
              preview={preview}
              transformPreflight={armaGarchPreflight}
              transformPreflightError={armaGarchPreflightError}
              value={armaGarchValue}
              onChange={setArmaGarchValue}
            />
          )}
          {isV186ModelType(modelType) && activeV186ModelOptions && (
            <V186ModelControls
              modelType={modelType}
              columns={columnNames}
              options={activeV186ModelOptions}
              onChange={(options) => {
                setV186ModelOptionsByType((current) => ({
                  ...current,
                  [modelType]: options,
                }));
              }}
            />
          )}
          {modelType === "iv_2sls" && (
            <div className="ios-group">
              <p className="ios-hint">
                把控制变量、内生变量、工具变量都加入 X，再在下方为每个变量指派角色。
              </p>
              <IVControls
                columns={xColumns}
                value={ivRole}
                onChange={setIvRole}
              />
              <CovarianceSelect
                capabilities={capabilities}
                value={covariance}
                onChange={setCovariance}
              />
            </div>
          )}
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
          <div className="ios-group" aria-label="Weight settings">
            <p className="ios-hint">
              权重会写入本次 Run 的证据。frequency / analysis 可用于 OLS；sampling 目前会明确拒绝，请通过现有 entity_col + covariance=clustered 通道声明 strata/PSU。
            </p>
            <label className="ios-field">
              <span>频数权重 frequency weight（可选）</span>
              <select aria-label="frequency weight" value={frequencyWeight}
                onChange={(e) => {
                  setFrequencyWeight(e.target.value);
                  setWeightParamsPresent((current) => ({ ...current, frequency: true }));
                }}>
                <option value="">(不使用)</option>
                {columnNames.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </label>
            <label className="ios-field">
              <span>分析权重 analysis weight（可选）</span>
              <select aria-label="analysis weight" value={analysisWeight}
                onChange={(e) => {
                  setAnalysisWeight(e.target.value);
                  setWeightParamsPresent((current) => ({ ...current, analysis: true }));
                }}>
                <option value="">(不使用)</option>
                {columnNames.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </label>
            <label className="ios-field">
              <span>抽样权重 sampling weight（当前会拒绝）</span>
              <select aria-label="sampling weight" value={samplingWeight}
                onChange={(e) => {
                  setSamplingWeight(e.target.value);
                  setWeightParamsPresent((current) => ({ ...current, sampling: true }));
                }}>
                <option value="">(不使用)</option>
                {columnNames.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </label>
          </div>
          {modelType !== "time_series.arma_garch" && <PredictionControls
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
          />}
          {modelType !== "time_series.arma_garch" &&
            modelType !== "panel_ols" &&
            modelType !== "iv_2sls" &&
            modelType !== "did" &&
            modelType !== "cs_did" &&
            modelType !== "sa_did" &&
            modelType !== "dcdh" && (
              <CovarianceSelect
                capabilities={capabilities}
                value={covariance}
                onChange={setCovariance}
              />
            )}
          {modelType !== "time_series.arma_garch" && <label className="ios-field">
            <span>Dependent variable (y)</span>
            <select
              aria-label="dependent variable"
              value={y}
              onChange={(event) => setY(event.target.value)}
            >
              <option value="">(选择)</option>
              {columnNames.map((column) => (
                <option key={column} value={column}>
                  {column}
                </option>
              ))}
            </select>
          </label>}
          {modelType !== "time_series.arma_garch" && <label className="ios-field">
            <span>Regressors (x, comma-separated)</span>
            <input
              aria-label="independent variables"
              value={x}
              onChange={(event) => setX(event.target.value)}
              placeholder="x1, x2"
            />
          </label>}
          {modelType !== "time_series.arma_garch" && <p className="ios-hint" style={{ marginTop: -4 }}>
            Use the column cards below to add or remove x variables; the text field updates with your selection.
          </p>}
          {modelType !== "time_series.arma_garch" && <FocalSelect
            xColumns={xColumns}
            focal={focal}
            onChange={setFocal}
            family={modelType}
          />}
          {modelType !== "time_series.arma_garch" && preview && (
            <ColumnRolePicker
              columns={preview.columns}
              excludedColumns={preview.excludedColumns}
              y={y}
              xColumns={xColumns}
              onY={setY}
              onX={setXSelection}
            />
          )}
          <button
            type="button"
            data-testid="genesis-save-model"
            onClick={saveModel}
            disabled={!canSaveModel || busy !== null}
          >
            保存模型
          </button>
        </section>
      )}

      {draft && (
        <section className="ios-group">
          <div className="ios-group-label">4. 运行</div>
          {validation && validation.checks.length > 0 && (
            <ul style={{ margin: "0 0 10px", paddingLeft: 18 }}>
              {validation.checks.map((check) => (
                <li key={`${check.code}:${check.message}`} style={{ fontSize: 12 }}>
                  {check.level}: {check.message}
                </li>
              ))}
            </ul>
          )}
          <button
            type="button"
            data-testid="genesis-run"
            onClick={validateAndExecute}
            disabled={!canRun || busy !== null}
          >
            验证并运行
          </button>
        </section>
      )}

      {busy && (
        <div role="status" className="ios-hint">
          {busy === "execute" ? "执行中..." : "处理中..."}
        </div>
      )}
      {error && (
        <div role="alert" className="ios-warning">
          {error}
        </div>
      )}
    </div>
  );
}
