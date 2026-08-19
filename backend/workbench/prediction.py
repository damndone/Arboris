from __future__ import annotations

from pathlib import Path
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd

from .artifacts import register_artifact, write_json
from .canonical import sha256_canonical
from .contracts.evidence.envelope import (
    ConsumerProjectionNotApplicableV1,
    ConsumerProjectionPayloadV1,
    ConsumerProjectionSlotV1,
    ConsumerProjectionV1,
    EvidenceEnvelopeV1,
    EvidenceReasonV1,
)
from .contracts.common.foundation_status import (
    AvailabilityStatusV1,
    CompletenessStatusV1,
    EvaluationDesignV1,
    ExecutionStatusV1,
    InferenceBasisV1,
    NumericalMethodV1,
    ValidationLevelV1,
)
from .contracts.prediction.holdout import HoldoutSealStoreV1
from .econometrics.optional_deps import require_optional_dependency
from .predictive_research.contracts import (
    AvailabilitySpecV1,
    ContractError,
    FeatureRecipeV1,
    SampleSpecV1,
    SamplingSpecV1,
    SplitPlanV1,
    StructureSpecV1,
)
from .predictive_research.classification_adapters import (
    dispatch_classification_runtime_binding,
)
from .predictive_research.classification_contracts import ClassificationTaskSpecV1, DecisionPolicyV1
from .predictive_research.classification_protocol import run_classification_protocol
from .predictive_research.preprocessing import ClassificationPreprocessingStepV1
from .predictive_research.persistence import (
    PredictionPersistenceAdmission,
    classification_artifact_id,
    persist_classification_artifacts,
)
from .predictive_research.feature_recipe import apply_feature_recipe
from .predictive_research.cache import PredictionIdentityCache
from .predictive_research.graph_persistence import persist_prediction_node_index
from .predictive_research.identity import build_prediction_identity
from .predictive_research.prediction_protocol import dataset_snapshot_hash, run_oos_prediction
from .predictive_research.split_kernel import build_split_plan
from .lineage.hashing import node_hash

_SUPPORTED_PREDICTION_MODEL_TYPES = {
    "prediction_lasso",
    "prediction_ridge",
    "prediction_random_forest",
}
_SUPPORTED_SAMPLING_METHODS = {"smote", "oversample", "undersample"}


def _classification_c0_reason(code: str, *, task_hash: str, split_hash: str, release_plan_hash: str) -> dict[str, Any]:
    return EvidenceReasonV1(
        code=code,
        message=f"classification evidence is {code}",
        source_refs=(
            f"classification-task:{task_hash}",
            f"classification-split:{split_hash}",
            f"classification-release-plan:{release_plan_hash}",
        ),
    ).to_dict()


def _build_classification_c0_evidence(
    *,
    status: str,
    task_hash: str,
    split_hash: str,
    holdout: Mapping[str, Any],
    evidence: Mapping[str, Any],
    blocked_reasons: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    release_plan_hash = str(holdout.get("release_plan_hash", ""))
    if not release_plan_hash:
        raise ContractError("CLASSIFICATION_RELEASE_PLAN_IDENTITY_REQUIRED", "holdout release plan identity is required")
    result_ref = f"classification-evidence:{task_hash}:{split_hash}:{release_plan_hash}"
    reasons = [
        _classification_c0_reason(
            reason,
            task_hash=task_hash,
            split_hash=split_hash,
            release_plan_hash=release_plan_hash,
        )
        for reason in blocked_reasons
    ]
    if status == "validated":
        execution_status = ExecutionStatusV1.COMPLETED.value
        availability = AvailabilityStatusV1.AVAILABLE.value
        completeness = CompletenessStatusV1.COMPLETE.value
        execution_reasons: list[dict[str, Any]] = []
        availability_reasons: list[dict[str, Any]] = []
        degradation_reasons: list[dict[str, Any]] = []
    elif status == "degraded":
        execution_status = ExecutionStatusV1.COMPLETED.value
        availability = AvailabilityStatusV1.AVAILABLE.value
        completeness = CompletenessStatusV1.DEGRADED.value
        execution_reasons = []
        availability_reasons = []
        degradation_reasons = reasons or [
            _classification_c0_reason(
                "CLASSIFICATION_EVIDENCE_DEGRADED",
                task_hash=task_hash,
                split_hash=split_hash,
                release_plan_hash=release_plan_hash,
            )
        ]
    else:
        execution_status = ExecutionStatusV1.BLOCKED.value
        availability = AvailabilityStatusV1.NOT_AVAILABLE.value
        completeness = CompletenessStatusV1.INSUFFICIENT.value
        execution_reasons = reasons or [
            _classification_c0_reason(
                "CLASSIFICATION_EVIDENCE_UNAVAILABLE",
                task_hash=task_hash,
                split_hash=split_hash,
                release_plan_hash=release_plan_hash,
            )
        ]
        availability_reasons = list(execution_reasons)
        degradation_reasons = list(execution_reasons)
    envelope = EvidenceEnvelopeV1.from_dict(
        {
            "result_identity": {
                "result_ref": result_ref,
                "task_hash": task_hash,
                "split_hash": split_hash,
                "holdout_hash": release_plan_hash,
                "release_plan_hash": release_plan_hash,
            },
            "execution_status": execution_status,
            "availability": availability,
            "completeness_status": completeness,
            "execution_reasons": execution_reasons,
            "availability_reasons": availability_reasons,
            "degradation_reasons": degradation_reasons,
            "numerical_method": NumericalMethodV1.DETERMINISTIC_NUMERIC.value,
            "inference_basis": InferenceBasisV1.DESCRIPTIVE.value,
            "evaluation_design": EvaluationDesignV1.NESTED_CROSS_VALIDATION.value,
            "validation_summary": {
                "levels_present": [],
                "minimum_required": ValidationLevelV1.NONE.value,
                "requirement_status": "not_applicable",
            },
            "method": {
                "id": "classification-production-v1",
                "version": "1.0",
                "model_families": ["logistic_regression", "random_forest"],
            },
            "estimand": {
                "id": "out_of_sample_binary_classification_performance",
                "population": evidence.get("task", {}).get("task_type", "binary") if isinstance(evidence.get("task"), Mapping) else "binary",
            },
            "input_provenance": {
                "task_hash": task_hash,
                "split_hash": split_hash,
                "holdout_hash": release_plan_hash,
                "release_plan_hash": release_plan_hash,
            },
            "assumptions": [],
            "diagnostics": [],
            "figures": [],
            "warnings": [] if status == "validated" else [{"code": "CLASSIFICATION_EVIDENCE_DEGRADED", "message": "classification evidence has unavailable or non-production facets"}],
            "dependencies": [],
            "numeric_facts": [],
            "family_evidence": {
                "classification": {
                    "status": status,
                    "task_hash": task_hash,
                    "split_hash": split_hash,
                    "holdout": dict(holdout),
                }
            },
            "oracle": {},
            "lineage_refs": [
                f"classification-task:{task_hash}",
                f"classification-split:{split_hash}",
                f"classification-release-plan:{release_plan_hash}",
            ],
        }
    )
    facets = ["classification", "task", "split", "holdout", "release_plan"]
    if status != "validated":
        facets.append("degraded")
    projection_status = "available" if status in {"validated", "degraded"} else "blocked"
    projection = ConsumerProjectionV1(
        contract="consumer-projection",
        contract_version="1.0",
        producer_version="1.8.9",
        payload=ConsumerProjectionPayloadV1(
            projection_id=result_ref,
            projection_ref=f"classification-consumer:{sha256_canonical(envelope.to_dict())}",
            projection_status=projection_status,
            slots=tuple(
                ConsumerProjectionSlotV1(
                    consumer=consumer,
                    artifact_facets=tuple(facets),
                    payload_schema_ref="workbench.prediction.classification-evidence",
                    source_eligible=status == "validated",
                )
                for consumer in ("agent", "notebook", "report")
            ),
            not_applicable_projection=ConsumerProjectionNotApplicableV1(
                "not_applicable",
                "classification evidence is applicable to this result",
            ),
        ),
    )
    return envelope.to_dict(), projection.to_dict()


def _prediction_project_root(run_root: Path) -> Path:
    run_root = Path(run_root)
    if run_root.parent.name == "runs":
        return run_root.parent.parent
    return run_root.parent


def run_classification_model_v189(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    task: ClassificationTaskSpecV1,
    row_refs: Sequence[str],
    model_ids: Sequence[str] = ("logistic_regression", "random_forest"),
    final_holdout_fraction: float = 0.2,
    cv_folds: int = 3,
    random_seed: int | None = None,
    decision_policy: DecisionPolicyV1 | None = None,
    feature_available_at: Sequence[Any] | None = None,
    prediction_origins: Sequence[Any] | None = None,
    label_windows: Sequence[tuple[Any, Any]] | None = None,
    entities: Sequence[str] | None = None,
    periods: Sequence[Any] | None = None,
    purge_gap: Any | None = None,
    embargo: Any | None = None,
    embargo_basis: str | None = None,
    preprocessing_steps: Sequence[ClassificationPreprocessingStepV1] | None = None,
    calibration_method: str = "platt",
    model_parameters: dict[str, dict[str, Any]] | None = None,
    runtime_registry: TrustedExecutorRegistry | None = None,
    holdout_seal_store: HoldoutSealStoreV1 | None = None,
    holdout_principal_ref: str | None = None,
    holdout_access_id: str | None = None,
) -> dict[str, Any]:
    """Run the additive v1.8.9 classification protocol from typed contracts.

    This entrypoint deliberately does not alter the v1.8.6 regression
    entrypoints.  Column names and availability are supplied by the typed
    task; adapters are selected by their package-local registry, never by a
    provider raw dictionary.
    """

    from .agent.trusted_executor_registry import TrustedExecutorRegistry, TrustedExecutorRegistryError

    if not isinstance(task, ClassificationTaskSpecV1):
        raise ContractError("CLASSIFICATION_TASK_REQUIRED", "classification entrypoint requires ClassificationTaskSpecV1")
    task.validate()
    if not isinstance(frame, pd.DataFrame):
        raise ContractError("CLASSIFICATION_FRAME_INVALID", "classification entrypoint requires a DataFrame")
    missing_columns = [
        column for column in (task.target_column, *task.feature_columns)
        if column not in frame.columns
    ]
    if missing_columns:
        raise ContractError("CLASSIFICATION_COLUMN_REF_MISSING", f"server-bound columns are missing: {missing_columns}")
    refs = tuple(row_refs)
    if len(refs) != len(frame) or len(set(refs)) != len(refs) or any(not isinstance(ref, str) or not ref for ref in refs):
        raise ContractError("CLASSIFICATION_ROW_IDENTITY_INVALID", "row_refs must be unique non-empty strings aligned to frame")
    if decision_policy is not None:
        if not isinstance(decision_policy, DecisionPolicyV1):
            raise ContractError("CLASSIFICATION_POLICY_INVALID", "decision_policy must be DecisionPolicyV1")
        decision_policy.validate()
    if type(runtime_registry) is not TrustedExecutorRegistry:
        raise ContractError(
            "CLASSIFICATION_PROVIDER_RUNTIME_JOIN_REQUIRED",
            "production classification requires a server-bound TrustedExecutorRegistry",
        )
    try:
        dispatch_classification_runtime_binding(runtime_registry, task_hash=task.content_hash)
    except TrustedExecutorRegistryError as exc:
        code = exc.code if exc.code.startswith("CLASSIFICATION_PROVIDER_RUNTIME_JOIN_") else "CLASSIFICATION_PROVIDER_RUNTIME_JOIN_MISMATCH"
        raise ContractError(code, str(exc)) from exc
    target = frame.loc[:, task.target_column]
    if target.isna().any():
        raise ContractError("CLASSIFICATION_TARGET_MISSING", "classification target contains missing values")
    seed = task.seed if random_seed is None else random_seed
    protocol = run_classification_protocol(
        frame.copy(),
        row_refs=refs,
        model_ids=tuple(model_ids),
        final_holdout_fraction=final_holdout_fraction,
        cv_folds=cv_folds,
        seed=seed,
        task=task,
        decision_policy=decision_policy,
        feature_available_at=feature_available_at,
        prediction_origins=prediction_origins,
        label_windows=label_windows,
        entities=entities,
        periods=periods,
        purge_gap=purge_gap,
        embargo=embargo,
        embargo_basis=embargo_basis,
        preprocessing_steps=preprocessing_steps,
        calibration_method=calibration_method,
        model_parameters=model_parameters,
        holdout_seal_store=holdout_seal_store,
        holdout_principal_ref=holdout_principal_ref,
        holdout_access_id=holdout_access_id,
    )
    class_support: dict[str, int] = {}
    for raw_value in target.tolist():
        label = task.class_mapping.get(raw_value, str(raw_value))
        class_support[str(label)] = class_support.get(str(label), 0) + 1
    split_hash = protocol["comparison"]["split_hash"]
    selected_model = protocol["comparison"]["selected_model"]
    selected = protocol["models"][selected_model]
    model_metrics = {
        "oof": selected["oof_metrics"],
        "holdout": selected["holdout"],
    }
    policy_payload = protocol["decision_policy"]
    blocked_reasons = list(protocol.get("blocked_reasons", []))
    unavailable_evidence = {
        "explanations": {
            "status": "unavailable",
            "reason_code": "CLASSIFICATION_EXPLANATION_PROVIDER_UNAVAILABLE",
            "shap": {"status": "unavailable", "reason_code": "CLASSIFICATION_EXPLANATION_PROVIDER_UNAVAILABLE"},
        },
        "stability": {
            "status": "unavailable",
            "reason_code": "CLASSIFICATION_STABILITY_UNAVAILABLE",
        },
        "shift": {
            "status": "unavailable",
            "reason_code": "CLASSIFICATION_SHIFT_UNAVAILABLE",
        },
    }
    blocked_reasons.extend(
        [
            unavailable_evidence["explanations"]["reason_code"],
            unavailable_evidence["stability"]["reason_code"],
            unavailable_evidence["shift"]["reason_code"],
        ]
    )
    blocked_reasons = list(dict.fromkeys(blocked_reasons))
    result_status = "degraded" if blocked_reasons else protocol["status"]
    evidence = {
        "payload_schema": "workbench.prediction.classification-evidence",
        "schema_version": 1,
        "status": result_status,
        "task": {
            "task_type": task.task_type,
            "positive_class": task.positive_class,
            "class_support": class_support,
            "task_hash": task.content_hash,
        },
        "split": {"profile": task.split_profile, "split_hash": split_hash},
        "metrics": model_metrics,
        "holdout": protocol["holdout"],
        "holdout_identity": {
            "status": protocol["holdout"].get("status"),
            "release_plan_hash": protocol["holdout"].get("release_plan_hash"),
            "release_count": protocol["holdout"].get("release_count"),
        },
        "calibration": protocol["calibration"],
        "baselines": protocol["baselines"],
        "controls": protocol["controls"],
        "comparison": protocol["comparison"],
        **unavailable_evidence,
        "decision_policy": policy_payload,
        "blocked_reasons": blocked_reasons,
        "evidence_refs": {
            "split": f"classification-split:{split_hash}",
            "model": f"classification-model:{selected_model}:{protocol['holdout']['release_plan']['model_hash']}",
            "holdout": f"classification-holdout:{protocol['holdout']['release_plan_hash']}",
            "task": f"classification-task:{task.content_hash}",
            "release_plan": f"classification-release-plan:{protocol['holdout']['release_plan_hash']}",
        },
    }
    c0_envelope, c0_projection = _build_classification_c0_evidence(
        status=result_status,
        task_hash=task.content_hash,
        split_hash=split_hash,
        holdout=protocol["holdout"],
        evidence=evidence,
        blocked_reasons=blocked_reasons,
    )
    evidence["c0_evidence_envelope"] = c0_envelope
    evidence["c0_consumer_projection"] = c0_projection
    evidence["foundation_status"] = {
        "execution_status": c0_envelope["execution_status"],
        "availability": c0_envelope["availability"],
        "completeness_status": c0_envelope["completeness_status"],
        "producer_status": result_status,
    }
    identity = classification_artifact_id(
        task_hash=task.content_hash,
        split_hash=split_hash,
        preprocessing_hash=sha256_canonical(selected["preprocessing"]),
        model_hash=sha256_canonical(protocol["models"]),
        prediction_hash=sha256_canonical(model_metrics),
        evaluation_hash=sha256_canonical(protocol["holdout"]),
        control_hash=sha256_canonical(evidence["controls"]),
        comparison_hash=sha256_canonical(protocol["comparison"]),
        explanation_hash=sha256_canonical(evidence["explanations"]),
        policy_hash=sha256_canonical(policy_payload),
    )
    artifact = persist_classification_artifacts(
        Path(run_root),
        {"artifact_id": identity, "task": {**task.to_dict(), "task_hash": task.content_hash}, "evidence": evidence},
    )
    artifact_sha256 = artifact.get("sha256")
    if type(artifact_sha256) is not str or len(artifact_sha256) != 64:
        raise ContractError(
            "CLASSIFICATION_ARTIFACT_DIGEST_INVALID",
            "persisted classification artifact did not return a SHA-256 digest",
        )
    # The packet is not consumable merely because it exists on disk. Register
    # the exact path, digest and payload contract in the run index through the
    # same FD-admitted persistence boundary used to write it.
    with PredictionPersistenceAdmission.admit(Path(run_root)) as persistence:
        persistence.register_artifact(
            artifact_id=identity,
            relative_parts=("classification_artifacts.json",),
            artifact_type="classification_artifacts",
            step="classification",
            inputs=[task.content_hash, split_hash],
            sha256=artifact_sha256,
            payload_contract={
                "payload_schema": "workbench.prediction.classification-artifacts",
                "schema_version": 1,
            },
        )
    return {
        **protocol,
        "status": result_status,
        "task_hash": task.content_hash,
        "split_hash": split_hash,
        "release_plan_identity": dict(protocol["holdout"]["release_plan"]),
        "task": {**task.to_dict(), "task_hash": task.content_hash},
        "evidence": evidence,
        "artifact": {**artifact, "artifact_id": identity},
    }


def run_prediction_model_v186(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    y: str,
    x: list[str],
    model_type: str,
    model_id: str,
    final_holdout_fraction: float,
    cv_folds: int,
    shuffle: bool,
    random_seed: int,
    data_structure: str = "unknown",
    entity_column: str | None = None,
    group_column: str | None = None,
    time_column: str | None = None,
    sampling: SamplingSpecV1 | None = None,
    inputs: list[str] | None = None,
    estimator_factory: Callable[[], Any] | None = None,
    feature_recipe: FeatureRecipeV1 | None = None,
    graph_recorder: Any | None = None,
    imputation_method: str | None = None,
    imputation_max_iter: int = 10,
    imputation_max_missing_rate: float = 0.4,
) -> dict[str, Any]:
    """Run the typed v1.8.6 protocol while keeping legacy callers unchanged."""

    sampling_spec = sampling or SamplingSpecV1()
    sampling_spec.validate()
    artifact_inputs = inputs or ["cleaned_dataset"]
    if imputation_method == "mice" and "imputed_dataset" in artifact_inputs:
        raise ContractError(
            "PREDICTION_FULL_TABLE_IMPUTATION_UNSUPPORTED",
            "prediction MICE must receive the cleaned snapshot and fit inside each split scope",
        )
    if sampling_spec.sampling_weight is not None or sampling_spec.analysis_weight is not None:
        raise ContractError(
            "PREDICTION_WEIGHT_UNSUPPORTED",
            "the v1.8.6 generic estimator adapter does not support sampling_weight or analysis_weight",
        )
    structure = StructureSpecV1(
        kind=data_structure,
        group_column=group_column,
        time_column=time_column,
        entity_column=entity_column,
        provenance="user_confirmed" if data_structure != "unknown" else "inferred",
    )
    structure.validate()
    if data_structure in {"temporal", "panel"}:
        required_columns = (
            [time_column] if data_structure == "temporal" else [entity_column, time_column]
        )
        missing_columns = [column for column in required_columns if not column or column not in frame.columns]
        if missing_columns:
            code = (
                "PREDICTION_TIME_COLUMN_MISSING"
                if data_structure == "temporal"
                else "PREDICTION_PANEL_COLUMN_MISSING"
            )
            raise ContractError(
                code,
                f"{data_structure} prediction requires declared columns present in the dataset: {missing_columns}",
            )
        raise ContractError(
            "PREDICTION_SPLIT_PROFILE_NOT_SUPPORTED",
            f"{data_structure} prediction requires a registered safety profile in a future release",
        )
    strategy = "grouped" if data_structure == "grouped" else data_structure
    protocol_frame = frame.copy()
    if feature_recipe is not None:
        protocol_frame = apply_feature_recipe(protocol_frame, feature_recipe)
    protocol_frame.index = [str(value) for value in frame.index]
    groups = protocol_frame[group_column].astype(str).tolist() if data_structure == "grouped" and group_column else None
    time_values = protocol_frame[time_column].tolist() if data_structure in {"temporal", "panel"} and time_column else None
    split = build_split_plan(
        row_refs=tuple(protocol_frame.index),
        strategy=strategy,
        groups=groups,
        time_values=time_values,
        final_holdout_fraction=final_holdout_fraction,
        cv_folds=cv_folds,
        shuffle=shuffle,
        random_seed=random_seed,
    )
    profile_id = {
        "grouped": "grouped_holdout_groupkfold",
        "temporal": "temporal_holdout_rolling",
    }.get(data_structure, "iid_holdout_kfold")
    sample_spec = SampleSpecV1(
        dataset_sha256=dataset_snapshot_hash(protocol_frame),
        sampling=sampling_spec,
        split_plan=SplitPlanV1(
            strategy=strategy,
            profile_id=profile_id,
            profile_version=1,
            effective_parameters={
                **split.effective_parameters,
                "group_column": group_column,
                "time_column": time_column,
                "model_id": model_id,
            },
        ),
        structure=structure,
        availability=AvailabilitySpecV1(kind="declared", reservation_policy="fail_closed", validation_status="declared"),
        feature_recipe_ref=feature_recipe.content_hash if feature_recipe is not None else None,
        split_plan_ref=split.content_hash,
    )
    prediction_identity = build_prediction_identity(
        sample_spec,
        model_type=model_type,
        model_id=model_id,
    )
    identity_cache = PredictionIdentityCache(_prediction_project_root(run_root))
    cache_status = identity_cache.status(prediction_identity)
    if estimator_factory is None:
        estimator_factory = _make_v186_estimator_factory(model_type, random_seed)
    result = run_oos_prediction(
        frame=protocol_frame,
        target=y,
        features=tuple(x),
        sample_spec=sample_spec,
        split_receipt=split,
        estimator_factory=estimator_factory,
        model_id=model_id,
        control_seed=random_seed,
        imputation_method=imputation_method,
        imputation_max_iter=imputation_max_iter,
        imputation_max_missing_rate=imputation_max_missing_rate,
    )

    sample_payload = {
        **sample_spec.to_dict(),
        "sample_spec_hash": sample_spec.content_hash,
        "transformation_hash": sample_spec.transformation_hash,
        "evaluation_hash": sample_spec.evaluation_hash,
    }
    split_payload = {**split.to_dict(), "content_hash": split.content_hash}
    identity_fields = prediction_identity.to_dict()
    sample_payload.update(identity_fields)
    prediction_payload = {"model_type": model_type, **result.prediction_packet, **identity_fields}
    evaluation_payload = {"model_type": model_type, **result.evaluation_packet, **identity_fields}
    control_payload = {"model_type": model_type, **result.control_packet, **identity_fields}
    with PredictionPersistenceAdmission.admit(run_root) as persistence:
        sample_path = ("prediction_splits", f"{model_id}.sample.json")
        split_path = ("prediction_splits", f"{model_id}.json")
        prediction_path = ("prediction_results", f"{model_id}.json")
        evaluation_path = ("evaluation_results", f"{model_id}.json")
        control_path = ("negative_controls", f"{model_id}.json")
        recipe_path = ("prediction_splits", f"{model_id}.feature-recipe.json")
        sample_sha = persistence.write_json(sample_path, sample_payload)
        split_sha = persistence.write_json(split_path, split_payload)
        prediction_sha = persistence.write_json(prediction_path, prediction_payload)
        evaluation_sha = persistence.write_json(evaluation_path, evaluation_payload)
        control_sha = persistence.write_json(control_path, control_payload)
        if feature_recipe is not None:
            recipe_sha = persistence.write_json(recipe_path, feature_recipe.to_dict())
            persistence.register_artifact(
                artifact_id=f"{model_id}_feature_recipe", relative_parts=recipe_path,
                artifact_type="prediction_feature_recipe", step="prediction", inputs=artifact_inputs,
                sha256=recipe_sha,
                payload_contract={"payload_schema": "workbench.prediction.feature-recipe", "schema_version": 1},
            )
        persistence.register_artifact(
            artifact_id=f"{model_id}_sample_spec", relative_parts=sample_path,
            artifact_type="prediction_sample_spec", step="prediction", inputs=artifact_inputs,
            sha256=sample_sha,
            payload_contract={"payload_schema": "workbench.prediction.sample-spec", "schema_version": 1},
        )
        persistence.register_artifact(
            artifact_id=f"{model_id}_split_plan", relative_parts=split_path,
            artifact_type="prediction_split_plan", step="prediction", inputs=artifact_inputs,
            sha256=split_sha,
            payload_contract={"payload_schema": "workbench.prediction.split-plan", "schema_version": 1},
        )
        persistence.register_artifact(
            artifact_id=model_id, relative_parts=prediction_path,
            artifact_type="prediction_packet", step="prediction", inputs=artifact_inputs,
            sha256=prediction_sha,
            payload_contract={"payload_schema": "workbench.prediction.prediction-packet", "schema_version": 1},
        )
        persistence.register_artifact(
            artifact_id=f"{model_id}_evaluation", relative_parts=evaluation_path,
            artifact_type="evaluation_packet", step="prediction", inputs=[model_id],
            sha256=evaluation_sha,
            payload_contract={"payload_schema": "workbench.prediction.evaluation-packet", "schema_version": 1},
        )
        persistence.register_artifact(
            artifact_id=f"{model_id}_controls", relative_parts=control_path,
            artifact_type="negative_control_packet", step="prediction", inputs=[model_id],
            sha256=control_sha,
            payload_contract={"payload_schema": "workbench.prediction.negative-control-packet", "schema_version": 1},
        )
    if graph_recorder is not None:
        prediction_node_index = _record_prediction_graph(
            graph_recorder,
            model_id=model_id,
            model_type=model_type,
            sample_spec=sample_payload,
            split_plan=split_payload,
            evaluation=evaluation_payload,
            control=control_payload,
        )
        persist_prediction_node_index(run_root, prediction_node_index)
    identity_cache.record(prediction_identity)
    return {
        "protocol": "predictive_research_v1",
        "model_type": model_type,
        **identity_fields,
        "cache": cache_status.to_dict(),
        "sample_spec": sample_payload,
        "split_plan": split_payload,
        "prediction_packet": prediction_payload,
        "evaluation_packet": evaluation_payload,
        "control_packet": control_payload,
    }


def _record_prediction_graph(
    recorder: Any,
    *,
    model_id: str,
    model_type: str,
    sample_spec: dict[str, Any],
    split_plan: dict[str, Any],
    evaluation: dict[str, Any],
    control: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Record the bounded research chain without making packet internals nodes."""

    transformation_identity = str(sample_spec.get("transformation_hash", ""))
    evaluation_identity = str(sample_spec.get("evaluation_hash", ""))
    sample_spec_identity = str(sample_spec.get("sample_spec_hash", ""))
    dataset_hash = node_hash(
        [],
        {
            "protocol": "predictive_research_v1",
            "node": "dataset_snapshot",
            "transformation_identity": transformation_identity,
        },
    )
    task_hash = node_hash(
        [dataset_hash],
        {
            "protocol": "predictive_research_v1",
            "node": "task",
            "model_id": model_id,
            "model_type": model_type,
        },
    )
    split_hash = node_hash(
        [task_hash],
        {
            "protocol": "predictive_research_v1",
            "node": "split_plan",
            "evaluation_identity": evaluation_identity,
        },
    )
    baseline_hash = node_hash(
        [split_hash],
        {"protocol": "predictive_research_v1", "node": "baseline", "model_id": model_id},
    )
    candidate_hash = node_hash(
        [split_hash],
        {
            "protocol": "predictive_research_v1",
            "node": "candidate",
            "model_id": model_id,
            "model_type": model_type,
        },
    )
    evaluation_hash = node_hash(
        [baseline_hash, candidate_hash],
        {
            "protocol": "predictive_research_v1",
            "node": "evaluation",
            "evaluation_identity": evaluation_identity,
        },
    )
    controls_hash = node_hash(
        [evaluation_hash],
        {"protocol": "predictive_research_v1", "node": "negative_controls", "model_id": model_id},
    )
    result_hash = node_hash(
        [controls_hash],
        {
            "protocol": "predictive_research_v1",
            "node": "result",
            "model_id": model_id,
            "prediction_identity": sample_spec.get("prediction_identity_hash", ""),
            "sample_spec_hash": sample_spec_identity,
        },
    )

    recorder.record_stage(
        "prediction:dataset_snapshot",
        "Dataset Snapshot",
        payload_ref="processed/cleaned_dataset.parquet",
        summary=f"Snapshot {sample_spec.get('dataset_ref', {}).get('dataset_sha256', '')}",
        node_hash=dataset_hash,
    )
    recorder.record_stage(
        "prediction:task",
        "Prediction Task",
        summary=f"{model_type} for {model_id}",
        node_hash=task_hash,
    )
    recorder.record_stage(
        "prediction:split_plan",
        "Split Plan",
        payload_ref=f"prediction_splits/{model_id}.json",
        summary=f"{split_plan.get('strategy', 'unknown')} / {split_plan.get('content_hash', '')}",
        node_hash=split_hash,
    )
    recorder.record_model(
        "prediction:baseline",
        "Baseline Model",
        payload_ref=f"evaluation_results/{model_id}.json",
        summary=str(evaluation.get("baseline", {}).get("model_id", "mean_regressor")),
        node_hash=baseline_hash,
    )
    recorder.record_model(
        "prediction:candidate",
        "Candidate Model",
        payload_ref=f"prediction_results/{model_id}.json",
        summary=model_type,
        node_hash=candidate_hash,
    )
    recorder.record_stage(
        "prediction:evaluation",
        "Evaluation",
        payload_ref=f"evaluation_results/{model_id}.json",
        summary=f"OOS n={evaluation.get('oos', {}).get('n', '—')}",
        node_hash=evaluation_hash,
    )
    recorder.record_stage(
        "prediction:negative_controls",
        "Negative Controls",
        payload_ref=f"negative_controls/{model_id}.json",
        summary=f"{len(control.get('controls', []))} control receipt(s)",
        node_hash=controls_hash,
    )
    recorder.record_stage(
        "prediction:result",
        "Prediction Result",
        payload_ref=f"evaluation_results/{model_id}.json",
        summary="Typed predictive-research evidence",
        node_hash=result_hash,
    )
    edges = (
        ("prediction:e:dataset-task", "prediction:dataset_snapshot", "prediction:task"),
        ("prediction:e:task-split", "prediction:task", "prediction:split_plan"),
        ("prediction:e:split-baseline", "prediction:split_plan", "prediction:baseline"),
        ("prediction:e:split-candidate", "prediction:split_plan", "prediction:candidate"),
        ("prediction:e:baseline-evaluation", "prediction:baseline", "prediction:evaluation"),
        ("prediction:e:candidate-evaluation", "prediction:candidate", "prediction:evaluation"),
        ("prediction:e:evaluation-controls", "prediction:evaluation", "prediction:negative_controls"),
        ("prediction:e:controls-result", "prediction:negative_controls", "prediction:result"),
    )
    for edge_id, source_id, target_id in edges:
        recorder.record_edge(edge_id, source_id, target_id, op="predictive_research")
    return {
        "prediction:dataset_snapshot": {
            "node_hash": dataset_hash,
            "producing_stage": "prediction",
            "cas_ref": {"node_hash": dataset_hash, "artifact": "processed/cleaned_dataset.parquet"},
        },
        "prediction:task": {
            "node_hash": task_hash,
            "producing_stage": "prediction",
            "cas_ref": {"node_hash": task_hash, "artifact": "prediction_splits"},
        },
        "prediction:split_plan": {
            "node_hash": split_hash,
            "producing_stage": "prediction",
            "cas_ref": {"node_hash": split_hash, "artifact": f"prediction_splits/{model_id}.json"},
        },
        "prediction:baseline": {
            "node_hash": baseline_hash,
            "producing_stage": "prediction",
            "cas_ref": {"node_hash": baseline_hash, "artifact": f"evaluation_results/{model_id}.json"},
        },
        "prediction:candidate": {
            "node_hash": candidate_hash,
            "producing_stage": "prediction",
            "cas_ref": {"node_hash": candidate_hash, "artifact": f"prediction_results/{model_id}.json"},
        },
        "prediction:evaluation": {
            "node_hash": evaluation_hash,
            "producing_stage": "prediction",
            "cas_ref": {"node_hash": evaluation_hash, "artifact": f"evaluation_results/{model_id}.json"},
        },
        "prediction:negative_controls": {
            "node_hash": controls_hash,
            "producing_stage": "prediction",
            "cas_ref": {"node_hash": controls_hash, "artifact": f"negative_controls/{model_id}.json"},
        },
        "prediction:result": {
            "node_hash": result_hash,
            "producing_stage": "prediction",
            "cas_ref": {"node_hash": result_hash, "artifact": f"evaluation_results/{model_id}.json"},
            "sample_spec_hash": sample_spec_identity,
        },
    }


def _make_v186_estimator_factory(model_type: str, random_seed: int) -> Callable[[], Any]:
    sklearn_pipeline = require_optional_dependency(
        "sklearn.pipeline", extra="ml", engine="scikit-learn", model_type=model_type, step="prediction"
    )
    sklearn_preprocessing = require_optional_dependency(
        "sklearn.preprocessing", extra="ml", engine="scikit-learn", model_type=model_type, step="prediction"
    )
    sklearn_linear = require_optional_dependency(
        "sklearn.linear_model", extra="ml", engine="scikit-learn", model_type=model_type, step="prediction"
    )
    sklearn_ensemble = require_optional_dependency(
        "sklearn.ensemble", extra="ml", engine="scikit-learn", model_type=model_type, step="prediction"
    )

    def factory() -> Any:
        if model_type == "prediction_lasso":
            estimator = sklearn_linear.Lasso(alpha=1.0, random_state=random_seed, max_iter=5000)
        elif model_type == "prediction_ridge":
            estimator = sklearn_linear.Ridge(alpha=1.0)
        elif model_type == "prediction_random_forest":
            estimator = sklearn_ensemble.RandomForestRegressor(n_estimators=100, random_state=random_seed, n_jobs=1)
        else:
            raise ValueError(f"Unsupported v1.8.6 prediction model_type: {model_type}")
        return sklearn_pipeline.make_pipeline(sklearn_preprocessing.StandardScaler(), estimator)

    return factory


def run_prediction_model(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    y: str,
    x: list[str],
    model_type: str,
    model_id: str,
    cv_folds: int = 5,
    random_seed: int = 20260429,
    shuffle: bool = True,
    inputs: list[str] | None = None,
    sampling_method: str = "",
) -> dict[str, Any]:
    """Replay the historical prediction artifact path only.

    New runs must use :func:`run_prediction_model_v186`, whose explicit
    structure and persisted SplitPlan contract are fail-closed.  This helper
    remains for historical artifact replay and keeps its shuffle choice
    explicit so callers cannot mistake the old random split for the typed path.
    """
    if model_type not in _SUPPORTED_PREDICTION_MODEL_TYPES:
        raise ValueError(f"Unsupported prediction model_type: {model_type}")

    sklearn_model_selection = require_optional_dependency(
        "sklearn.model_selection",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_pipeline = require_optional_dependency(
        "sklearn.pipeline",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_preprocessing = require_optional_dependency(
        "sklearn.preprocessing",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_metrics = require_optional_dependency(
        "sklearn.metrics",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_linear = require_optional_dependency(
        "sklearn.linear_model",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )
    sklearn_ensemble = require_optional_dependency(
        "sklearn.ensemble",
        extra="ml",
        engine="scikit-learn",
        model_type=model_type,
        step="prediction",
    )

    data = frame[[y, *x]].dropna()
    if len(data) < 4:
        raise ValueError("Prediction models require at least four complete rows.")
    folds = min(max(int(cv_folds), 2), 5, len(data), max(len(data) // 2, 2))
    if len(data) <= 2:
        test_size = 1
    else:
        test_size = 0.25
    X = data[x]
    target = data[y]

    if model_type == "prediction_lasso":
        estimator = sklearn_linear.Lasso(
            alpha=1.0,
            random_state=random_seed,
            max_iter=5000,
        )
    elif model_type == "prediction_ridge":
        estimator = sklearn_linear.Ridge(alpha=1.0)
    else:
        estimator = sklearn_ensemble.RandomForestRegressor(
            n_estimators=100,
            random_state=random_seed,
            n_jobs=1,
        )

    pipeline = sklearn_pipeline.make_pipeline(
        sklearn_preprocessing.StandardScaler(),
        estimator,
    )
    X_train, X_test, y_train, y_test = sklearn_model_selection.train_test_split(
        X,
        target,
        test_size=test_size,
        shuffle=shuffle,
        random_state=random_seed if shuffle else None,
    )
    if sampling_method:
        _validate_sampling_target(target, sampling_method)
    sampler = build_sampler(
        sampling_method,
        model_type=model_type,
        random_seed=random_seed,
    )
    if sampler is not None:
        X_train, y_train = sampler.fit_resample(X_train, y_train)
    pipeline.fit(X_train, y_train)
    predictions = pipeline.predict(X_test)
    cv_scores = sklearn_model_selection.cross_val_score(
        pipeline,
        X,
        target,
        cv=sklearn_model_selection.KFold(
            n_splits=folds,
            shuffle=shuffle,
            random_state=random_seed if shuffle else None,
        ),
        scoring="r2",
    )
    result = {
        "schema_version": 1,
        "protocol": "legacy_random_split_v0",
        "historical_replay": True,
        "new_run_fallback": False,
        "replay_semantics": {
            "shuffle": bool(shuffle),
            "cv_shuffle": bool(shuffle),
            "cv_folds": int(folds),
            "random_seed": random_seed,
        },
        "model_id": model_id,
        "model_type": model_type,
        "engine": "scikit-learn",
        "status": "completed",
        "nobs": int(len(data)),
        "input_columns": {"y": y, "x": x},
        "cv_folds": int(folds),
        "sampling_method": sampling_method or None,
        "metrics": {
            "test_r2": _safe_metric(sklearn_metrics.r2_score(y_test, predictions)),
            "test_rmse": _rmse(sklearn_metrics, y_test, predictions),
            "cv_r2_mean": _safe_metric(cv_scores.mean()),
        },
        "warnings": [
            "Prediction results are not causal effects and are not regression inference."
        ],
    }
    output_dir = run_root / "prediction_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{model_id}.json"
    write_json(path, result)
    register_artifact(
        run_root,
        model_id,
        path,
        "prediction_result",
        "prediction",
        inputs or ["cleaned_dataset"],
    )
    return result


def build_sampler(
    sampling_method: str,
    *,
    model_type: str,
    random_seed: int,
) -> Any | None:
    if not sampling_method:
        return None
    if not model_type.startswith("prediction_"):
        raise ValueError("Imbalanced sampling is prediction-only and cannot feed inference models.")
    if sampling_method not in _SUPPORTED_SAMPLING_METHODS:
        raise ValueError(f"Unsupported sampling method: {sampling_method}")
    imblearn_over = require_optional_dependency(
        "imblearn.over_sampling",
        extra="imbalanced",
        engine="imbalanced-learn",
        model_type=model_type,
        step="prediction",
    )
    imblearn_under = require_optional_dependency(
        "imblearn.under_sampling",
        extra="imbalanced",
        engine="imbalanced-learn",
        model_type=model_type,
        step="prediction",
    )
    if sampling_method == "smote":
        return imblearn_over.SMOTE(random_state=random_seed)
    if sampling_method == "oversample":
        return imblearn_over.RandomOverSampler(random_state=random_seed)
    return imblearn_under.RandomUnderSampler(random_state=random_seed)


def _rmse(sklearn_metrics: Any, y_true: Any, predictions: Any) -> float | None:
    try:
        value = sklearn_metrics.mean_squared_error(
            y_true,
            predictions,
            squared=False,
        )
    except TypeError:
        value = sklearn_metrics.mean_squared_error(y_true, predictions) ** 0.5
    return _safe_metric(value)


def _safe_metric(value: Any) -> float | None:
    try:
        import math

        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _validate_sampling_target(target: pd.Series, sampling_method: str) -> None:
    unique_count = int(target.nunique(dropna=True))
    if unique_count < 2:
        raise ValueError("Imbalanced sampling requires at least two target classes.")
    if pd.api.types.is_float_dtype(target) and unique_count > min(10, max(len(target) // 2, 2)):
        raise ValueError(
            f"Imbalanced sampling requires a discrete target; {sampling_method} "
            "cannot be applied to a continuous prediction target."
        )
