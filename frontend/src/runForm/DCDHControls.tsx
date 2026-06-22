export interface DCDHValue {
  entity: string;
  time: string;
  treatmentPath: string; // the per-(unit,period) D_it column (0/1, may switch on AND off)
  clusterVar: string; // "" = cluster by entity
}

// Role assignment for de Chaisemartin-D'Haultfoeuille (non-absorbing DID).
// Distinct from cohort/adoption-time controls: treatmentPath is the raw per-row
// treatment status D_it, NOT a first-treatment cohort.
export function DCDHControls(props: {
  value: DCDHValue;
  columns: string[];
  onChange: (v: DCDHValue) => void;
}) {
  const { value, columns, onChange } = props;
  const set = (patch: Partial<DCDHValue>) => onChange({ ...value, ...patch });

  return (
    <div className="ios-group" aria-label="dCDH settings">
      <div className="ios-group-label">
        de Chaisemartin-D'Haultfœuille 设定 · 二元非吸收（可开可关）处理
      </div>

      <label className="ios-field">
        <span>实体列 (entity)</span>
        <select
          aria-label="dcdh-entity"
          value={value.entity}
          onChange={(e) => set({ entity: e.target.value })}
        >
          <option value="">选择实体列…</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>时间列 (time)</span>
        <select
          aria-label="dcdh-time"
          value={value.time}
          onChange={(e) => set({ time: e.target.value })}
        >
          <option value="">选择时间列…</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>处理路径列 (treatment D_it, 0/1)</span>
        <select
          aria-label="dcdh-treatment-path"
          value={value.treatmentPath}
          onChange={(e) => set({ treatmentPath: e.target.value })}
        >
          <option value="">选择处理列…</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>聚类变量 (cluster, 选填)</span>
        <select
          aria-label="dcdh-cluster-var"
          value={value.clusterVar}
          onChange={(e) => set({ clusterVar: e.target.value })}
        >
          <option value="">按实体 (entity, 默认)</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <div className="ios-hint" aria-label="dcdh-precheck-note">
        分析样本 = baseline=0 且首次切换为 0→1 的 switchers（首次切换后可再 1→0，仍纳入）。
        baseline=1 单位将被排除。此处为预检说明，最终样本与计数以后端 diagnostics 为准 (pre-check)。
      </div>
    </div>
  );
}
