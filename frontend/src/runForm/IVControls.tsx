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
    badge = "Assign at least one endogenous variable";
  } else if (nInstr < nEndog) {
    badge = "Under-identified (fewer instruments than endogenous variables)";
  } else if (nInstr === nEndog) {
    badge = "Just-identified";
  } else {
    badge = "Over-identified";
  }

  return (
    <div className="ios-group" aria-label="IV settings">
      <div className="ios-group-label">IV setup — assign a role to each variable</div>
      {columns.map((col) => (
        <label className="ios-field" key={col}>
          <span>{col}</span>
          <select
            aria-label={`role-${col}`}
            value={roleOf(col, value)}
            onChange={(e) => assign(col, e.target.value as Role)}
          >
            <option value="exog">Exogenous control</option>
            <option value="endog">Endogenous</option>
            <option value="instrument">Instrument</option>
          </select>
        </label>
      ))}
      <div className="ios-hint" aria-label="iv-identification" aria-live="polite">{badge}</div>
    </div>
  );
}
