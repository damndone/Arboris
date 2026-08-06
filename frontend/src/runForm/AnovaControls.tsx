/**
 * Entry point for factorial ANOVA and ANCOVA.
 *
 * The sums-of-squares selector starts empty and stays empty until the user
 * chooses. SPSS's GLM reports Type III and R's aov reports Type I, and on an
 * unbalanced design they disagree -- on the repository's fixture SS(factor_a)
 * is 166.74 against 104.05. The backend refuses a run that has not declared the
 * type; pre-selecting one here would hand the user a choice they never made and
 * make that refusal unreachable.
 */

export type AnovaOptionsValue = {
  sums_of_squares: string;
  categorical: string[];
  interactions: string[][];
  posthoc: string;
};

const SS_TYPES = [
  { value: "1", label: "Type I（序贯，R aov 的默认）" },
  { value: "2", label: "Type II（无交互作用时的主效应）" },
  { value: "3", label: "Type III（SPSS GLM 的默认）" },
];

const POSTHOC = [
  { value: "tukey", label: "Tukey HSD" },
  { value: "bonferroni", label: "Bonferroni" },
];

export function emptyAnovaOptions(): AnovaOptionsValue {
  return { sums_of_squares: "", categorical: [], interactions: [], posthoc: "" };
}

export function toAnovaModelOptions(value: AnovaOptionsValue): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    sums_of_squares: Number(value.sums_of_squares),
    categorical: value.categorical,
    interactions: value.interactions,
  };
  // An unset post-hoc is absent, not an empty string: the backend validates the
  // value against a closed set and "" is not one of its members.
  if (value.posthoc) payload.posthoc = value.posthoc;
  return payload;
}

export function AnovaControls(props: {
  columns: string[];
  value: AnovaOptionsValue;
  onChange: (value: AnovaOptionsValue) => void;
}) {
  const set = (patch: Partial<AnovaOptionsValue>) =>
    props.onChange({ ...props.value, ...patch });

  const toggle = (list: string[], item: string) =>
    list.includes(item) ? list.filter((entry) => entry !== item) : [...list, item];

  return (
    <div className="ios-group" aria-label="ANOVA settings">
      <div className="ios-group-label">ANOVA / ANCOVA 设置</div>

      <label className="ios-field">
        <span>平方和类型</span>
        <select
          aria-label="ANOVA sums of squares"
          value={props.value.sums_of_squares}
          onChange={(event) => set({ sums_of_squares: event.target.value })}
        >
          <option value="">请选择</option>
          {SS_TYPES.map((entry) => (
            <option key={entry.value} value={entry.value}>{entry.label}</option>
          ))}
        </select>
      </label>
      <p className="ios-hint" data-testid="anova-ss-help">
        没有默认值，必须自己选。SPSS 的 GLM 默认 Type III，R 的 aov 默认 Type I；
        在非平衡设计下两者给出不同的 F 与 p，替你选一个会让这个差异不可见。
      </p>

      <fieldset className="ios-field">
        <legend>因子（其余列作为协变量）</legend>
        {props.columns.map((column) => (
          <label key={column} className="ios-check">
            <input
              type="checkbox"
              aria-label={`ANOVA factor ${column}`}
              checked={props.value.categorical.includes(column)}
              onChange={() => set({ categorical: toggle(props.value.categorical, column) })}
            />
            <span>{column}</span>
          </label>
        ))}
      </fieldset>

      <label className="ios-check">
        <input
          type="checkbox"
          aria-label="ANOVA interaction"
          checked={props.value.interactions.length > 0}
          onChange={(event) =>
            set({
              interactions:
                event.target.checked && props.value.categorical.length >= 2
                  ? [props.value.categorical.slice(0, 2)]
                  : [],
            })
          }
        />
        <span>纳入前两个因子的交互作用</span>
      </label>

      <label className="ios-field">
        <span>事后比较</span>
        <select
          aria-label="ANOVA post-hoc"
          value={props.value.posthoc}
          onChange={(event) => set({ posthoc: event.target.value })}
        >
          <option value="">不做</option>
          {POSTHOC.map((entry) => (
            <option key={entry.value} value={entry.value}>{entry.label}</option>
          ))}
        </select>
      </label>
      <p className="ios-hint">
        总体 F 只说明存在差异，不说明是哪一对；事后比较回答后一个问题。
      </p>
    </div>
  );
}
