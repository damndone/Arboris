import type { SurveyDesignCapability } from "../capabilities/types";

/**
 * Entry point for the complex-survey design declarations.
 *
 * The option sets are read from `/capabilities` rather than restated here. The
 * backend publishes which replicate types and single-PSU policies it can
 * actually execute, and a local copy would drift out of step the first time one
 * is added or withdrawn, with the form quietly offering something the engine
 * refuses.
 */

export type SurveyDesignValue = {
  survey_strata_col: string;
  survey_psu_col: string;
  survey_fpc_col: string;
  survey_replicate_weights: string[];
  survey_replicate_type: string;
  survey_lonely_psu: string;
  survey_weight_frame: string;
  survey_subpop: string;
};

export function emptySurveyDesign(): SurveyDesignValue {
  // Nothing is pre-filled. The backend refuses a sampling weight without a
  // declared design, and a form that arrived already declaring one would make
  // that refusal read as a product defect rather than a missing input.
  return {
    survey_strata_col: "",
    survey_psu_col: "",
    survey_fpc_col: "",
    survey_replicate_weights: [],
    survey_replicate_type: "",
    survey_lonely_psu: "",
    survey_weight_frame: "",
    survey_subpop: "",
  };
}

export function hasSurveyDesign(value: SurveyDesignValue): boolean {
  return Boolean(value.survey_strata_col.trim() || value.survey_psu_col.trim());
}

const WEIGHT_FRAMES = [
  { value: "cross_sectional", label: "横截面权重" },
  { value: "longitudinal", label: "纵向权重" },
];

export function SurveyDesignControls(props: {
  columns: string[];
  capability: SurveyDesignCapability;
  value: SurveyDesignValue;
  onChange: (value: SurveyDesignValue) => void;
}) {
  const set = (patch: Partial<SurveyDesignValue>) =>
    props.onChange({ ...props.value, ...patch });

  const columnSelect = (
    label: string,
    key: "survey_strata_col" | "survey_psu_col" | "survey_fpc_col",
    caption: string,
  ) => (
    <label className="ios-field">
      <span>{caption}</span>
      <select
        aria-label={label}
        value={props.value[key]}
        onChange={(event) => set({ [key]: event.target.value } as Partial<SurveyDesignValue>)}
      >
        <option value="">未声明</option>
        {props.columns.map((column) => (
          <option key={column} value={column}>{column}</option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="ios-group" aria-label="Complex survey design">
      <div className="ios-group-label">复杂抽样设计</div>

      {columnSelect("Survey strata", "survey_strata_col", "分层变量")}
      {columnSelect("Survey PSU", "survey_psu_col", "初级抽样单元 (PSU)")}
      {columnSelect("Survey FPC", "survey_fpc_col", "有限总体校正")}

      <label className="ios-field">
        <span>重复权重方法</span>
        <select
          aria-label="Survey replicate type"
          value={props.value.survey_replicate_type}
          onChange={(event) => set({ survey_replicate_type: event.target.value })}
        >
          <option value="">线性化（默认）</option>
          {props.capability.replicate_types.map((kind) => (
            <option key={kind} value={kind}>{kind}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>单 PSU 层处理</span>
        <select
          aria-label="Survey lonely PSU policy"
          value={props.value.survey_lonely_psu}
          onChange={(event) => set({ survey_lonely_psu: event.target.value })}
        >
          <option value="">未声明（按 fail 处理）</option>
          {props.capability.lonely_psu_policies.map((policy) => (
            <option key={policy} value={policy}>{policy}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>面板权重语义</span>
        <select
          aria-label="Survey weight frame"
          value={props.value.survey_weight_frame}
          onChange={(event) => set({ survey_weight_frame: event.target.value })}
        >
          <option value="">未声明</option>
          {WEIGHT_FRAMES.map((frame) => (
            <option key={frame.value} value={frame.value}>{frame.label}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>子总体条件</span>
        <input
          aria-label="Survey subpopulation"
          type="text"
          placeholder="例如 region == 'north'"
          value={props.value.survey_subpop}
          onChange={(event) => set({ survey_subpop: event.target.value })}
        />
      </label>
      <p className="ios-hint">
        子总体在完整设计上取子集。先筛数据再分析会低估标准误，而系数不变，所以结果看不出异常。
      </p>
    </div>
  );
}
