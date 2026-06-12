export interface IVRoleValue {
  endog: string[];
  instruments: string[];
}

type Role = "exog" | "endog" | "instrument";

function roleOf(col: string, value: IVRoleValue): Role {
  if (value.endog.includes(col)) return "endog";
  if (value.instruments.includes(col)) return "instrument";
  return "exog";
}

export function IVControls(props: {
  columns: string[];
  value: IVRoleValue;
  onChange: (v: IVRoleValue) => void;
}) {
  const { columns, value, onChange } = props;

  function assign(col: string, role: Role): void {
    // Remove the column from any current role, then append to its new role.
    // Existing assignment order is preserved; the reassigned column lands last.
    const endog = value.endog.filter((c) => c !== col);
    const instruments = value.instruments.filter((c) => c !== col);
    if (role === "endog") endog.push(col);
    if (role === "instrument") instruments.push(col);
    onChange({ endog, instruments });
  }

  const nEndog = value.endog.length;
  const nInstr = value.instruments.length;
  let badge: string;
  if (nEndog === 0) {
    badge = "请指派至少一个内生变量";
  } else if (nInstr < nEndog) {
    badge = "欠识别 under-identified（工具数 < 内生数）";
  } else if (nInstr === nEndog) {
    badge = "恰好识别 just-identified";
  } else {
    badge = "过度识别 over-identified";
  }

  return (
    <div className="ios-group" aria-label="IV settings">
      <div className="ios-group-label">IV 设定 · 给每个变量指派角色</div>
      {columns.map((col) => (
        <label className="ios-field" key={col}>
          <span>{col}</span>
          <select
            aria-label={`role-${col}`}
            value={roleOf(col, value)}
            onChange={(e) => assign(col, e.target.value as Role)}
          >
            <option value="exog">外生控制</option>
            <option value="endog">内生</option>
            <option value="instrument">工具</option>
          </select>
        </label>
      ))}
      <div className="ios-hint" aria-label="iv-identification" aria-live="polite">{badge}</div>
    </div>
  );
}
