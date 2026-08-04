from __future__ import annotations

import pytest

from workbench.predictive_research.contracts import (
    AvailabilitySpecV1,
    ContractError,
    FeatureRecipeV1,
    SampleSpecV1,
    SamplingSpecV1,
    SplitPlanV1,
    StructureSpecV1,
)
from workbench.predictive_research.schema import PayloadContractError, PayloadSchemaRegistry


def make_sample_spec(**overrides: object) -> SampleSpecV1:
    values: dict[str, object] = {
        "dataset_sha256": "a" * 64,
        "sampling": SamplingSpecV1(),
        "split_plan": SplitPlanV1(
            strategy="iid",
            profile_id="iid_holdout_kfold",
            profile_version=1,
            effective_parameters={
                "final_holdout_fraction": 0.2,
                "cv_folds": 3,
                "shuffle": True,
                "random_seed": 7,
            },
        ),
        "structure": StructureSpecV1(kind="iid", provenance="user_confirmed"),
        "availability": AvailabilitySpecV1(kind="declared", reservation_policy="fail_closed"),
    }
    values.update(overrides)
    return SampleSpecV1(**values)


def test_unknown_structure_is_not_treated_as_iid() -> None:
    spec = make_sample_spec(structure=StructureSpecV1(kind="unknown", provenance="inferred"))

    with pytest.raises(ContractError) as error:
        spec.validate()

    assert error.value.code == "PREDICTION_DATA_STRUCTURE_UNKNOWN"


def test_sampling_weight_semantics_cannot_be_collapsed() -> None:
    spec = make_sample_spec(
        sampling=SamplingSpecV1(
            sampling_weight="weight",
            analysis_weight="weight",
        )
    )

    with pytest.raises(ContractError) as error:
        spec.validate()

    assert error.value.code == "PREDICTION_WEIGHT_SEMANTICS_CONFLICT"


def test_temporal_split_preserves_declared_parameters_but_fails_closed_for_m0() -> None:
    spec = make_sample_spec(
        structure=StructureSpecV1(kind="temporal", time_column="as_of", provenance="user_confirmed"),
        split_plan=SplitPlanV1(
            strategy="temporal",
            profile_id="blocked_time",
            profile_version=1,
            effective_parameters={
                "time_column": "as_of",
                "gap": 2,
                "embargo": 1,
                "random_seed": 7,
            },
        ),
    )

    with pytest.raises(ContractError) as error:
        spec.validate(executable_profiles={"iid_holdout_kfold", "grouped_holdout_groupkfold"})

    assert error.value.code == "PREDICTION_SPLIT_PROFILE_NOT_SUPPORTED"
    assert spec.split_plan.effective_parameters["gap"] == 2
    assert spec.split_plan.effective_parameters["embargo"] == 1


def test_feature_recipe_rejects_unregistered_or_arbitrary_operation() -> None:
    recipe = FeatureRecipeV1(
        recipe_id="recipe-1",
        operation_id="python_eval",
        operation_version=1,
        inputs=("x",),
        outputs=("x2",),
        output_types=("float",),
        parameters={"expression": "x + 1"},
        fit_scope="stateless",
        source_artifact="sha256:" + "b" * 64,
    )

    with pytest.raises(ContractError) as error:
        recipe.validate()

    assert error.value.code == "PREDICTION_FEATURE_RECIPE_UNKNOWN_OPERATION"


def test_payload_registry_rejects_unknown_version_and_missing_contract() -> None:
    registry = PayloadSchemaRegistry()
    registry.register("workbench.prediction.sample-spec", 1, required_fields={"schema_version", "payload_schema"})

    with pytest.raises(PayloadContractError) as missing:
        registry.validate({"schema_version": 1})
    assert missing.value.code == "ARTIFACT_PAYLOAD_CONTRACT_REQUIRED"

    with pytest.raises(PayloadContractError) as unknown:
        registry.validate(
            {
                "payload_schema": "workbench.prediction.sample-spec",
                "schema_version": 99,
            }
        )
    assert unknown.value.code == "ARTIFACT_PAYLOAD_SCHEMA_VERSION_UNSUPPORTED"
