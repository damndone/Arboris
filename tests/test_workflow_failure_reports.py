"""A repeated plan reuses its result, and a refusal says what the data has and what would work."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from tests.test_matching_pack import _frame, _policy
from workbench.agent.completion_targets import computed_result
from workbench.agent.p7_pack_adapters.base import P7PackAdapterError, _require_columns
from workbench.agent.p7_pack_adapters.synthetic_power import validate_synthetic_frame_request
from workbench.agent.postestimation_steps import _load_kernel
from workbench.agent.workflow_runtime_parts.datasets import _persist_numeric_derivation
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.data_operations import DataTransformSpecV1, apply_data_transform, preview_data_transform
from workbench.data_operations.frames import _write_frame_artifact
from workbench.engine.packs.matching import estimate_att
from workbench.statistical_exploration import ExplorationSpec, execute_exploration
from workbench.statistical_tests import run_statistical_tests


def test_the_same_reshape_runs_again_from_a_later_plan(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path, pd.DataFrame({"year": [1, 1, 2, 2], "state": [3, 4, 3, 4], "sales": [1.5, 2.5, 3.5, 4.5]})
    )
    spec = DataTransformSpecV1(
        source_run_id=run_id, source_node_id="stage:source", source_artifact_id=artifact_id, operation="reshape",
        parameters={"direction": "long_to_wide", "index": ["year"], "columns": "state", "values": "sales"},
    )
    first = apply_data_transform(project, spec, preview_data_transform(project, spec))
    second = apply_data_transform(project, spec, preview_data_transform(project, spec))
    assert second.child_node_id == first.child_node_id


def test_a_different_result_at_the_same_path_is_still_refused(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    _write_frame_artifact(path, pd.DataFrame({"a": [1]}), "csv")
    with pytest.raises(Exception, match="path is occupied"):
        _write_frame_artifact(path, pd.DataFrame({"a": [2]}), "csv")


def _derive(root: Path, workflow_id: str, step_id: str, values: list[int]):
    return _persist_numeric_derivation(
        root=root,
        draft=SimpleNamespace(workflow_id=workflow_id, target={"run_id": "r"}),
        lineage={"artifact_id": "cleaned_dataset", "sha256": "s", "node_ref": "stage:cleaned"},
        frame=pd.DataFrame({"a": values, "b": values}),
        step=SimpleNamespace(
            step_id=step_id, fingerprint="sha256:same",
            spec={"recipes": [{"input_columns": ["a", "b"], "operator": "multiply", "output_name": "c"}]},
        ),
    )


def test_the_same_derivation_from_a_later_plan_is_the_same_result(tmp_path: Path) -> None:
    (tmp_path / "runs" / "r").mkdir(parents=True)
    (tmp_path / "runs" / "r" / "artifacts_index.json").write_text('{"artifacts": []}')
    _derive(tmp_path, "workflow_one", "make", [1, 2])
    _derive(tmp_path, "workflow_two", "other_name", [1, 2])
    recipe = next((tmp_path / "runs" / "r" / "derived" / "workflow_numeric").glob("*/recipe.json"))
    assert json.loads(recipe.read_text())["workflow_id"] == "workflow_one"
    with pytest.raises(Exception, match="occupied"):
        _derive(tmp_path, "workflow_three", "make", [5, 6])


def test_tabulate_counts_within_each_group() -> None:
    frame = pd.DataFrame({"sick": ["y", "y", "n", "n", "n"], "smoker": ["a", "b", "a", "a", "b"]})
    result = execute_exploration(frame, ExplorationSpec(
        operation="tabulate", selected_columns=("sick",), options={"group_by": "smoker"}))
    counts = {group["value"]: {row["value"]: row["count"] for row in group["rows"]} for group in result["groups"]}
    assert counts == {"a": {"y": 1, "n": 2}, "b": {"y": 1, "n": 1}}


def test_matching_policy_refusal_shows_the_whole_policy() -> None:
    with pytest.raises(Exception, match=r'exactly these fields.*"max_probability"'):
        estimate_att(_frame(), **_policy(propensity_policy={"model": "logit", "method": "newton"}))


def test_matching_unmatched_refusal_gives_the_counts() -> None:
    with pytest.raises(Exception, match=r"eligible controls but ratio is 1 \(\d+ treated, \d+ controls, replacement=False, caliper=1e-09"):
        estimate_att(_frame(), **_policy(caliper=1e-9))


def test_a_model_in_another_run_is_named(tmp_path: Path) -> None:
    root = tmp_path
    (root / "here").mkdir()
    fitted = root / "there" / kernel_relative_path("ols_1")
    fitted.parent.mkdir(parents=True)
    fitted.write_text("{}")
    with pytest.raises(Exception, match=r"run here has no model ols_1.*there.*model_run_id"):
        _load_kernel(root / "here", "ols_1")
    with pytest.raises(Exception, match="no run in this project"):
        _load_kernel(root / "here", "ols_2")


def _artifact(kind: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(artifact_type=kind, payload=payload)


def test_completed_postestimation_and_named_tests_count_as_results() -> None:
    assert computed_result(None, {}, _artifact(
        "post_estimation", {"schema_version": "workbench.workflow.post-estimation/v1",
                            "result": {"schema_version": "workbench.postestimation.result/v1", "margins": [1]}}))
    assert not computed_result(None, {}, _artifact(
        "post_estimation", {"schema_version": "workbench.workflow.post-estimation/v1", "result": {"contract": "iv-ar.evidence.v1"}}))
    assert computed_result(None, {}, _artifact(
        "statistical_test", {"payload_schema": "workbench.statistical_tests.named-family", "result": {"results": [{"p": 0.1}]}}))
    assert not computed_result(None, {}, _artifact(
        "statistical_test", {"payload_schema": "workbench.statistical_tests.named-family", "result": {"results": []}}))
    assert not computed_result(None, {}, _artifact(
        "post_estimation", {"schema_version": "other", "result": {"margins": [1]}}))


def test_missing_binding_lists_source_columns() -> None:
    with pytest.raises(P7PackAdapterError, match=r"cigsale_3\. Source columns: year, 3, 4"):
        _require_columns(pd.DataFrame({"year": [1], "3": [1.0], "4": [2.0]}), {"outcomes": ["cigsale_3"]})


def test_paired_rows_are_under_evidence() -> None:
    frame = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [2.0, 2.5, 3.5, 4.5, 7.0]})
    results = run_statistical_tests(frame, analysis_columns=["a", "b"], paired_columns=[("a", "b")])
    assert not results["t_tests"]["results"] and results["evidence"]["results"]


def _diagnostic(operation_id: str, frame: pd.DataFrame, bindings: dict, options: dict | None = None) -> dict:
    from workbench.agent.p7_pack_registry import p7_pack_registry

    operation = p7_pack_registry.get(operation_id)
    request = {"operation_id": operation_id, "input_mode": "typed", "column_bindings": bindings, "options": options or {}}
    operation.validate(request)
    result = operation.execute(frame, request)
    operation.validate_result(result)
    return result


def _design_frame() -> pd.DataFrame:
    rng = np.random.default_rng(20261101)
    x1, x2 = rng.normal(size=60), rng.normal(size=60)
    return pd.DataFrame({"x1": x1, "x2": x2, "y": 1.0 + x1 - x2 + rng.normal(size=60)})


def _with_gaps(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([frame, pd.DataFrame({"x1": [np.nan, 0.5], "x2": [0.5, 0.5], "y": [0.5, np.nan]})], ignore_index=True)


@pytest.mark.parametrize(
    "operation_id,bindings",
    [("diagnostics.vif", {"design": ["x1", "x2"]}),
     ("diagnostics.breusch_pagan", {"response": "y", "design": ["x1", "x2"]}),
     ("diagnostics.white", {"response": "y", "design": ["x1", "x2"]})],
)
def test_diagnostics_use_the_rows_ols_would_keep_and_say_so(operation_id: str, bindings: dict) -> None:
    complete = _diagnostic(operation_id, _design_frame(), bindings)
    gaps = _with_gaps(_design_frame())
    if "response" not in bindings:  # the gap in y is not in this design, so only the row missing x1 goes
        gaps = gaps.iloc[:-1]
    result = _diagnostic(operation_id, gaps, bindings)
    report = result["result"].pop("missing_rows")
    assert result == complete
    assert report["rows_used"] == 60 and report["rows_total"] == len(gaps)
    assert report["missing_by_column"]["x1"] == 1


def test_diagnostics_without_gaps_report_nothing_extra() -> None:
    assert "missing_rows" not in _diagnostic("diagnostics.vif", _design_frame(), {"design": ["x1", "x2"]})["result"]


def test_infinite_values_are_refused_and_named() -> None:
    frame = _design_frame()
    frame.loc[3, "x2"] = np.inf
    with pytest.raises(P7PackAdapterError, match=r"non-finite values: x2 \(1\)"):
        _diagnostic("diagnostics.vif", frame, {"design": ["x1", "x2"]})


@pytest.mark.parametrize(
    "operation_id,options",
    [("diagnostics.influence", {}), ("diagnostics.breusch_godfrey", {"lag": 1, "time_order": "declared_order"})],
)
def test_row_order_diagnostics_refuse_gaps_and_name_them(operation_id: str, options: dict) -> None:
    with pytest.raises(P7PackAdapterError, match=rf"{operation_id}.*row.*x1: 1"):
        _diagnostic(operation_id, _with_gaps(_design_frame()), {"response": "y", "design": ["x1", "x2"]}, options)


def test_too_few_complete_rows_gives_the_counts() -> None:
    frame = _design_frame().head(4)
    frame.loc[[0, 1, 2], "x1"] = np.nan
    with pytest.raises(P7PackAdapterError, match=r"1 of 4 rows are complete.*x1: 3"):
        _diagnostic("diagnostics.vif", frame, {"design": ["x1", "x2"]})


def test_the_agent_can_read_which_rows_went() -> None:
    from workbench.agent.context_tools_support.summaries import _public_operation_artifact_result

    result = _diagnostic("diagnostics.vif", _with_gaps(_design_frame()).iloc[:-1], {"design": ["x1", "x2"]})
    public, _withheld = _public_operation_artifact_result("p7_analysis", {"result": result})
    assert public["result"]["missing_rows"] == {"rows_total": 61, "rows_used": 60, "missing_by_column": {"x1": 1}}
    assert public["n_observations"] == 60


def _subset_project(tmp_path: Path, frame: pd.DataFrame, filters: list[dict]):
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    return project, DataTransformSpecV1(
        source_run_id=run_id, source_node_id="stage:source", source_artifact_id=artifact_id, operation="subset",
        parameters={"columns": list(frame.columns), "filters": filters},
    )


@pytest.mark.parametrize("op,value", [("ne", "Palm Beach"), ("eq", "Palm Beach"), ("not_in", ["Dade", "Palm Beach"])])
def test_a_filter_on_a_value_the_column_lacks_is_refused_with_the_nearest(tmp_path: Path, op: str, value: object) -> None:
    project, spec = _subset_project(
        tmp_path, pd.DataFrame({"county": ["PalmBeach", "Dade", "Lee"], "votes": [1, 2, 3]}),
        [{"column": "county", "op": op, "value": value}])
    with pytest.raises(Exception, match=r"no value .*Palm Beach.*Closest values: PalmBeach"):
        preview_data_transform(project, spec)


def test_a_filter_on_a_present_value_still_filters(tmp_path: Path) -> None:
    project, spec = _subset_project(
        tmp_path, pd.DataFrame({"county": ["PalmBeach", "Dade", "Lee"], "votes": [1, 2, 3]}),
        [{"column": "county", "op": "ne", "value": "PalmBeach"}])
    result = apply_data_transform(project, spec, preview_data_transform(project, spec))
    assert result.child_node_id


def _panel() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    rows = []
    for unit in (1, 2, 3, 4):
        level = rng.normal(size=8).cumsum() + unit
        rows += [{"state": unit, "year": 2000 + t, "sales": float(level[t])} for t in range(8)]
    return pd.DataFrame(rows)


def _wide(panel: pd.DataFrame) -> pd.DataFrame:
    wide = panel.pivot(index="year", columns="state", values="sales").reset_index()
    wide.columns = [str(c) for c in wide.columns]
    return wide


def test_synthetic_control_reads_long_data_and_matches_the_wide_result() -> None:
    years = list(range(2000, 2008))
    periods = {"pre_periods": years[:5], "post_periods": years[5:], "treated_unit": "1"}
    wide = _diagnostic("synthetic_control.fit", _wide(_panel()), {"outcomes": ["1", "2", "3", "4"]},
                       {**periods, "periods": years, "donor_pool": ["2", "3", "4"]})
    long = _diagnostic("synthetic_control.fit", _panel(), {"outcomes": ["sales"]},
                       {**periods, "unit_column": "state", "time_column": "year"})
    assert long["result"]["post_treatment"] == wide["result"]["post_treatment"]


def test_synthetic_control_long_data_must_be_balanced_and_name_a_real_unit() -> None:
    panel = _panel()
    long = {"pre_periods": [2000, 2001], "post_periods": [2006], "unit_column": "state", "time_column": "year"}
    with pytest.raises(P7PackAdapterError, match="not balanced.*: 2"):
        _diagnostic("synthetic_control.fit", panel.drop(index=9), {"outcomes": ["sales"]}, {**long, "treated_unit": "1"})
    with pytest.raises(P7PackAdapterError, match="treated_unit 9 is not a value of state"):
        _diagnostic("synthetic_control.fit", panel, {"outcomes": ["sales"]}, {**long, "treated_unit": "9"})


def test_synthetic_control_periods_written_as_a_range_are_refused_with_the_gap() -> None:
    long = {"pre_periods": [2000, 2004], "post_periods": [2005, 2007], "unit_column": "state", "time_column": "year",
            "treated_unit": "1"}
    with pytest.raises(P7PackAdapterError, match="PERIOD_GAPS.*2001, 2002, 2003, 2006"):
        _diagnostic("synthetic_control.fit", _panel(), {"outcomes": ["sales"]}, long)


def test_synthetic_control_period_ranges_are_refused_by_the_frame_preflight() -> None:
    """Proposals run this preflight before approval; execution runs it again."""
    from workbench.agent.p7_pack_registry import p7_pack_registry

    operation = p7_pack_registry.get("synthetic_control.fit")
    options = {"unit_column": "state", "time_column": "year", "treated_unit": "1"}
    request = {"operation_id": "synthetic_control.fit", "input_mode": "typed", "column_bindings": {"outcomes": ["sales"]},
               "options": {**options, "pre_periods": [2000, 2004], "post_periods": [2005, 2007]}}
    with pytest.raises(P7PackAdapterError, match="PERIOD_GAPS.*2001, 2002, 2003, 2006"):
        operation.preflight(_panel(), request)
    years = list(range(2000, 2008))
    operation.preflight(_panel(), {**request, "options": {**options, "pre_periods": years[:5], "post_periods": years[5:]}})


def test_a_final_answer_heading_is_not_an_answer(monkeypatch) -> None:
    # The grader lives in scripts/; without this the test passed only after another test added that path.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from agent_eval.external import qrdata_correct

    reply = "FINAL ANSWER: 6.52\n\n### Final Answer\nThe estimate is 6.52"
    assert qrdata_correct("6.52", reply, "numerical") is True
    assert qrdata_correct("6.52", "### Final Answer\nThe estimate is 6.52", "numerical") is None
    assert qrdata_correct("B", "**FINAL ANSWER:** B", "multiple_choice") is True


def test_ols_refuses_a_predictor_with_thousands_of_levels() -> None:
    from workbench.econometrics.runner import run_ols

    frame = pd.DataFrame({"y": np.arange(1500.0), "title": [f"t{i}" for i in range(1500)], "x": np.arange(1500.0) % 7})
    with pytest.raises(ValueError, match=r"OLS_TOO_MANY_CATEGORY_LEVELS.*title \(1500\)"):
        run_ols(frame, "y", ["title", "x"], robust=False, model_id="ols_1", categorical_x={"title"})


def test_a_grouped_frequency_table_shows_each_groups_values() -> None:
    """QRData 374 (55ce11c1 round): the California group read "state: distinct 1" without the state code,
    and the model guessed unit 16 instead of 3. Frequencies are aggregates; raw rows stay withheld."""
    from workbench.agent.context_tools_support.summaries_public import _public_operation_artifact_result
    from workbench.statistical_exploration import ExplorationSpec, execute_exploration

    frame = pd.DataFrame([{"state": state, "year": year, "california": state == 3, "cigsale": float(state + year)}
                          for state in range(1, 6) for year in range(1970, 1975)])
    result = execute_exploration(frame, ExplorationSpec(operation="tabulate", selected_columns=("state",),
                                                        options={"group_by": "california"}))
    public, withheld = _public_operation_artifact_result("statistical_exploration", {"result": result})
    california = next(group for group in public["groups"] if group["value"] is True)
    assert [row["value"] for row in california["frequencies"]] == [3]
    assert california["frequencies"][0]["count"] == 5
    assert "raw_rows" in withheld and "cigsale" not in json.dumps(public)


def test_a_paired_result_names_its_direction_and_both_means_for_the_agent() -> None:
    """QRData 109 (3724e8b2 round): a negative dx90_1948-minus-dx90_2018 difference was read as fewer days in 2018."""
    from workbench.agent.context_tools_support.summaries_public import _public_operation_artifact_result
    from workbench.agent.workflow_capability_adapters import get_workflow_capability_adapter

    adapter = get_workflow_capability_adapter("statistical_test")
    frame = pd.DataFrame({"dx90_1948": [1.0, 2, 3, 4, 5, 6], "dx90_2018": [2.0, 4, 3, 7, 6, 9]})
    request = adapter.validate_request("test.evidence", {
        "operation_id": "test.evidence", "input_mode": "frame",
        "column_bindings": {"columns": ["dx90_1948", "dx90_2018"]},
        "options": {"paired_columns": [["dx90_1948", "dx90_2018"]]}})
    payload = adapter.execute(frame, request).payload
    public, _ = _public_operation_artifact_result("workflow_capability_result", {"result": payload})
    paired = next(row for row in public["results"] if row["test_type"] == "paired_t_test")
    assert paired["difference"] == "dx90_1948 minus dx90_2018"
    assert paired["means"] == {"dx90_1948": 3.5, "dx90_2018": 5.166666666666667}
    assert paired["effect_size"]["value"] < 0
    # QRData 106 (3f281a47 round): the interval of the difference reaches the Agent too.
    interval = paired["confidence_interval"]
    assert interval["level"] == 0.95 and interval["lower"] < interval["estimate"] < interval["upper"]


def test_a_one_row_summary_exports_without_a_standard_deviation(tmp_path) -> None:
    """QRData 403 (3724e8b2 round): the PDF formatted std=None and failed the whole exploration step."""
    from workbench import statistical_exploration_persist as persist
    from workbench.statistical_exploration import ExplorationSpec, execute_exploration

    spec = ExplorationSpec(operation="summarize", selected_columns=("a", "b"))
    result = execute_exploration(pd.DataFrame({"a": [1], "b": [0]}), spec)
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"artifacts": []}))
    exports = persist._persist_exploration_exports(tmp_path, artifact_id="x", fingerprint="f" * 40, spec=spec, result=result)
    assert [item["format"] for item in exports] == ["html", "pdf", "xlsx"]
