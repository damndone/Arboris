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
        de Chaisemartin-D'Haultfœuille setup — binary non-absorbing (switching) treatment
      </div>

      <label className="ios-field">
        <span>Entity column</span>
        <select
          aria-label="dcdh-entity"
          value={value.entity}
          onChange={(e) => set({ entity: e.target.value })}
        >
          <option value="">Select the entity column…</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>Time column</span>
        <select
          aria-label="dcdh-time"
          value={value.time}
          onChange={(e) => set({ time: e.target.value })}
        >
          <option value="">Select the time column…</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>Treatment path column (D_it, 0/1)</span>
        <select
          aria-label="dcdh-treatment-path"
          value={value.treatmentPath}
          onChange={(e) => set({ treatmentPath: e.target.value })}
        >
          <option value="">Select the treatment column…</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>Cluster variable (optional)</span>
        <select
          aria-label="dcdh-cluster-var"
          value={value.clusterVar}
          onChange={(e) => set({ clusterVar: e.target.value })}
        >
          <option value="">By entity (default)</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <div className="ios-hint" aria-label="dcdh-precheck-note">
        Analysis sample = switchers with baseline 0 whose first switch is 0→1 (a later 1→0 switch keeps them in).
        Units with baseline 1 are excluded. This is a pre-check note; the backend diagnostics are authoritative for the final sample and counts.
      </div>
    </div>
  );
}
