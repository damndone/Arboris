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
      <div className="ios-group-label">DID 设定 · 选择输入模式与角色列</div>
      <label className="ios-field">
        <span>输入模式</span>
        <select aria-label="did-mode" value={value.mode}
          onChange={(e) => set({ mode: e.target.value as DIDMode })}>
          <option value="cohort">队列(首次处理时点)</option>
          <option value="two_by_two">经典 2×2(组 + 期)</option>
          <option value="status">处理状态(D_it)</option>
        </select>
      </label>

      <ColumnSelect label="个体 (entity)" aria="did-entity" columns={columns}
        value={value.entity} onChange={(v) => set({ entity: v })} />
      <ColumnSelect label="时间 (time)" aria="did-time" columns={columns}
        value={value.time} onChange={(v) => set({ time: v })} />
      {value.mode === "cohort" && (
        <ColumnSelect label="首次处理时点 (cohort)" aria="did-cohort" columns={columns}
          value={value.cohort} onChange={(v) => set({ cohort: v })} />
      )}
      {value.mode === "two_by_two" && (
        <>
          <ColumnSelect label="处理组 (treat)" aria="did-treat" columns={columns}
            value={value.treat} onChange={(v) => set({ treat: v })} />
          <ColumnSelect label="时期 (post)" aria="did-post" columns={columns}
            value={value.post} onChange={(v) => set({ post: v })} />
        </>
      )}
      {value.mode === "status" && (
        <ColumnSelect label="处理状态 (D_it)" aria="did-status" columns={columns}
          value={value.status} onChange={(v) => set({ status: v })} />
      )}
      <div className="ios-hint" aria-live="polite">
        需要 ≥2 个时间期,且至少 1 个处理单位 + 1 个对照(从不处理/尚未处理)。
      </div>
    </div>
  );
}
