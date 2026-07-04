import { useEffect, useMemo, useState } from "react";
import {
  createGenesisDraft,
  executePipelineDraft,
  getPipelineDraft,
  listPipelineDrafts,
  patchDraftNode,
  previewFile,
  uploadDataset,
  validatePipelineDraft,
  type DraftExecutionResult,
  type DraftValidationResult,
  type FilePreview,
  type PipelineDraftNode,
  type PipelineDraftResponse,
  type PipelineDraftV1,
} from "../../api";
import { useCapabilities } from "../../capabilities/useCapabilities";
import { ModelTypeSelect } from "../../runForm/ModelTypeSelect";
import { ImputationControls } from "../../runForm/ImputationControls";
import { PanelControls } from "../../runForm/PanelControls";
import { PredictionControls } from "../../runForm/PredictionControls";
import { FocalSelect } from "../../runForm/FocalSelect";

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
  const [predictionEnabled, setPredictionEnabled] = useState(false);
  const [predictionModelType, setPredictionModelType] = useState("");
  const [predictionCvFolds, setPredictionCvFolds] = useState(5);
  const [predictionSampling, setPredictionSampling] = useState("");
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
    setModelType((current) => firstString(modelParams.model_type) || model?.model_type || current);
    const nextY = firstString(modelParams.y);
    if (nextY) setY(nextY);
    const modelX = stringList(modelParams.x);
    if (modelX.length > 0) setX(modelX.join(", "));
    const modelFocal = stringList(modelParams.focal_x);
    if (modelFocal.length > 0) setFocal(modelFocal);
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
        params: { sheet_name: sheetName, transpose },
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
    const params: Record<string, unknown> = {
      model_type: modelType,
      y: y.trim(),
      x: xColumns,
    };
    if (imputationMethod) params.imputation = JSON.stringify({ method: imputationMethod });
    if (modelType === "panel_ols") {
      if (entityCol) params.entity_col = entityCol;
      if (timeCol) params.time_col = timeCol;
      if (covariance) params.covariance = covariance;
    }
    if (predictionEnabled) {
      if (predictionModelType) params.prediction_model_type = predictionModelType;
      params.prediction_cv_folds = predictionCvFolds;
      if (predictionSampling) params.prediction_sampling_method = predictionSampling;
    }
    if (focal.length > 0) params.focal_x = focal.filter((col) => xColumns.includes(col));
    return params;
  }

  async function saveModel() {
    if (!draft) return;
    if (!y.trim() || xColumns.length === 0) {
      setError("请选择 y，并至少选择一个 x。");
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
  const canSaveTable = Boolean(draftId && sheetName);
  const canSaveModel = Boolean(draftId && tableConfigured && y.trim() && xColumns.length > 0);
  const canRun = Boolean(draftId && modelConfigured);

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
          <PredictionControls
            capabilities={capabilities}
            enabled={predictionEnabled}
            modelType={predictionModelType}
            cvFolds={predictionCvFolds}
            sampling={predictionSampling}
            onEnabled={setPredictionEnabled}
            onModelType={setPredictionModelType}
            onCvFolds={setPredictionCvFolds}
            onSampling={setPredictionSampling}
          />
          <label className="ios-field">
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
          </label>
          <label className="ios-field">
            <span>Regressors (x, comma-separated)</span>
            <input
              aria-label="independent variables"
              value={x}
              onChange={(event) => setX(event.target.value)}
              placeholder="x1, x2"
            />
          </label>
          <FocalSelect
            xColumns={xColumns}
            focal={focal}
            onChange={setFocal}
            family={modelType}
          />
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
