export type DIDMode = "cohort" | "two_by_two" | "status";

export interface DIDRoleValue {
  mode: DIDMode;
  entity: string;
  time: string;
  cohort: string;
  treat: string;
  post: string;
  status: string;
}

function ColumnSelect(props: {
  label: string; aria: string; columns: string[]; value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="ios-field">
      <span>{props.label}</span>
      <select aria-label={props.aria} value={props.value}
        onChange={(e) => props.onChange(e.target.value)}>
        <option value="">—</option>
        {props.columns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </label>
  );
}

export function DIDControls(props: {
  columns: string[];
  value: DIDRoleValue;
  onChange: (v: DIDRoleValue) => void;
}) {
  const { columns, value, onChange } = props;
  const set = (patch: Partial<DIDRoleValue>) => onChange({ ...value, ...patch });

  return (
    <div className="ios-group" aria-label="DID settings">
      <div className="ios-group-label">DID setup — input mode and role columns</div>
      <label className="ios-field">
        <span>Input mode</span>
        <select aria-label="did-mode" value={value.mode}
          onChange={(e) => set({ mode: e.target.value as DIDMode })}>
          <option value="cohort">Cohort (first treatment period)</option>
          <option value="two_by_two">Classic 2×2 (group + period)</option>
          <option value="status">Treatment status (D_it)</option>
        </select>
      </label>

      <ColumnSelect label="Entity" aria="did-entity" columns={columns}
        value={value.entity} onChange={(v) => set({ entity: v })} />
      <ColumnSelect label="Time" aria="did-time" columns={columns}
        value={value.time} onChange={(v) => set({ time: v })} />
      {value.mode === "cohort" && (
        <ColumnSelect label="First treated period (cohort)" aria="did-cohort" columns={columns}
          value={value.cohort} onChange={(v) => set({ cohort: v })} />
      )}
      {value.mode === "two_by_two" && (
        <>
          <ColumnSelect label="Treated group (treat)" aria="did-treat" columns={columns}
            value={value.treat} onChange={(v) => set({ treat: v })} />
          <ColumnSelect label="Period (post)" aria="did-post" columns={columns}
            value={value.post} onChange={(v) => set({ post: v })} />
        </>
      )}
      {value.mode === "status" && (
        <ColumnSelect label="Treatment status (D_it)" aria="did-status" columns={columns}
          value={value.status} onChange={(v) => set({ status: v })} />
      )}
      <div className="ios-hint" aria-live="polite">
        Requires at least 2 time periods, and at least 1 treated unit plus 1 control (never-treated or not-yet-treated).
      </div>
    </div>
  );
}
