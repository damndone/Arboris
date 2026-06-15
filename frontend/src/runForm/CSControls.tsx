export interface CSValue {
  controlGroup: "never" | "not_yet";
  estMethod: "dr" | "ipw" | "reg";
  basePeriod: "varying" | "universal";
  anticipation: number;
  clusterVar: string; // "" = default (cluster by entity)
}

export function CSControls(props: {
  columns: string[];
  value: CSValue;
  onChange: (v: CSValue) => void;
}) {
  const { columns, value, onChange } = props;
  const set = (patch: Partial<CSValue>) => onChange({ ...value, ...patch });

  return (
    <div className="ios-group" aria-label="CS settings">
      <div className="ios-group-label">
        Callaway-Sant'Anna 设定 · 交错处理估计参数
      </div>

      <label className="ios-field">
        <span>对照组</span>
        <select
          aria-label="cs-control-group"
          value={value.controlGroup}
          onChange={(e) =>
            set({ controlGroup: e.target.value as CSValue["controlGroup"] })
          }
        >
          <option value="never">从不处理 (never)</option>
          <option value="not_yet">尚未处理 (not_yet)</option>
        </select>
      </label>

      <label className="ios-field">
        <span>估计法</span>
        <select
          aria-label="cs-est-method"
          value={value.estMethod}
          onChange={(e) =>
            set({ estMethod: e.target.value as CSValue["estMethod"] })
          }
        >
          <option value="dr">双重稳健 (dr)</option>
          <option value="ipw">IPW</option>
          <option value="reg">结果回归 (reg)</option>
        </select>
      </label>

      <label className="ios-field">
        <span>基期</span>
        <select
          aria-label="cs-base-period"
          value={value.basePeriod}
          onChange={(e) =>
            set({ basePeriod: e.target.value as CSValue["basePeriod"] })
          }
        >
          <option value="varying">序贯 (varying)</option>
          <option value="universal">固定 (universal)</option>
        </select>
      </label>

      <label className="ios-field">
        <span>预期期数 (anticipation)</span>
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
        <span>聚类变量 (cluster)</span>
        <select
          aria-label="cs-cluster-var"
          value={value.clusterVar}
          onChange={(e) => set({ clusterVar: e.target.value })}
        >
          <option value="">默认按个体聚类</option>
          {columns.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
