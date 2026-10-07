"""Exported scripts still run standalone, one fresh process each.

The script-export tests run scripts in one warm interpreter per language
(tests/native_runner.py). These cases rerun a representative set the original
way, `python script.py`, `Rscript script.R` and `stata -b do script.do`, so a
script that only works after another script ran in the same interpreter
cannot pass: data operations, a model, post-estimation, the survey FPC
adapter and a script continuing from a Workbench result sidecar.
"""
import pytest

import native_runner
# Modules, not functions: imported test functions would be collected twice.
import test_script_export_basic_oracle as basic
import test_script_export_data_oracles as data
import test_script_export_postestimation_oracles as postestimation
import test_script_export_result_sidecars as sidecars
import test_script_export_v1811_statistical_adapters as adapters

LANGUAGES = ("stata", "r", "python")


@pytest.fixture(autouse=True)
def cold_process(monkeypatch):
    monkeypatch.setenv("WORKBENCH_NATIVE_COLD", "1")
    assert native_runner.cold()


@pytest.mark.parametrize("language", LANGUAGES)
def test_basic_path_runs_in_a_fresh_process(language):
    assert native_runner.describe(language, "s")[0] != "warm-interpreter"
    basic.test_validated_basic_real_registry_runner(language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_data_operation_runs_in_a_fresh_process(language):
    data.test_data_operation_native_oracle("subset", language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_postestimation_runs_in_a_fresh_process(language):
    postestimation.test_postestimation_native_kernel_oracle(("ols_clustered", "wald"), language)


@pytest.mark.parametrize("language", LANGUAGES)
def test_survey_fpc_runs_in_a_fresh_process(language, monkeypatch):
    adapters.test_approved_single_stage_fpc_is_executed_natively(language, "population", monkeypatch)


@pytest.mark.parametrize("language", LANGUAGES)
def test_result_sidecar_continuation_runs_in_a_fresh_process(language, monkeypatch):
    sidecars.test_actual_model_post_closure_then_independent_native_model(language, monkeypatch)
