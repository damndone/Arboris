import type { Capabilities } from "../capabilities/types";

export function PredictionControls(props: {
  capabilities: Capabilities | null | undefined;
  enabled: boolean;
  modelType: string;
  cvFolds: number;
  sampling: string;
  columns?: string[];
  dataStructure?: string;
  entityColumn?: string;
  groupColumn?: string;
  timeColumn?: string;
  finalHoldoutFraction?: number;
  shuffle?: boolean;
  onEnabled: (v: boolean) => void;
  onModelType: (v: string) => void;
  onCvFolds: (v: number) => void;
  onSampling: (v: string) => void;
  onDataStructure?: (v: string) => void;
  onEntityColumn?: (v: string) => void;
  onGroupColumn?: (v: string) => void;
  onTimeColumn?: (v: string) => void;
  onFinalHoldoutFraction?: (v: number) => void;
  onShuffle?: (v: boolean) => void;
}) {
  const models = props.capabilities?.prediction_models ?? [];
  const sampling = props.capabilities?.sampling_methods ?? [];
  const columns = props.columns ?? [];
  const dataStructure = props.dataStructure ?? "unknown";
  const setDataStructure = props.onDataStructure ?? (() => undefined);
  const setEntityColumn = props.onEntityColumn ?? (() => undefined);
  const setGroupColumn = props.onGroupColumn ?? (() => undefined);
  const setTimeColumn = props.onTimeColumn ?? (() => undefined);
  const setFinalHoldoutFraction = props.onFinalHoldoutFraction ?? (() => undefined);
  const setShuffle = props.onShuffle ?? (() => undefined);
  if (models.length === 0) return null;
  return (
    <div className="ios-group" aria-label="Forecast settings">
      <label className="ios-row">
        <span>同时跑预测模型</span>
        <input type="checkbox" aria-label="prediction" className="ios-switch"
          checked={props.enabled}
          onChange={(e) => props.onEnabled(e.target.checked)} />
      </label>
      {props.enabled && (
        <>
          <label className="ios-field">
            <span>算法 algorithm</span>
            <select aria-label="algorithm" value={props.modelType}
              onChange={(e) => props.onModelType(e.target.value)}>
              <option value="">(选择)</option>
              {models.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          </label>
          <label className="ios-field">
            <span>交叉验证折数 cv_folds</span>
            <input type="number" aria-label="cv_folds" min={2} max={20} value={props.cvFolds}
              onChange={(e) => props.onCvFolds(Number(e.target.value) || 5)} />
          </label>
          <label className="ios-field">
            <span>最终留出比例 final holdout</span>
            <input type="number" aria-label="final holdout fraction" min={0.1} max={0.5} step={0.05}
              value={props.finalHoldoutFraction ?? 0.2}
              onChange={(e) => setFinalHoldoutFraction(Number(e.target.value) || 0.2)} />
          </label>
          <label className="ios-row">
            <span>IID / grouped split shuffle</span>
            <input type="checkbox" aria-label="prediction shuffle" className="ios-switch"
              checked={props.shuffle ?? true}
              onChange={(e) => setShuffle(e.target.checked)} />
          </label>
          <label className="ios-field">
            <span>数据结构 data structure</span>
            <select aria-label="data structure" value={dataStructure}
              onChange={(e) => setDataStructure(e.target.value)}>
              <option value="unknown">(必须声明)</option>
              <option value="iid">IID / 独立同分布</option>
              <option value="grouped">Grouped / 分组</option>
              <option value="temporal">Temporal / 时间序列</option>
              <option value="panel">Panel / 面板</option>
            </select>
          </label>
          {dataStructure === "grouped" && (
            <label className="ios-field">
              <span>分组列 group column</span>
              <select aria-label="group column" value={props.groupColumn ?? ""}
                onChange={(e) => setGroupColumn(e.target.value)}>
                <option value="">(选择)</option>
                {columns.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </label>
          )}
          {dataStructure === "panel" && (
            <label className="ios-field">
              <span>个体列 entity column</span>
              <select aria-label="entity column" value={props.entityColumn ?? ""}
                onChange={(e) => setEntityColumn(e.target.value)}>
                <option value="">(选择)</option>
                {columns.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </label>
          )}
          {(dataStructure === "temporal" || dataStructure === "panel") && (
            <label className="ios-field">
              <span>时间列 time column</span>
              <select aria-label="time column" value={props.timeColumn ?? ""}
                onChange={(e) => setTimeColumn(e.target.value)}>
                <option value="">(选择)</option>
                {columns.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </label>
          )}
          {sampling.length > 0 && (
            <label className="ios-field">
              <span>不平衡采样 sampling</span>
              <select aria-label="sampling" value={props.sampling}
                onChange={(e) => props.onSampling(e.target.value)}>
                <option value="">(none)</option>
                {sampling.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
              </select>
            </label>
          )}
        </>
      )}
    </div>
  );
}
