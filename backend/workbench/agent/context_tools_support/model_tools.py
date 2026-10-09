"""Model tools: bounded read-only context projection."""

from __future__ import annotations
import math
from typing import Any
from ...artifacts import read_json
from ...lineage.run_inputs import read_run_inputs
from ...services.results_service import read_model_results
from ...analysis_loop.time_series_compare import read_time_series_artifacts as _read_time_series_artifacts
from ..tools import ToolVisibleError
from ..bounds import _public_stat_number
from .coefficients import (
    _lmm_published_results,
    _public_requested_model_coefficients,
    _run_term_labeler,
)
from .figures import (
    _bounded_model_figure_numeric_source,
)
from .requests import (
    InspectProjectCoefficientTransformsRequest,
    InspectProjectLinearInteractionEffectsRequest,
    InspectProjectModelCoefficientsRequest,
    InspectProjectModelFigureEvidenceRequest,
    InspectProjectStatisticalEvidenceRequest,
    InspectRepeatedMeasuresRecipeRequest,
    InspectTimeSeriesSummaryRequest,
)
from .summaries import (
    RECIPE_RESULT_PROJECTIONS,
    _analysis_contract_from_run_inputs,
    _bounded_node,
    _bounded_statistics_evidence,
    _resolve_verified_registered_artifact,
)



class ModelToolsMixin:
    def inspect_project_model_coefficients(
        self,
        request: InspectProjectModelCoefficientsRequest,
    ) -> dict[str, Any]:
        """Return exact public coefficient evidence for explicitly named terms.

        This deliberately resolves neither a formula nor a raw-data artifact.
        The caller chooses a small set of known project runs and terms; the
        server projects only the persisted public statistics that answer that
        question.  Missing terms remain visible rather than being inferred.
        """

        models: list[dict[str, Any]] = []
        for run_id in request.run_ids:
            run_root = self._project_run_root(run_id)
            labeler = _run_term_labeler(run_root)
            for result in [*read_model_results(run_root), *_lmm_published_results(run_root)]:
                public_model = _public_requested_model_coefficients(
                    run_id=run_id,
                    result=result,
                    requested_terms=request.terms,
                    labeler=labeler,
                )
                if public_model is not None:
                    models.append(public_model)
        return {
            "models": models,
            "omitted_sections": ["raw_model_results", "raw_rows"],
        }

    def inspect_project_model_figure_evidence(
        self,
        request: InspectProjectModelFigureEvidenceRequest,
    ) -> dict[str, Any]:
        """Return one bounded numeric projection per requested model figure."""

        evidence: list[dict[str, Any]] = []
        for item in request.figures:
            if set(item) != {"run_id", "artifact_id"} or not all(
                isinstance(value, str) and value for value in item.values()
            ):
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_INVALID: each figure needs one run_id and artifact_id."
                )
            run_id = item["run_id"]
            artifact_id = item["artifact_id"]
            run_root = self._project_run_root(run_id)
            try:
                index = read_json(run_root / "artifacts_index.json")
                records = index.get("artifacts") if isinstance(index, dict) else None
                record = next(
                    (
                        value
                        for value in records or []
                        if isinstance(value, dict) and value.get("artifact_id") == artifact_id
                    ),
                    None,
                )
            except (FileNotFoundError, OSError, ValueError, TypeError) as exc:
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: the persisted artifact index is unavailable."
                ) from exc
            if not isinstance(record, dict) or record.get("artifact_type") != "figure":
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: requested artifact is not a persisted figure."
                )
            models = [result for result in read_model_results(run_root) if isinstance(result, dict)]
            if len(models) != 1 or not isinstance(models[0].get("model_id"), str):
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: the figure does not resolve to exactly one persisted model."
                )
            model_id = str(models[0]["model_id"])
            numeric_source = _bounded_model_figure_numeric_source(
                run_root,
                node_id=f"model:{model_id}",
                artifact_id=artifact_id,
            )
            if numeric_source is None:
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: the figure has no bounded numeric evidence."
                )
            try:
                from ...figure_context import resolve_figure_ai_context

                packet = resolve_figure_ai_context(
                    self.project_root, run_id=run_id, artifact_id=artifact_id
                )
            except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
                raise ToolVisibleError(
                    "PROJECT_MODEL_FIGURE_EVIDENCE_UNAVAILABLE: figure metadata is unavailable."
                ) from exc
            figure = packet.get("figure") if isinstance(packet, dict) else None
            evidence.append(
                {
                    "run_id": run_id,
                    "model_id": model_id,
                    "artifact_id": artifact_id,
                    "chart_type": figure.get("chart_type") if isinstance(figure, dict) else None,
                    "numeric_source": numeric_source,
                    "evidence_ref": {
                        "run_id": run_id,
                        "model_id": model_id,
                        "artifact_id": artifact_id,
                    },
                }
            )
        return {
            "figures": evidence,
            "omitted_sections": ["raw_rows", "raw_model_results", "image_pixels", "figure_paths"],
        }

    def inspect_project_linear_interaction_effects(
        self,
        request: InspectProjectLinearInteractionEffectsRequest,
    ) -> dict[str, Any]:
        """Compute OLS-scale interaction slopes from persisted public inputs.

        This is deliberately a read-only, server-side calculation rather than
        asking a language model to do floating-point arithmetic.  It is only
        available for OLS results, where the requested derivative on the
        recorded outcome scale is beta_focal + beta_interaction * mean(moderator).
        No standard error or interval is implied because that requires a
        covariance term which this bounded reader does not expose.
        """

        effects: list[dict[str, Any]] = []
        for item in request.effects:
            if set(item) != {
                "run_id",
                "focal_term",
                "interaction_term",
                "moderator_column",
            } or not all(isinstance(value, str) and value for value in item.values()):
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_INVALID: each effect must identify one "
                    "run, focal term, interaction term, and moderator column."
                )
            run_id = item["run_id"]
            focal_term = item["focal_term"]
            interaction_term = item["interaction_term"]
            moderator_column = item["moderator_column"]
            if len({focal_term, interaction_term, moderator_column}) != 3:
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_INVALID: focal term, interaction term, "
                    "and moderator column must be distinct."
                )
            run_root = self._project_run_root(run_id)
            matches: list[tuple[str, dict[str, Any]]] = []
            for result in read_model_results(run_root):
                model_id = result.get("model_id")
                model_type = result.get("model_type")
                coefficients = result.get("coefficients")
                if (
                    not isinstance(model_id, str)
                    or not isinstance(model_type, str)
                    or not model_type.startswith("ols")
                    or not isinstance(coefficients, dict)
                ):
                    continue
                focal = coefficients.get(focal_term)
                interaction = coefficients.get(interaction_term)
                if (
                    isinstance(focal, dict)
                    and isinstance(interaction, dict)
                    and _public_stat_number(focal.get("estimate")) is not None
                    and _public_stat_number(interaction.get("estimate")) is not None
                ):
                    matches.append((model_id, coefficients))
            if len(matches) != 1:
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_UNAVAILABLE: exactly one persisted OLS "
                    f"model in {run_id!r} must contain the requested focal and interaction terms."
                )
            try:
                profile = read_json(run_root / "staged" / "data_profile.json")
            except (FileNotFoundError, OSError, ValueError) as exc:
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_UNAVAILABLE: the moderator mean is not persisted."
                ) from exc
            columns = profile.get("columns") if isinstance(profile, dict) else None
            metadata = columns.get(moderator_column) if isinstance(columns, dict) else None
            moderator_mean = (
                _public_stat_number(metadata.get("mean"))
                if isinstance(metadata, dict)
                else None
            )
            if moderator_mean is None:
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_UNAVAILABLE: the requested moderator has "
                    "no persisted numeric mean."
                )
            model_id, coefficients = matches[0]
            focal_estimate = _public_stat_number(coefficients[focal_term].get("estimate"))
            interaction_estimate = _public_stat_number(
                coefficients[interaction_term].get("estimate")
            )
            assert focal_estimate is not None and interaction_estimate is not None
            marginal_effect = float(focal_estimate) + float(interaction_estimate) * float(moderator_mean)
            if not math.isfinite(marginal_effect):
                raise ToolVisibleError(
                    "PROJECT_INTERACTION_EFFECT_UNAVAILABLE: persisted inputs produced a "
                    "non-finite marginal effect."
                )
            effects.append(
                {
                    "run_id": run_id,
                    "model_id": model_id,
                    "focal_term": focal_term,
                    "interaction_term": interaction_term,
                    "moderator_column": moderator_column,
                    "moderator_mean": moderator_mean,
                    "marginal_effect": marginal_effect,
                    "evidence_ref": {
                        "run_id": run_id,
                        "model_id": model_id,
                        "result_ref": f"model_results:{model_id}",
                        "profile_ref": "staged/data_profile.json",
                    },
                }
            )
        return {
            "effects": effects,
            "omitted_sections": ["raw_model_results", "raw_rows", "correlations"],
        }

    def inspect_project_coefficient_transforms(
        self,
        request: InspectProjectCoefficientTransformsRequest,
    ) -> dict[str, Any]:
        """Apply closed, auditable numeric transforms to one stored coefficient.

        The server returns mathematics only.  It does not infer that a term is
        logged, that an outcome is logged, or that a percentage interpretation
        is appropriate; those are separate conclusions which must be supported
        by the persisted model evidence the Agent cites alongside this result.
        """

        values: list[dict[str, Any]] = []
        for item in request.transforms:
            if set(item) != {"run_id", "term", "transform"} or not all(
                isinstance(value, str) and value for value in item.values()
            ):
                raise ToolVisibleError(
                    "PROJECT_COEFFICIENT_TRANSFORM_INVALID: each item must identify "
                    "one run, term, and registered transform."
                )
            run_id = item["run_id"]
            term = item["term"]
            transform = item["transform"]
            if transform not in {"scale_0_01", "expm1_percent"}:
                raise ToolVisibleError(
                    "PROJECT_COEFFICIENT_TRANSFORM_INVALID: transform must be "
                    "scale_0_01 or expm1_percent."
                )
            run_root = self._project_run_root(run_id)
            matches: list[tuple[str, float]] = []
            for result in read_model_results(run_root):
                model_id = result.get("model_id")
                coefficients = result.get("coefficients")
                coefficient = coefficients.get(term) if isinstance(coefficients, dict) else None
                estimate = (
                    _public_stat_number(coefficient.get("estimate"))
                    if isinstance(coefficient, dict)
                    else None
                )
                if isinstance(model_id, str) and estimate is not None:
                    matches.append((model_id, float(estimate)))
            if len(matches) != 1:
                raise ToolVisibleError(
                    "PROJECT_COEFFICIENT_TRANSFORM_UNAVAILABLE: exactly one persisted "
                    f"model in {run_id!r} must contain {term!r}."
                )
            model_id, estimate = matches[0]
            value = estimate * 0.01 if transform == "scale_0_01" else math.expm1(estimate) * 100.0
            if not math.isfinite(value):
                raise ToolVisibleError(
                    "PROJECT_COEFFICIENT_TRANSFORM_UNAVAILABLE: persisted input produced "
                    "a non-finite transformed value."
                )
            values.append(
                {
                    "run_id": run_id,
                    "model_id": model_id,
                    "term": term,
                    "transform": transform,
                    "value": value,
                    "evidence_ref": {
                        "run_id": run_id,
                        "model_id": model_id,
                        "result_ref": f"model_results:{model_id}",
                    },
                }
            )
        return {
            "transforms": values,
            "omitted_sections": ["raw_model_results", "raw_rows"],
        }

    def inspect_project_statistical_evidence(
        self,
        request: InspectProjectStatisticalEvidenceRequest,
    ) -> dict[str, Any]:
        """Read the statistics evidence packet for named, visible project runs."""

        runs: list[dict[str, Any]] = []
        for run_id in sorted(set(request.run_ids)):
            run_root = self._project_run_root(run_id)
            evidence = _bounded_statistics_evidence(run_root)
            if evidence is None:
                continue
            runs.append({"run_id": run_id, "statistical_evidence": evidence})
        return {
            "runs": runs,
            "omitted_sections": ["raw_artifact_payloads", "raw_rows"],
        }

    def inspect_time_series_summary(
        self,
        request: InspectTimeSeriesSummaryRequest,
    ) -> dict[str, Any]:
        """Return the public projection owned by the run's actual Recipe."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id
        try:
            run_inputs = read_run_inputs(run_root)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            run_inputs = {}
        routing = manifest.get("model_routing")
        manifest_model_type = (
            routing.get("effective_model_type")
            if isinstance(routing, dict)
            else None
        )
        effective_model_type = manifest_model_type
        input_model_types: list[str] = []
        if isinstance(run_inputs, dict):
            for section_name in ("executed_payload", "confirmed_payload", "form"):
                section = run_inputs.get(section_name)
                model_type = section.get("model_type") if isinstance(section, dict) else None
                if isinstance(model_type, str) and model_type:
                    input_model_types.append(model_type)
        input_model_type_set = set(input_model_types)
        if len(input_model_type_set) > 1 or (
            manifest_model_type in {"time_series.ets", "time_series.arma_garch"}
            and input_model_type_set
            and input_model_type_set != {manifest_model_type}
        ):
            return {
                **canonical,
                "node": _bounded_node(node),
                "lineage": {
                    "run_id": request.owner_run_id,
                    "source_run_id": None,
                    "node_id": node.get("id"),
                    "model_type": manifest_model_type,
                },
                "time_series_summary": {
                    "available": False,
                    "reason_code": "TIME_SERIES_MODEL_IDENTITY_CONFLICT",
                },
                "compare": None,
                "omitted_sections": ["raw_series"],
            }
        if input_model_types and effective_model_type not in {
            "time_series.ets",
            "time_series.arma_garch",
        }:
            effective_model_type = input_model_types[0]

        recipe_projection = RECIPE_RESULT_PROJECTIONS.get(effective_model_type)
        if recipe_projection is not None:
            from ..recipe_contracts import recipe_contract

            registered = _resolve_verified_registered_artifact(
                run_root,
                artifact_id=recipe_projection.artifact_id,
                expected_type="model_result",
            )
            summary = (
                recipe_contract(effective_model_type).public_result_projection().build(
                    registered[0],
                    artifact_id=recipe_projection.artifact_id,
                    artifact_sha256=registered[1],
                )
                if registered is not None
                else {
                    "available": False,
                    "reason_code": recipe_projection.unavailable_reason_code,
                }
            )
            return {
                **canonical,
                "node": _bounded_node(node),
                "lineage": {
                    "run_id": request.owner_run_id,
                    "source_run_id": None,
                    "node_id": node.get("id"),
                    "model_type": effective_model_type,
                },
                "time_series_summary": summary,
                "compare": None,
                "omitted_sections": ["raw_series"],
            }

        if effective_model_type != "time_series.arma_garch":
            return {
                **canonical,
                "node": _bounded_node(node),
                "lineage": {
                    "run_id": request.owner_run_id,
                    "source_run_id": None,
                    "node_id": node.get("id"),
                    "model_type": effective_model_type,
                },
                "time_series_summary": {
                    "available": False,
                    "reason_code": "TIME_SERIES_PUBLIC_RESULT_UNSUPPORTED",
                },
                "compare": None,
                "omitted_sections": ["raw_series"],
            }

        from ..recipe_contracts import recipe_contract

        artifacts, metadata = _read_time_series_artifacts(run_root)
        projection = recipe_contract(effective_model_type).public_result_projection()
        summary = projection.build(
            {"artifacts": artifacts},
            artifact_id=None,
            artifact_sha256=None,
        )
        if "ts.analysis_contract" not in artifacts:
            recovered = _analysis_contract_from_run_inputs(run_inputs)
            if recovered is not None:
                artifacts["ts.analysis_contract"] = recovered
            summary = projection.build(
                {"artifacts": artifacts},
                artifact_id=None,
                artifact_sha256=None,
            )
        persisted_source_run_id = run_inputs.get("rerun_of")
        declared_source_run_id = metadata.get("source_run_id")
        source_run_id = (
            persisted_source_run_id
            if isinstance(persisted_source_run_id, str) and persisted_source_run_id
            else declared_source_run_id
        )
        compare = None
        if isinstance(source_run_id, str) and source_run_id:
            source_root = self.project_root / "runs" / source_run_id
            source_artifacts, _ = _read_time_series_artifacts(source_root)
            if source_artifacts:
                from ...analysis_loop.time_series_compare import (
                    build_arma_garch_compare_packet,
                )

                compare = build_arma_garch_compare_packet(
                    source_run_id=source_run_id,
                    child_run_id=request.owner_run_id,
                    source_artifacts=source_artifacts,
                    child_artifacts=artifacts,
                    child_source_run_id=(
                        declared_source_run_id
                        if isinstance(declared_source_run_id, str)
                        else persisted_source_run_id
                    ),
                ).to_dict()
        omitted = summary.pop("omitted_sections", [])
        return {
            **canonical,
            "node": _bounded_node(node),
            "lineage": {
                "run_id": request.owner_run_id,
                "source_run_id": source_run_id,
                "node_id": metadata.get("node_id"),
                "dataset_ref": metadata.get("dataset_ref"),
                "dataset_hash": metadata.get("dataset_hash"),
                "contract_hash": metadata.get("contract_hash"),
            },
            "time_series_summary": summary,
            "compare": compare,
            "omitted_sections": omitted,
        }

    def inspect_repeated_measures_recipe(
        self,
        request: InspectRepeatedMeasuresRecipeRequest,
    ) -> dict[str, Any]:
        """Return only the sealed, read-only LMM explanation/recovery view."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        neutral = {
            "proposal": None,
            "plan_diff": None,
            "explanation": "未提供可用于生成说明的受控 LMM 诊断。",
        }
        if manifest.get("requested_model_type") != "linear_mixed_effects":
            recipe = neutral
        else:
            from ..recipes.lmm_public_result_view import build_repeated_measures_recipe_from_run

            recipe = build_repeated_measures_recipe_from_run(
                self.project_root / "runs", request.owner_run_id
            )
        return {
            **canonical,
            "node": _bounded_node(node),
            "repeated_measures_recipe": recipe,
            "omitted_sections": ["raw_model_results", "persistence_capability"],
        }

