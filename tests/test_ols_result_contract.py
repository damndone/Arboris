import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import statsmodels.formula.api as smf

from workbench.analysis_loop.fingerprints import inference_config_fingerprint
from workbench.econometrics.runner import run_ols
from workbench.lineage.run_inputs import read_run_inputs, write_run_inputs
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.services.results_service import (
    read_coefficient_by_result_id,
    validate_result_contract,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "y": [1.0, 2.2, 3.1, 4.4, 5.0, 6.3, 7.2, 8.1],
            "x": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
            "firm": ["a", "a", "b", "b", "c", "c", "d", "d"],
        },
        index=[f"row-{i}" for i in range(8)],
    )


def _run(frame: pd.DataFrame, **kwargs):
    return run_ols(
        frame.copy(),
        y="y",
        x=["x"],
        model_id="ols_1",
        categorical_x=set(),
        row_ids=list(frame.index),
        dataset_snapshot={"upload_sha256": "a" * 64},
        **kwargs,
    )


def _cluster_fitted(frame: pd.DataFrame):
    original = smf.ols("y ~ x", data=frame).fit()
    return original.get_robustcov_results(
        cov_type="cluster",
        groups=frame["firm"].to_numpy(copy=True),
        use_correction=True,
        df_correction=True,
        use_t=False,
    )


def test_unadjusted_ols_emits_contract_ids_and_fingerprints():
    result, _ = _run(
        _frame(),
        robust=False,
        covariance="unadjusted",
        covariance_explicit=True,
        focal_x=["x"],
    )

    assert result["contract_version"] == "ols_result_contract_v1"
    assert result["model"] == "ols"
    assert result["model_type"] == "ols"
    assert result["covariance"] == "unadjusted"
    assert result["covariance_wire"] == "unadjusted"
    assert result["source_eligible"] is True
    assert result["stable_result_ids"] == result["candidate_result_ids"]
    assert result["stable_result_ids"]
    assert result["primary_estimand"]["result_id"] in result["stable_result_ids"]

    for term, coefficient in result["coefficients"].items():
        assert coefficient["result_id"] in result["stable_result_ids"]
        assert coefficient["candidate_result_id"] == coefficient["result_id"]
        assert coefficient["coefficient_identity"] == f"ols:ols_1:{term}"
        assert coefficient["coefficient_term"] == term
        assert result["result_id_by_source_id"][coefficient["source_id"]] == coefficient["result_id"]

    for field in (
        "dataset_snapshot_fingerprint",
        "analysis_sample_fingerprint",
        "point_estimation_fingerprint",
        "coefficient_schema_fingerprint",
        "inference_config_fingerprint",
    ):
        assert isinstance(result[field], str) and len(result[field]) == 64
    assert result["analysis_sample"]["row_order"] == list(_frame().index)


def test_unadjusted_contract_records_statsmodels_t_inference_semantics():
    result, _ = _run(
        _frame(),
        robust=False,
        covariance="unadjusted",
        covariance_explicit=True,
    )
    fitted = smf.ols("y ~ x", data=_frame()).fit()
    evidence = result["covariance_evidence"]

    assert fitted.use_t is True
    assert evidence["use_t"] is True
    assert evidence["inference_distribution"] == "t"
    assert evidence["p_value_method"] == "t"
    assert evidence["confidence_interval_method"] == "t"
    assert evidence["effective_df"] == pytest.approx(fitted.df_resid)

    confidence_intervals = fitted.conf_int()
    for position, (term, coefficient) in enumerate(result["coefficients"].items()):
        assert coefficient["p_value"] == pytest.approx(
            round(float(fitted.pvalues.iloc[position]), 6)
        )
        assert coefficient["ci_lower"] == pytest.approx(
            float(confidence_intervals.iloc[position, 0])
        )
        assert coefficient["ci_upper"] == pytest.approx(
            float(confidence_intervals.iloc[position, 1])
        )

    assert result["inference_config_fingerprint"] == inference_config_fingerprint(
        covariance="unadjusted",
        cluster_var=None,
        cluster_count=0,
        corrections={
            "small_sample_correction": False,
            "degrees_of_freedom_correction": False,
        },
        df=float(fitted.df_resid),
        use_t=True,
        confidence_level=0.95,
        engine="statsmodels",
        version=evidence["library_version"],
        inference_distribution="t",
        p_value_method="t",
        confidence_interval_method="t",
    )


def test_default_robust_remains_hc1_and_is_not_source_eligible():
    result, _ = _run(_frame(), robust=True)

    assert result["model_type"] == "ols_robust"
    assert result["covariance"] == "robust"
    assert result["covariance_estimator"] == "HC1"
    assert result["source_eligible"] is False


def test_clustered_covariance_changes_only_inference_and_records_evidence():
    source, _ = _run(
        _frame(),
        robust=False,
        covariance="unadjusted",
        covariance_explicit=True,
        focal_x=["x"],
    )
    child, _ = _run(
        _frame(),
        robust=False,
        covariance="clustered",
        covariance_explicit=True,
        cluster_col="firm",
        focal_x=["x"],
    )

    assert child["model_type"] == "ols_clustered"
    assert child["formula"] == source["formula"]
    assert child["x_columns"] == source["x_columns"] == ["x"]
    assert child["analysis_sample"] == source["analysis_sample"]
    assert child["point_estimation_fingerprint"] == source["point_estimation_fingerprint"]
    assert child["coefficient_schema_fingerprint"] == source["coefficient_schema_fingerprint"]
    assert child["stable_result_ids"] == source["stable_result_ids"]
    assert child["inference_config_fingerprint"] != source["inference_config_fingerprint"]
    assert child["dataset_snapshot_fingerprint"] == source["dataset_snapshot_fingerprint"]
    assert child["coefficients"]["x"]["estimate"] == pytest.approx(source["coefficients"]["x"]["estimate"])
    assert child["coefficients"]["x"]["std_error"] != source["coefficients"]["x"]["std_error"]

    evidence = child["covariance_evidence"]
    assert evidence["covariance"] == "clustered"
    assert evidence["cluster_variable"] == "firm"
    assert evidence["entity_col"] == "firm"
    assert evidence["small_sample_correction"] is True
    assert evidence["degrees_of_freedom_correction"] is True
    assert evidence["use_t"] is False
    assert evidence["inference_distribution"] == "normal"
    assert evidence["p_value_method"] == "normal_z"
    assert evidence["confidence_interval_method"] == "normal_z"
    assert evidence["effective_df"] is not None
    fitted = _cluster_fitted(_frame())
    assert evidence["effective_df"] == pytest.approx(
        getattr(fitted, "df_resid_inference", fitted.df_resid)
    )
    assert evidence["engine"] == "statsmodels"
    assert evidence["library_version"]
    assert evidence["cluster_count"] == 4
    assert len(evidence["group_vector_fingerprint"]) == 64


def test_clustered_contract_uses_statsmodels_inference_df_for_pvalues_and_ci():
    result, _ = _run(
        _frame(),
        robust=False,
        covariance="clustered",
        covariance_explicit=True,
        cluster_col="firm",
    )

    fitted = _cluster_fitted(_frame())
    expected_df = getattr(fitted, "df_resid_inference", fitted.df_resid)
    assert expected_df != fitted.df_resid
    assert result["covariance_evidence"]["effective_df"] == pytest.approx(expected_df)
    assert result["inference_config"]["effective_df"] == pytest.approx(expected_df)
    evidence = result["covariance_evidence"]
    assert result["inference_config_fingerprint"] == inference_config_fingerprint(
        covariance=evidence["covariance"],
        cluster_var=evidence["cluster_variable"],
        cluster_count=evidence["cluster_count"],
        corrections={
            "small_sample_correction": evidence["small_sample_correction"],
            "degrees_of_freedom_correction": evidence["degrees_of_freedom_correction"],
        },
        df=expected_df,
        use_t=evidence["use_t"],
        confidence_level=0.95,
        engine=evidence["engine"],
        version=evidence["library_version"],
        inference_distribution=evidence["inference_distribution"],
        p_value_method=evidence["p_value_method"],
        confidence_interval_method=evidence["confidence_interval_method"],
        cluster_group_vector_fingerprint=evidence["group_vector_fingerprint"],
    )

    confidence_intervals = fitted.conf_int()
    for position, (term, coefficient) in enumerate(result["coefficients"].items()):
        assert coefficient["p_value"] == pytest.approx(
            round(float(fitted.pvalues[position]), 6)
        )
        assert coefficient["ci_lower"] == pytest.approx(
            float(confidence_intervals[position][0])
        )
        assert coefficient["ci_upper"] == pytest.approx(
            float(confidence_intervals[position][1])
        )


@pytest.mark.parametrize(
    ("robust", "covariance"),
    [(False, "unadjusted"), (True, "robust")],
)
def test_duplicate_index_nonclustered_ols_uses_occurrence_row_ids(robust, covariance):
    frame = _frame().set_axis(["duplicate"] * len(_frame()))
    expected, _ = _run(
        _frame(),
        robust=robust,
        covariance=covariance,
        covariance_explicit=True,
    )

    result, fitted = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=robust,
        covariance=covariance,
        covariance_explicit=True,
        model_id="ols_1",
    )

    assert fitted.nobs == len(frame)
    assert result["coefficients"]["x"]["estimate"] == pytest.approx(
        expected["coefficients"]["x"]["estimate"]
    )
    row_order = result["analysis_sample"]["row_order"]
    assert len(row_order) == len(frame)
    assert len(set(row_order)) == len(frame)


def test_duplicate_index_clustered_ols_aligns_groups_by_occurrence():
    frame = _frame().set_axis(["duplicate"] * len(_frame()))

    result, fitted = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=False,
        covariance="clustered",
        covariance_explicit=True,
        cluster_col="firm",
        model_id="ols_1",
    )

    assert fitted.nobs == len(frame)
    row_order = result["analysis_sample"]["row_order"]
    assert len(row_order) == len(frame)
    assert len(set(row_order)) == len(frame)
    assert result["covariance_evidence"]["cluster_count"] == 4


def test_analysis_row_ids_are_collision_safe_after_stringification():
    frame = _frame().set_axis([1, "1", 2, "2", 3, "3", 4, "4"])

    result, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=False,
        covariance="unadjusted",
        covariance_explicit=True,
        model_id="ols_1",
    )

    row_order = result["analysis_sample"]["row_order"]
    assert len(row_order) == len(frame)
    assert len(set(row_order)) == len(frame)
    assert row_order[0] != row_order[1]


def test_analysis_row_ids_preserve_timestamp_vs_string_type_identity():
    timestamps = [pd.Timestamp("2020-01-01") + pd.Timedelta(days=index) for index in range(4)]
    index = [value for timestamp in timestamps for value in (timestamp, timestamp.isoformat())]
    frame = _frame().set_axis(index)

    result, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=False,
        covariance="unadjusted",
        covariance_explicit=True,
        model_id="ols_1",
    )

    row_order = result["analysis_sample"]["row_order"]
    assert len(row_order) == len(frame)
    assert len(set(row_order)) == len(frame)
    assert row_order[0] != row_order[1]


@pytest.mark.parametrize(
    ("cluster_values", "error_code"),
    [
        ([1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0], "OLS_CLUSTER_TYPE_UNSUPPORTED"),
        ([True, True, False, False, True, True, False, False], "OLS_CLUSTER_TYPE_UNSUPPORTED"),
        ([1, 1, "b", "b", 3, 3, "d", "d"], "OLS_CLUSTER_TYPE_MIXED"),
    ],
)
def test_clustered_covariance_rejects_policy_disallowed_group_types(
    cluster_values, error_code
):
    frame = _frame().assign(firm=cluster_values)

    with pytest.raises(ValueError, match=error_code):
        _run(
            frame,
            robust=False,
            covariance="clustered",
            covariance_explicit=True,
            cluster_col="firm",
        )


def test_clustered_covariance_accepts_category_group_dtype():
    frame = _frame().copy()
    frame["firm"] = pd.Categorical(frame["firm"])

    result, _ = _run(
        frame,
        robust=False,
        covariance="clustered",
        covariance_explicit=True,
        cluster_col="firm",
    )

    assert result["covariance_evidence"]["cluster_count"] == 4


def test_clustered_covariance_rejects_null_entity_on_dropped_y_x_row():
    frame = _frame().copy()
    frame.loc["row-2", "y"] = np.nan
    frame.loc["row-2", "firm"] = None

    with pytest.raises(ValueError, match="OLS_CLUSTER_VALUES_MISSING"):
        _run(
            frame,
            robust=False,
            covariance="clustered",
            covariance_explicit=True,
            cluster_col="firm",
        )


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (lambda frame: frame.drop(columns=["firm"]), "OLS_CLUSTER_FIELD_MISSING"),
        (lambda frame: frame.assign(firm=["a", "a", None, "b", "c", "c", "d", "d"]), "OLS_CLUSTER_VALUES_MISSING"),
        (lambda frame: frame.assign(firm=["a", "a", "b", "b", np.nan, "c", "d", "d"]), "OLS_CLUSTER_VALUES_MISSING"),
        (lambda frame: frame, "OLS_CLUSTER_ROW_ALIGNMENT"),
    ],
)
def test_clustered_covariance_fails_closed_without_silent_sample_changes(mutator, error_code):
    frame = mutator(_frame())
    kwargs = {"robust": False, "covariance": "clustered", "cluster_col": "firm"}
    if error_code == "OLS_CLUSTER_ROW_ALIGNMENT":
        kwargs["cluster_row_ids"] = list(reversed(frame.index))

    with pytest.raises(ValueError, match=error_code):
        _run(frame, **kwargs)


def test_cluster_column_cannot_be_in_the_ols_design():
    with pytest.raises(ValueError, match="OLS_CLUSTER_FIELD_CONFLICT"):
        run_ols(
            _frame(),
            y="y",
            x=["x", "firm"],
            robust=False,
            covariance="clustered",
            cluster_col="firm",
            model_id="ols_1",
        )


def test_primary_estimand_never_comes_from_display_label_or_fuzzy_match():
    result, _ = run_ols(
        _frame(),
        y="y",
        x=["x"],
        robust=False,
        covariance="unadjusted",
        model_id="ols_1",
        focal_x=["X"],
    )

    assert result["primary_estimand"] is None


def test_run_inputs_and_model_result_contract_round_trip(tmp_path: Path):
    result, _ = _run(
        _frame(),
        robust=False,
        covariance="clustered",
        covariance_explicit=True,
        cluster_col="firm",
    )
    result_path = tmp_path / "model_results" / "ols_1.json"
    result_path.parent.mkdir()
    result_path.write_text(json.dumps(result), encoding="utf-8")

    write_run_inputs(
        tmp_path,
        form={
            "model_type": "ols",
            "covariance": "clustered",
            "entity_col": "firm",
            "y": "y",
            "x": "x",
            "api_key": "secret",
        },
        upload={"sha256": "a" * 64, "filename": "d.csv"},
        rerun_of="run_source",
        from_node="model:ols_1",
        rerun_reason="analysis_loop",
        override_hash="override-hash",
        dag_hash="d" * 64,
        source_lineage={
            "source_run_id": "run_source",
            "from_node": "model:ols_1",
        },
        contract_summary={
            "contract_version": result["contract_version"],
            "model_type": "ols",
            "covariance": "clustered",
            "entity_col": "firm",
        },
        executable_payload={"covariance": "clustered", "entity_col": "firm"},
        rerun_inputs={"rerun_of": "run_source", "from_node": "model:ols_1"},
        confirmed_payload={"covariance": "clustered", "entity_col": "firm"},
        executed_payload={"covariance": "clustered", "entity_col": "firm"},
        contract_metadata={"fingerprints": {"point": result["point_estimation_fingerprint"]}},
    )

    stored = read_run_inputs(tmp_path)
    assert stored["form"]["api_key"] == "***"
    assert stored["form"]["covariance"] == "clustered"
    assert stored["contract_summary"]["entity_col"] == "firm"
    assert stored["executable_payload"]["entity_col"] == "firm"
    assert stored["rerun_inputs"]["rerun_of"] == "run_source"
    assert stored["source_lineage"]["source_run_id"] == "run_source"
    assert stored["confirmed_payload"] == stored["executed_payload"]
    loaded_result = json.loads(result_path.read_text())
    assert validate_result_contract(loaded_result)["contract_version"] == "ols_result_contract_v1"
    assert loaded_result["coefficients"]
    assert read_coefficient_by_result_id(
        loaded_result, result["stable_result_ids"][0]
    ) is not None


def test_completed_workflow_manifest_exposes_ols_contract_summary(tmp_path: Path):
    project = create_project(tmp_path, "contract-run")
    source = tmp_path / "data.csv"
    workflow_frame = pd.DataFrame(
        {
            "y": [1.0 + 0.5 * i for i in range(40)],
            "x": list(range(40)),
        }
    )
    workflow_frame.to_csv(source, index=False)

    run = run_workflow(
        project.root,
        [source],
        mode="explicit",
        y="y",
        x=["x"],
        model_type="ols",
        covariance="unadjusted",
    )
    run_root = project.root / "runs" / run["run_id"]
    manifest = json.loads((run_root / "run_manifest.json").read_text())
    model_result = json.loads(
        (run_root / "model_results" / "ols_1.json").read_text()
    )

    assert manifest["result_contract"]["contract_version"] == "ols_result_contract_v1"
    assert manifest["result_contract"]["stable_result_ids"] == model_result["stable_result_ids"]
    assert manifest["result_contract"]["inference_config_fingerprint"] == model_result[
        "inference_config_fingerprint"
    ]
    run_inputs = json.loads((run_root / "run_inputs.json").read_text())
    assert run_inputs["form"]["model_type"] == "ols"
    assert run_inputs["form"]["covariance"] == "unadjusted"
    assert run_inputs["executable_payload"]["model_type"] == "ols"
    assert run_inputs["contract_summary"]["covariance"] == "unadjusted"
    assert len(run_inputs["upload"]["sha256"]) == 64


def test_direct_workflow_run_inputs_round_trip_preserves_did_cs_honest_wire_fields(
    tmp_path: Path,
):
    project = create_project(tmp_path, "direct-wire-round-trip")
    source = tmp_path / "data.csv"
    pd.DataFrame(
        {
            "y": [1.0 + 0.5 * i for i in range(40)],
            "x": list(range(40)),
        }
    ).to_csv(source, index=False)

    run = run_workflow(
        project.root,
        [source],
        mode="explicit",
        y="y",
        x=["x"],
        model_type="ols",
        covariance="unadjusted",
        did_mode="twfe",
        did_cohort_col="cohort",
        did_treat_col="treated",
        did_post_col="post",
        did_status_col="status",
        did_treatment_path="treatment_path",
        cs_control_group="not_yet_treated",
        cs_est_method="dr",
        cs_base_period="universal",
        cs_anticipation=2,
        cs_cluster_var="firm",
        honest_did=True,
    )

    run_inputs = json.loads(
        (project.root / "runs" / run["run_id"] / "run_inputs.json").read_text()
    )
    expected = {
        "did_mode": "twfe",
        "did_cohort_col": "cohort",
        "did_treat_col": "treated",
        "did_post_col": "post",
        "did_status_col": "status",
        "did_treatment_path": "treatment_path",
        "cs_control_group": "not_yet_treated",
        "cs_est_method": "dr",
        "cs_base_period": "universal",
        "cs_anticipation": "2",
        "cs_cluster_var": "firm",
        "honest_did": "true",
    }
    for field, value in expected.items():
        assert run_inputs["form"][field] == value
        assert run_inputs["executable_payload"]["form"][field] == value
