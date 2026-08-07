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

/**
 * Whether the design controls belong on the form for this family.
 *
 * The answer comes from the server's published list, not from a copy kept here:
 * offering a design to a family whose engine refuses a sampling weight produces
 * a rejection the user cannot act on.
 */
export function surveyDesignApplies(
  capability: SurveyDesignCapability | undefined,
  modelType: string,
): boolean {
  return Boolean(capability?.sampling_weight_families.includes(modelType));
}

const WEIGHT_FRAMES = [
  { value: "cross_sectional", label: "Cross-sectional weight" },
  { value: "longitudinal", label: "Longitudinal weight" },
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
        <option value="">Not declared</option>
        {props.columns.map((column) => (
          <option key={column} value={column}>{column}</option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="ios-group" aria-label="Complex survey design">
      <div className="ios-group-label">Complex survey design</div>

      {columnSelect("Survey strata", "survey_strata_col", "Strata")}
      {columnSelect("Survey PSU", "survey_psu_col", "Primary sampling unit (PSU)")}
      {columnSelect("Survey FPC", "survey_fpc_col", "Finite population correction")}

      <label className="ios-field">
        <span>Replicate-weight method</span>
        <select
          aria-label="Survey replicate type"
          value={props.value.survey_replicate_type}
          onChange={(event) => set({ survey_replicate_type: event.target.value })}
        >
          <option value="">Linearization (default)</option>
          {props.capability.replicate_types.map((kind) => (
            <option key={kind} value={kind}>{kind}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>Single-PSU stratum policy</span>
        <select
          aria-label="Survey lonely PSU policy"
          value={props.value.survey_lonely_psu}
          onChange={(event) => set({ survey_lonely_psu: event.target.value })}
        >
          <option value="">Not declared (treated as fail)</option>
          {props.capability.lonely_psu_policies.map((policy) => (
            <option key={policy} value={policy}>{policy}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>Panel weight frame</span>
        <select
          aria-label="Survey weight frame"
          value={props.value.survey_weight_frame}
          onChange={(event) => set({ survey_weight_frame: event.target.value })}
        >
          <option value="">Not declared</option>
          {WEIGHT_FRAMES.map((frame) => (
            <option key={frame.value} value={frame.value}>{frame.label}</option>
          ))}
        </select>
      </label>

      <label className="ios-field">
        <span>Subpopulation condition</span>
        <input
          aria-label="Survey subpopulation"
          type="text"
          placeholder="e.g. region == 'north'"
          value={props.value.survey_subpop}
          onChange={(event) => set({ survey_subpop: event.target.value })}
        />
      </label>
      <p className="ios-hint">
        A subpopulation is taken on the full design. Filtering the data first understates
        the standard errors while leaving the coefficients unchanged, so the result gives
        no sign that anything went wrong.
      </p>
    </div>
  );
}
