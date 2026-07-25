"""Contract tests for the OLS Agent model_options seam."""

from __future__ import annotations

import pytest
import pandas as pd

from workbench.agent.recipes.registry import build_option_vocabulary
from workbench.artifacts import read_json
from workbench.engine.capabilities import build_capabilities
from workbench.model_options import ModelOptionsError, bind_new_model_options
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.services.draft_materialization import normalize_ols_genesis_model_params


def test_ols_model_options_binds_as_a_server_owned_contract() -> None:
    bound = bind_new_model_options("ols", {"covariance": "unadjusted"})

    assert bound.payload == {"covariance": "unadjusted"}
    assert bound.binding is not None
    assert bound.binding.owner_model_type == "ols"
    assert bound.binding.owner_model_id == "ols_1"
    assert bound.binding.producer_version == "ols@1.0"
    assert bound.binding.input_contract_version == "ols_model_options@1.0"


@pytest.mark.parametrize("covariance", ["robust", "clustered", "unadjusted"])
def test_ols_model_options_accepts_the_published_covariance_values(
    covariance: str,
) -> None:
    assert bind_new_model_options("ols", {"covariance": covariance}).payload == {
        "covariance": covariance
    }


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"covariance": "hc2"}, "OLS_MODEL_OPTIONS_INVALID_COVARIANCE"),
        ({"covariance": "robust", "future": True}, "OLS_MODEL_OPTIONS_UNKNOWN_FIELD"),
        ({"covariance": 1}, "OLS_MODEL_OPTIONS_INVALID_COVARIANCE"),
    ],
)
def test_ols_model_options_fails_closed(payload: dict[str, object], code: str) -> None:
    with pytest.raises(ModelOptionsError) as error:
        bind_new_model_options("ols", payload)

    assert error.value.code == code


def test_ols_capability_advertises_a_model_options_owner_without_removing_covariance_ui() -> None:
    ols = next(item for item in build_capabilities()["model_types"] if item["key"] == "ols")
    params = {item["key"]: item for item in ols["params"]}

    assert params["covariance"]["kind"] == "select"
    assert params["model_options"]["role"] == "model_options"


def test_ols_agent_vocabulary_is_bounded_to_covariance() -> None:
    vocabulary = build_option_vocabulary("ols")

    assert vocabulary is not None
    assert vocabulary["version"] == "ols-model-options/v1"
    assert vocabulary["fields"]["covariance"]["allowed_values"] == [
        "robust",
        "clustered",
        "unadjusted",
    ]


def test_ols_genesis_keeps_the_bound_agent_envelope_and_legacy_covariance_projection() -> None:
    normalized = normalize_ols_genesis_model_params(
        {"model_type": "ols", "model_options": {"covariance": "unadjusted"}}
    )

    assert normalized["covariance"] == "unadjusted"
    assert normalized["model_options"] == {"covariance": "unadjusted"}


def test_nested_ols_covariance_changes_the_actual_fit_and_persisted_execution_input(
    tmp_path,
) -> None:
    source = tmp_path / "source.csv"
    pd.DataFrame(
        {
            "y": [1.0 + 2.0 * index + (index % 3) * 0.25 for index in range(40)],
            "x": list(range(40)),
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "ols-model-options-execution")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="ols",
        covariance="robust",
        model_options={"covariance": "unadjusted"},
    )

    run_root = project.root / "runs" / result["run_id"]
    inputs = read_json(run_root / "run_inputs.json")
    model_result = read_json(run_root / "model_results" / "ols_1.json")

    assert inputs["form"]["covariance"] == "unadjusted"
    assert inputs["executable_payload"]["covariance"] == "unadjusted"
    assert inputs["form"]["model_options"] == {"covariance": "unadjusted"}
    assert inputs["form"]["model_options_binding"]["owner_model_type"] == "ols"
    assert model_result["covariance_wire"] == "unadjusted"
