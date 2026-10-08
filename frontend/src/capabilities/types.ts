/** Capability catalog types, generated from the backend's declarations
 *  (backend/workbench/http/responses/system.py). */
import type { Schema } from "../apiTypes";

export type ModelGroup = Schema<"ModelTypeEntry">["group"];
export type EditableControlSpec = Schema<"EditableControlSpec">;
export type ModelTypeEntry = Schema<"ModelTypeEntry">;
export type ImputationMethodEntry = Schema<"KeyedEntry">;
export type PredictionModelEntry = Schema<"KeyedEntry">;
export type SamplingMethodEntry = Schema<"SamplingMethodEntry">;
/** The backend marks the default option explicitly; consumers must read this
 *  flag rather than assuming `options[0]` (reordering must not change SE). */
export type CovarianceOption = Schema<"CovarianceOption">;
/** Published so the form can derive what composes instead of restating it. */
export type SurveyDesignCapability = Schema<"SurveyDesignCapability">;
export type Capabilities = Schema<"Capabilities">;
