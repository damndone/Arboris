import type { Capabilities } from "../capabilities/types";
import { covarianceDefault } from "./CovarianceSelect";

const PANEL_COVARIANCE_LABELS: Record<string, string> = {
  clustered: "Clustered by entity (default)",
  robust: "Robust, not clustered",
  unadjusted: "Unadjusted",
};

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
  // v1.8.11: the panel family's own covariance options (clustered by default).
  const family = props.capabilities?.model_types?.find((entry) => entry.key === "panel_ols");
  const declared = family?.params?.find((param) => param.key === "covariance")?.options;
  const cov = Array.isArray(declared)
    ? declared.map((option) => {
        const key = typeof option === "string" ? option : String(option.value);
        return { key, label: PANEL_COVARIANCE_LABELS[key] ?? key };
      })
    : props.capabilities?.covariance_options ?? [];
  const covariance = props.covariance || covarianceDefault(props.capabilities, "panel_ols");
  return (
    <div className="ios-group" aria-label="Panel settings">
      <div className="ios-group-label">Panel settings — entity or time</div>
      <div className="ios-row-pair">
        <label className="ios-field">
          <span>Entity column</span>
          <select aria-label="entity" value={props.entity}
            onChange={(e) => props.onEntity(e.target.value)}>
            <option value="">(auto)</option>
            {props.columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="ios-field">
          <span>Time column</span>
          <select aria-label="time" value={props.time}
            onChange={(e) => props.onTime(e.target.value)}>
            <option value="">(auto)</option>
            {props.columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>
      {cov.length > 0 && (
        <label className="ios-field">
          <span>Covariance</span>
          <select aria-label="covariance" value={covariance}
            onChange={(e) => props.onCovariance(e.target.value)}>
            {cov.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
        </label>
      )}
      <div className="ios-hint">Leave both empty and they are detected automatically (backwards compatible)</div>
    </div>
  );
}
