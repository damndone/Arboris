export type LmmControlValue = {
  subject_id: string;
  time: string;
  group: string;
  fit_method: "reml" | "ml";
  random_slope: boolean;
};

export function LmmControls(props: {
  columns: string[];
  value: LmmControlValue;
  onChange: (value: LmmControlValue) => void;
}) {
  const set = (patch: Partial<LmmControlValue>) => props.onChange({ ...props.value, ...patch });
  return (
    <div className="ios-group" aria-label="Linear mixed-effects settings">
      <div className="ios-group-label">重复测量设置</div>
      <label className="ios-field">
        <span>受试者列</span>
        <select aria-label="LMM subject" value={props.value.subject_id} onChange={(event) => set({ subject_id: event.target.value })}>
          <option value="">选择列</option>
          {props.columns.map((column) => <option key={column} value={column}>{column}</option>)}
        </select>
      </label>
      <label className="ios-field">
        <span>时间列</span>
        <select aria-label="LMM time" value={props.value.time} onChange={(event) => set({ time: event.target.value })}>
          <option value="">选择列</option>
          {props.columns.map((column) => <option key={column} value={column}>{column}</option>)}
        </select>
      </label>
      <label className="ios-field">
        <span>组别列</span>
        <select aria-label="LMM group" value={props.value.group} onChange={(event) => set({ group: event.target.value })}>
          <option value="">选择列</option>
          {props.columns.map((column) => <option key={column} value={column}>{column}</option>)}
        </select>
      </label>
      <label className="ios-field">
        <span>拟合方法</span>
        <select aria-label="LMM fit method" value={props.value.fit_method} onChange={(event) => set({ fit_method: event.target.value as LmmControlValue["fit_method"] })}>
          <option value="reml">REML</option>
          <option value="ml">ML</option>
        </select>
      </label>
      <label className="ios-field">
        <input aria-label="LMM random slope" type="checkbox" checked={props.value.random_slope} onChange={(event) => set({ random_slope: event.target.checked })} />
        随机时间斜率
      </label>
    </div>
  );
}
