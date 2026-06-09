import type { Capabilities } from "../capabilities/types";

export function PanelControls(props: {
  capabilities: Capabilities | null | undefined;
  columns: string[];
  entity: string;
  time: string;
  covariance: string;
  onEntity: (v: string) => void;
  onTime: (v: string) => void;
  onCovariance: (v: string) => void;
}) {
  const cov = props.capabilities?.covariance_options ?? [];
  return (
    <div className="ios-group" aria-label="Panel settings">
      <div className="ios-group-label">面板设置 · 个体 / 时间二选一</div>
      <div className="ios-row-pair">
        <label className="ios-field">
          <span>个体列 entity</span>
          <select aria-label="entity" value={props.entity}
            onChange={(e) => props.onEntity(e.target.value)}>
            <option value="">(自动)</option>
            {props.columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="ios-field">
          <span>时间列 time</span>
          <select aria-label="time" value={props.time}
            onChange={(e) => props.onTime(e.target.value)}>
            <option value="">(自动)</option>
            {props.columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      {cov.length > 0 && (
        <label className="ios-field">
          <span>标准误 covariance</span>
          <select aria-label="covariance" value={props.covariance}
            onChange={(e) => props.onCovariance(e.target.value)}>
            {cov.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
        </label>
      )}
      <div className="ios-hint">两者都留空 → 自动探测（向后兼容）</div>
    </div>
  );
}
