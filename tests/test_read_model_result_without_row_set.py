"""Deferred figures decode a model result without its stored row_set list.

2026-11-09: after 70a3bc12 restored analysis_sample.row_set for v1.9.0 bytes, the 1M-row
OLS figure delivery peak footprint rose from 574 to 635 MiB (6 alternating runs each,
local/release-closeout-20261109/rowset-memory-ab): ensure_figures decoded both row lists,
and figures only use row_order. The file on disk is unchanged.
"""
from __future__ import annotations

import json

import pytest

from workbench import figure_plans
from workbench.artifacts import read_model_result_without_row_set, write_json

ODD_IDS = ["10", "2", "10", "é", "é", "a\nb", '"', "]", "\n    ]", "x\\", " ", "0"]


def _result(order, *, row_set=None):
    return {"schema_version": 1, "model_id": "ols_1", "nobs": len(order),
            "coefficients": {"x": {"estimate": 1.5, "std_error": 0.25}},
            "analysis_sample": {"row_set": sorted(order) if row_set is None else row_set,
                                "row_order": order, "fingerprint": "f" * 64},
            "after": [[1, 2], {"row_order": ["not", "this"]}]}


def _expected(payload):
    expected = json.loads(json.dumps(payload))
    del expected["analysis_sample"]["row_set"]
    return expected


@pytest.mark.parametrize("order", [ODD_IDS, [str(i) for i in range(2000)], ["only"]])
def test_the_row_set_is_skipped_and_everything_else_decodes_unchanged(tmp_path, order):
    path = tmp_path / "ols_1.json"
    write_json(path, _result(order))
    decoded = read_model_result_without_row_set(path)
    assert decoded == _expected(_result(order))
    assert list(decoded["analysis_sample"]) == ["row_order", "fingerprint"]


@pytest.mark.parametrize("layout", ["compact", "single_list", "empty"])
def test_any_other_layout_is_decoded_whole(tmp_path, layout):
    path = tmp_path / "ols_1.json"
    if layout == "compact":
        payload = _result(ODD_IDS)
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif layout == "single_list":
        payload = _result(ODD_IDS)
        del payload["analysis_sample"]["row_set"]
        write_json(path, payload)
    else:  # an empty list has no closing line; a later "row_order" list must not end the skip
        payload = _result([], row_set=[])
        payload["later"] = {"values": [1], "row_order": ["kept"]}
        write_json(path, payload)
    assert read_model_result_without_row_set(path) == json.loads(path.read_text(encoding="utf-8"))


def test_deferred_figures_read_model_results_without_the_row_set(tmp_path, monkeypatch):
    captured = {}

    def create_figures(frame, run_root, *, model_results, **options):
        captured["results"] = model_results
        return []

    run = tmp_path / "run"
    (run / "figures").mkdir(parents=True)
    (run / "model_results").mkdir()
    write_json(run / "model_results" / "ols_1.json", _result(ODD_IDS))
    original = (run / "model_results" / "ols_1.json").read_bytes()
    monkeypatch.setattr(figure_plans, "_artifact_paths", lambda root: {
        "cleaned_dataset": root / "data.parquet", "ols_1": root / "model_results" / "ols_1.json"})
    import pandas as pd
    pd.DataFrame({"x": [1.0]}).to_parquet(run / "data.parquet")
    write_json(run / figure_plans.FIGURE_PLAN, {"model_result_ids": ["ols_1"], "options": {}})
    import workbench.visualization as visualization
    monkeypatch.setattr(visualization, "create_figures", create_figures)
    figure_plans.ensure_figures(run)
    [(name, result)] = captured["results"]
    assert name == "ols_1" and "row_set" not in result["analysis_sample"]
    assert result["analysis_sample"]["row_order"] == ODD_IDS
    assert (run / "model_results" / "ols_1.json").read_bytes() == original


@pytest.mark.parametrize("stored", ["both_lists", "single_list"])
def test_a_reader_of_no_sample_row_gets_only_the_fingerprint(tmp_path, stored):
    from workbench.artifacts import read_model_result_without_sample_rows

    payload = _result(ODD_IDS)
    if stored == "single_list":
        del payload["analysis_sample"]["row_set"]
    path = tmp_path / "ols_1.json"
    write_json(path, payload)
    expected = json.loads(path.read_text(encoding="utf-8"))
    expected["analysis_sample"] = {"fingerprint": expected["analysis_sample"]["fingerprint"]}
    assert read_model_result_without_sample_rows(path) == expected


def test_the_report_survey_facts_are_unchanged_and_skip_the_rows(tmp_path, monkeypatch):
    from workbench import report_view_model

    run = tmp_path / "run"
    (run / "model_results").mkdir(parents=True)
    payload = _result(ODD_IDS)
    payload["survey_design"] = {"variance_method": "linearization", "n_strata": 4, "n_psu": 38,
                                "strata_column": "region", "psu_column": "school", "design_effect": 1.7,
                                "effective_sample_size": 412.5}
    write_json(run / "model_results" / "ols_1.json", payload)
    whole = report_view_model.read_json
    expected = None
    monkeypatch.setattr(report_view_model, "read_model_result_without_sample_rows", whole)
    expected = report_view_model._survey_design_facts(run)
    monkeypatch.undo()
    decoded = []
    from workbench import artifacts
    original = artifacts.read_model_result_without_sample_rows
    monkeypatch.setattr(report_view_model, "read_model_result_without_sample_rows",
                        lambda path: decoded.append(original(path)) or decoded[-1])
    assert expected and report_view_model._survey_design_facts(run) == expected
    assert decoded and "row_order" not in decoded[0]["analysis_sample"]


def test_the_run_manifest_summaries_skip_the_sample_rows_and_say_the_same(tmp_path, monkeypatch):
    from workbench.orchestrator import _manifest

    run = tmp_path / "run"
    (run / "model_results").mkdir(parents=True)
    payload = {**_result(ODD_IDS), "contract_version": "ols_result_contract_v1", "model": "ols",
               "model_type": "ols", "covariance": "HC1", "stable_result_ids": ["r1"]}
    write_json(run / "model_results" / "ols_1.json", payload)
    expected = (_manifest._primary_model_summary(run), _manifest._result_contract_summary(run))

    def refuse(path):
        raise AssertionError(f"decoded whole: {path}")

    monkeypatch.setattr(_manifest, "read_json", refuse)
    assert (_manifest._primary_model_summary(run), _manifest._result_contract_summary(run)) == expected
    assert expected[0]["model_id"] == "ols_1" and expected[1]["covariance"] == "HC1"
