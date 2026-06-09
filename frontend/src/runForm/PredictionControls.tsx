import type { Capabilities } from "../capabilities/types";

export function PredictionControls(props: {
  capabilities: Capabilities | undefined;
  enabled: boolean;
  modelType: string;
  cvFolds: number;
  sampling: string;
  onEnabled: (v: boolean) => void;
  onModelType: (v: string) => void;
  onCvFolds: (v: number) => void;
  onSampling: (v: string) => void;
}) {
  const models = props.capabilities?.prediction_models ?? [];
  const sampling = props.capabilities?.sampling_methods ?? [];
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
