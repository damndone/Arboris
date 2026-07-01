// frontend/src/runForm/FocalSelect.tsx
//
// V1.6.5 — focal declaration on the run form (Plan §7 / Phase E1).
//
// Lets the user mark a subset of the explanatory columns (x) as the *focal*
// explanatory variables — the coefficients they actually care about — so the
// role layer can distinguish focal from covariates. Renders nothing for
// causal families (IV / DID / CS / SA / dCDH), where focal/treatment is
// structural and declared elsewhere, not a free-form pick.

/** Families where focal/treatment is structural — no free-form focal pick. */
const STRUCTURAL_FOCAL_FAMILIES = new Set([
  "iv",
  "did",
  "cs_did",
  "sa_did",
  "dcdh",
]);

export interface FocalSelectProps {
  xColumns: string[];
  focal: string[];
  onChange: (focal: string[]) => void;
  family?: string;
}

export function FocalSelect({ xColumns, focal, onChange, family }: FocalSelectProps) {
  if (family && STRUCTURAL_FOCAL_FAMILIES.has(family)) return null;
  if (xColumns.length === 0) return null;

  const toggle = (col: string) => {
    const next = focal.includes(col)
      ? focal.filter((c) => c !== col)
      : [...focal, col];
    onChange(next);
  };

  return (
    <fieldset
      data-testid="focal-select"
      style={{ border: 0, padding: 0, margin: 0 }}
    >
      <legend
        style={{
          fontSize: 11,
          color: "var(--label-secondary)",
          marginBottom: 4,
          padding: 0,
        }}
      >
        Focal explanatory variable(s) — optional
      </legend>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {xColumns.map((col) => (
          <label
            key={col}
            style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12 }}
          >
            <input
              type="checkbox"
              aria-label={col}
              checked={focal.includes(col)}
              onChange={() => toggle(col)}
            />
            {col}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
