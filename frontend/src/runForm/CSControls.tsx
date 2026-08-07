export interface CSValue {
  controlGroup: "never" | "not_yet";
  estMethod: "dr" | "ipw" | "reg";
  basePeriod: "varying" | "universal";
  anticipation: number;
  clusterVar: string; // "" = cluster by entity
  honestDid: boolean;
}

export function CSControls(props: {
  value: CSValue;
  columns: string[];
  onChange: (v: CSValue) => void;
}) {
  const { value, columns, onChange } = props;
  const set = (patch: Partial<CSValue>) => onChange({ ...value, ...patch });

  return (
    <div className="ios-group" aria-label="CS settings">
      <div className="ios-group-label">
        Callaway-Sant'Anna setup — staggered adoption parameters
      </div>

      <label className="ios-field">
        <span>Control group</span>
        <select
          aria-label="cs-control-group"
          value={value.controlGroup}
          onChange={(e) =>
            set({ controlGroup: e.target.value as CSValue["controlGroup"] })
          }
        >
          <option value="never">Never treated (never)</option>
          <option value="not_yet">Not yet treated (not_yet)</option>
        </select>
      </label>

      <label className="ios-field">
        <span>Estimation method</span>
        <select
          aria-label="cs-est-method"
          value={value.estMethod}
          onChange={(e) =>
            set({ estMethod: e.target.value as CSValue["estMethod"] })
          }
        >
          <option value="dr">Doubly robust (dr)</option>
          <option value="ipw">IPW</option>
          <option value="reg">Outcome regression (reg)</option>
        </select>
      </label>

      <label className="ios-field">
        <span>Base period</span>
        <select
          aria-label="cs-base-period"
          value={value.basePeriod}
          onChange={(e) =>
            set({ basePeriod: e.target.value as CSValue["basePeriod"] })
          }
        >
          <option value="varying">Sequential (varying)</option>
          <option value="universal">Fixed (universal)</option>
        </select>
      </label>

      <label className="ios-field">
        <span>Anticipation periods</span>
        <input
          aria-label="cs-anticipation"
          type="number"
          min={0}
          step={1}
          value={value.anticipation}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            set({ anticipation: Number.isFinite(n) && n >= 0 ? n : 0 });
          }}
        />
      </label>

      <label className="ios-field">
        <span>Cluster variable (optional)</span>
        <select
          aria-label="cs-cluster-var"
          value={value.clusterVar}
          onChange={(e) => set({ clusterVar: e.target.value })}
        >
          <option value="">By entity (default)</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <label className="ios-row">
        <span>honest-DID sensitivity (Rambachan-Roth)</span>
        <input
          type="checkbox"
          aria-label="cs-honest-did"
          checked={value.honestDid}
          onChange={(e) => set({ honestDid: e.target.checked })}
        />
      </label>
    </div>
  );
}
