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
        <span>Also run a prediction model</span>
        <input type="checkbox" aria-label="prediction" className="ios-switch"
          checked={props.enabled}
          onChange={(e) => props.onEnabled(e.target.checked)} />
      </label>
      {props.enabled && (
        <>
          <label className="ios-field">
            <span>Algorithm</span>
            <select aria-label="algorithm" value={props.modelType}
              onChange={(e) => props.onModelType(e.target.value)}>
              <option value="">(select)</option>
              {models.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          </label>
          <label className="ios-field">
            <span>Cross-validation folds</span>
            <input type="number" aria-label="cv_folds" min={2} max={20} value={props.cvFolds}
              onChange={(e) => props.onCvFolds(Number(e.target.value) || 5)} />
          </label>
          <label className="ios-field">
            <span>Final holdout fraction</span>
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
            <span>Data structure</span>
            <select aria-label="data structure" value={dataStructure}
              onChange={(e) => setDataStructure(e.target.value)}>
              <option value="unknown">(must be declared)</option>
              <option value="iid">IID / independent and identically distributed</option>
              <option value="grouped">Grouped</option>
              <option value="temporal">Temporal / time series</option>
              <option value="panel">Panel</option>
            </select>
          </label>
          {dataStructure === "grouped" && (
            <label className="ios-field">
              <span>Group column</span>
              <select aria-label="group column" value={props.groupColumn ?? ""}
                onChange={(e) => setGroupColumn(e.target.value)}>
                <option value="">(select)</option>
                {columns.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </label>
          )}
          {dataStructure === "panel" && (
            <label className="ios-field">
              <span>Entity column</span>
              <select aria-label="entity column" value={props.entityColumn ?? ""}
                onChange={(e) => setEntityColumn(e.target.value)}>
                <option value="">(select)</option>
                {columns.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </label>
          )}
          {(dataStructure === "temporal" || dataStructure === "panel") && (
            <label className="ios-field">
              <span>Time column</span>
              <select aria-label="time column" value={props.timeColumn ?? ""}
                onChange={(e) => setTimeColumn(e.target.value)}>
                <option value="">(select)</option>
                {columns.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </label>
          )}
          {sampling.length > 0 && (
            <label className="ios-field">
              <span>Imbalance sampling</span>
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
