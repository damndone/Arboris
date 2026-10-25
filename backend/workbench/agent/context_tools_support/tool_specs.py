"""Static descriptors of the Agent's context tools: ids, schemas, budgets and descriptions.

Handlers stay in registration.py; this module only holds what the model reads.
"""

from __future__ import annotations

from typing import Any


def chain_tool_specs(*, top_level_operation_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Static fields of each chain-scope tool, by tool id, in list order."""
    return {
        "export_analysis_script": dict(
            tool_id="export_analysis_script",
            version="v1",
            side_effect="artifact",
            scope_requirements=("project", "chain"),
            max_output_budget=16384,
            input_schema={"type": "object", "required": ["run_id", "target", "language"],
                "properties": {"run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "target": {"type": "string", "minLength": 1, "maxLength": 300,
                        "description": "Completed model node model:<artifact_id> or recorded post-estimation artifact:<artifact_id>."},
                    "language": {"type": "string", "enum": ["stata", "r", "python"]},
                    "require_native": {"type": "boolean", "default": False}}, "additionalProperties": False},
            description="Export the completed analysis path to a local Stata, R or Python script bundle with source data, snapshots and closing numeric self-checks. Report every snapshot coverage reason; require_native refuses before writing if any step requires a snapshot. Returns download and coverage metadata only; never share the local bundle with the model or a remote provider.",
        ),
        "export_dataset": dict(
            tool_id="export_dataset",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["run_id", "node_id", "format"],
                "properties": {
                    "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "node_id": {"type": "string", "minLength": 1, "maxLength": 300},
                    "format": {"type": "string", "enum": ["sav", "zsav", "dta", "csv", "xlsx"]},
                    "columns": {
                        "type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1,
                        "description": "Variables to export, in this order; all when omitted.",
                    },
                    "filters": {
                        "type": "array", "maxItems": 20, "items": {"type": "object"},
                        "description": "Rows to keep, in data.subset filter form {column, op, value}.",
                    },
                    "dta_version": {
                        "type": "integer", "enum": [13, 14, 15],
                        "description": "13 = Stata 13; 14 = Stata 14-18 (default); 15 = over 32,767 variables.",
                    },
                    "value_labels": {
                        "type": "string", "enum": ["labels", "strings", "none"],
                        "description": "labels: codes with label sets; strings: label text instead of codes; none: codes only.",
                    },
                    "missing_codes": {
                        "type": "string", "enum": ["as_missing", "keep_codes"],
                        "description": "as_missing: declared missing codes become missing; keep_codes: keep them as values.",
                    },
                    "filename": {"type": "string", "minLength": 1, "maxLength": 120},
                },
                "additionalProperties": False,
            },
            side_effect="artifact",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
            description="Write one dataset node (e.g. stage:raw, stage:cleaned or a derived "
                "dataset) as SPSS (.sav/.zsav), Stata (.dta), CSV or Excel, with its "
                "declared labels -- choosing the variables, the rows, the Stata "
                "version, how value labels and missing codes are written, and the "
                "file name when the user asks. Creates a downloadable file only; "
                "changes no data or results. Report every item in notes to the user: "
                "they are labels or missing codes the format could not hold.",
        ),
        "list_project_datasets": dict(
            tool_id="list_project_datasets",
            version="v1",
            input_schema={
                "type": "object",
                "properties": {
                    "detail_for": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "required": ["run_id", "node_id"],
                            "properties": {
                                "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                                "node_id": {"type": "string", "minLength": 1, "maxLength": 300},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=16384,
            description="List real graph-backed dataset run/node/artifact identities. "
                "Use detail_for for at most eight datasets when dtype, unique-count, "
                "and nonzero missing-rate facts are needed.",
        ),
        "inspect_data_schema": dict(
            tool_id="inspect_data_schema",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "inspect_completed_operations": dict(
            tool_id="inspect_completed_operations",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "inspect_notebook_workflow_results": dict(
            tool_id="inspect_notebook_workflow_results",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "inspect_operation_artifact": dict(
            tool_id="inspect_operation_artifact",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                    "operation_record_id",
                    "artifact_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                    "operation_record_id": {"type": "string"},
                    "artifact_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "inspect_analysis_loop_context": dict(
            tool_id="inspect_analysis_loop_context",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["scope", "source_context"],
                "properties": {
                    "scope": {
                        "type": "string",
                        "enum": ["inspect", "plan", "validation", "compare"],
                    },
                    "source_context": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                    "plan_diff": {"type": "object"},
                    "validation_packet": {"type": "object"},
                    "compare_packet": {"type": "object"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "submit_analysis_loop_intent": dict(
            tool_id="submit_analysis_loop_intent",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["intent"],
                "properties": {
                    "intent": {
                        "type": "object",
                        "additionalProperties": True,
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "inspect_node_context": dict(
            tool_id="inspect_node_context",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "inspect_operation_contract": dict(
            tool_id="inspect_operation_contract",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                    "operation_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                    # Enumerate the registered operation identities so the
                    # model cannot guess ("rerun"/"run"/"ols" — observed in
                    # the live DeepSeek smoke) and fail closed repeatedly.
                    "operation_id": {
                        "type": "string",
                        "enum": top_level_operation_ids,
                    },
                    "operation_version": {"type": "string"},
                    "step_operation_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 12,
                        "description": (
                            "operation.multi_step only: the step operations you will use. Their full "
                            "specifications are returned; without this you get a one-line index of every step. "
                            "The protocol's step reference already holds the most-used steps."
                        ),
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            # Schema, not data. This tool returns the live workflow-step
            # vocabulary, including every registered P7 operation. A bounded
            # 12K projection kept only the first step entries and
            # made the rest unreachable in a real Agent turn. Nested P7
            # request schemas are now part of the declaration-derived
            # contract, so the live 74-step vocabulary is larger; keep a
            # generous explicit cap below the model context window while
            # ensuring the contract remains whole.
            # The full vocabulary is no longer returned whole: an index, or
            # the specifications of the steps asked for (v1.9.1).
            max_output_budget=65536,
        ),
        "inspect_diagnostics": dict(
            tool_id="inspect_diagnostics",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "inspect_design_advisories": dict(
            tool_id="inspect_design_advisories",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
            description="Read what this run assumed and could not verify: measurement "
                "levels that were never declared (an integer rating analysed as "
                "a count) -- split into `measurement_advisories`, which the "
                "evidence supports declaring, and `measurement_uncertain`, "
                "which you must ask about rather than declare. Also columns "
                "that look like an undeclared sampling design, "
                "the design effect and effective sample size, and extreme "
                "sampling weights. Every figure here was computed by the engine "
                "-- quote these values rather than deriving your own, and present "
                "them as observations and questions, never as a verdict on the "
                "user's conclusions.",
        ),
        "inspect_statistical_evidence": dict(
            tool_id="inspect_statistical_evidence",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
            description="Read the run's statistical evidence packet: ANOVA post-hoc "
                "comparisons with their correction method (Tukey, Bonferroni), "
                "Cohen's d, eta squared, omega squared, and the Levene, Bartlett "
                "and Shapiro-Wilk assumption checks. Call this for any question "
                "about statistical tests, effect sizes, post-hoc multiple "
                "comparisons or assumption checks on a completed run.",
        ),
        "inspect_result_summary": dict(
            tool_id="inspect_result_summary",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
            description="Read the persisted result summary for one model node: model "
                "identity, fit metrics, coefficient rows, the regression table, "
                "model-family evidence, and the run's statistical evidence packet "
                "(ANOVA post-hoc comparisons and their correction method, Cohen's d, "
                "eta squared, omega squared, Levene, Bartlett and Shapiro-Wilk). "
                "Use this whenever the question is about statistical tests, effect "
                "sizes, post-hoc comparisons or assumption checks for a completed run.",
        ),
        "inspect_project_model_coefficients": dict(
            tool_id="inspect_project_model_coefficients",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["run_ids", "terms"],
                "properties": {
                    "run_ids": {
                        "type": "array", "minItems": 1, "maxItems": 4,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 200},
                    },
                    "terms": {
                        "type": "array", "minItems": 1, "maxItems": 4,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 300},
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "inspect_time_series_summary": dict(
            tool_id="inspect_time_series_summary",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            # Raised with inspect_operation_contract, and for the same
            # reason: what remains after removing the ~25,000 characters of
            # provenance row ids is all conclusions -- candidate tables
            # bounded at eight rows, scalar metrics, and six acceptance
            # verdicts. An ARMA-GARCH run simply has more *kinds* of
            # conclusion than the OLS-shaped result this default was sized
            # for, and truncating them made a live turn thrash and die.
            max_output_budget=12288,
        ),
        "inspect_repeated_measures_recipe": dict(
            tool_id="inspect_repeated_measures_recipe",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
        "inspect_artifact_preview": dict(
            tool_id="inspect_artifact_preview",
            version="v1",
            input_schema={
                "type": "object",
                "required": [
                    "owner_run_id",
                    "op_node_id",
                    "active_head_run_id",
                ],
                "properties": {
                    "request_id": {"type": "string"},
                    "owner_run_id": {"type": "string"},
                    "op_node_id": {"type": "string"},
                    "active_head_run_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project", "chain"),
            max_output_budget=8192,
        ),
    }


def global_tool_specs() -> dict[str, dict[str, Any]]:
    """Static fields of each global tool, by tool id, in list order."""
    return {
        "inspect_project_model_coefficients": dict(
            tool_id="inspect_project_model_coefficients",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["run_ids", "terms"],
                "properties": {
                    "run_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 200},
                    },
                    "terms": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 16,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 300},
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project",),
            max_output_budget=8192,
        ),
        "inspect_project_dataset_schema": dict(
            tool_id="inspect_project_dataset_schema",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project",),
            max_output_budget=8192,
        ),
        "inspect_project_numeric_summary": dict(
            tool_id="inspect_project_numeric_summary",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["run_id", "columns"],
                "properties": {
                    "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                    "columns": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 300},
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project",),
            max_output_budget=8192,
        ),
        "inspect_project_model_figure_evidence": dict(
            tool_id="inspect_project_model_figure_evidence",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["figures"],
                "properties": {
                    "figures": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "required": ["run_id", "artifact_id"],
                            "properties": {
                                "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                                "artifact_id": {"type": "string", "minLength": 1, "maxLength": 300},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project",),
            max_output_budget=8192,
        ),
        "inspect_project_linear_interaction_effects": dict(
            tool_id="inspect_project_linear_interaction_effects",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["effects"],
                "properties": {
                    "effects": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "required": [
                                "run_id",
                                "focal_term",
                                "interaction_term",
                                "moderator_column",
                            ],
                            "properties": {
                                "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                                "focal_term": {"type": "string", "minLength": 1, "maxLength": 300},
                                "interaction_term": {"type": "string", "minLength": 1, "maxLength": 300},
                                "moderator_column": {"type": "string", "minLength": 1, "maxLength": 300},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project",),
            max_output_budget=8192,
        ),
        "inspect_project_coefficient_transforms": dict(
            tool_id="inspect_project_coefficient_transforms",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["transforms"],
                "properties": {
                    "transforms": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "items": {
                            "type": "object",
                            "required": ["run_id", "term", "transform"],
                            "properties": {
                                "run_id": {"type": "string", "minLength": 1, "maxLength": 200},
                                "term": {"type": "string", "minLength": 1, "maxLength": 300},
                                "transform": {
                                    "type": "string",
                                    "enum": ["scale_0_01", "expm1_percent"],
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project",),
            max_output_budget=8192,
        ),
        "inspect_project_notebook_workflow_results": dict(
            tool_id="inspect_project_notebook_workflow_results",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["run_ids"],
                "properties": {
                    "run_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 16,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 200},
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project",),
            max_output_budget=8192,
        ),
        "inspect_project_statistical_evidence": dict(
            tool_id="inspect_project_statistical_evidence",
            version="v1",
            input_schema={
                "type": "object",
                "required": ["run_ids"],
                "properties": {
                    "run_ids": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 16,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 200},
                    },
                },
                "additionalProperties": False,
            },
            side_effect="none",
            scope_requirements=("project",),
            max_output_budget=8192,
            description="Read the persisted statistical evidence packet for the named runs: "
                "ANOVA post-hoc multiple comparisons with their correction method "
                "(Tukey, Bonferroni), Cohen's d, eta squared, omega squared, and the "
                "Levene, Bartlett and Shapiro-Wilk assumption checks. Call this for "
                "any question about statistical tests, effect sizes, post-hoc "
                "comparisons or assumption checks — these are produced by every "
                "ordinary run and do not require a Notebook workflow receipt.",
        ),
    }
