import json

import pytest

from workbench.lineage.card_preview import build_card_previews
from workbench.contracts.model.inference_kernel import build_inference_kernel


def _write(run_root, relative, payload):
    path = run_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _graph(model_id="iv_2sls_1"):
    key = f"model:{model_id}"
    return {
        "nodes": {
            "stage:raw": {"kind": "dataset_stage", "summary": "Raw: 64 rows × 65 cols"},
            "stage:cleaned": {"kind": "dataset_stage", "summary": "Cleaned: 64 rows"},
            key: {"kind": "model", "payload_ref": f"model_results/{model_id}.json"},
            "report:html": {"kind": "report"},
            "var:d:cleaned": {"kind": "variable"},
        },
        "edges": {
            "report": {"source_id": key, "target_id": "report:html", "op": "render_report"},
            "endog": {
                "source_id": "var:d:cleaned", "target_id": key, "op": "enters_as_focal",
                "params": {"source": "_iv_endog", "dropped": False},
            },
        },
    }


def _model(run_root, **overrides):
    _write(run_root, "model_results/iv_2sls_1.json", {
        "model_id": "iv_2sls_1", "model_type": "iv_2sls", "nobs": 64, "y_column": "y",
        "engine": "linearmodels",
        "engine_selection": {"requested": "fast", "used": "reference", "reason": "domain unavailable"},
        "coefficients": {
            "Intercept": {"estimate": 9, "p_value": 0.001},
            "w": {"estimate": 42, "p_value": 0.001},
            "d": {"estimate": 2.5, "ci_lower": -1, "ci_upper": 6, "p_value": 0.1},
        },
        **overrides,
    })


def test_raw_uses_bound_recorded_input_and_identifies_upload_staging(tmp_path):
    graph = _graph()
    inputs = {"upload": {"filename": "sample.csv"}}
    path = "/research/source/sample.csv"
    manifest = {"lineage": [
        {"source": "/unrelated/sample.csv", "artifact_id": "raw_other.csv"},
        {"source": path, "artifact_id": "raw_sample.csv"},
    ]}
    raw = build_card_previews(tmp_path, graph, manifest, inputs, ["stage:raw"])
    assert set(raw) == {"stage:raw"}
    assert raw["stage:raw"]["title"] == "sample.csv"
    assert "Folder: /research/source" in raw["stage:raw"]["lines"]
    assert path in raw["stage:raw"]["detail"]
    assert "/unrelated" not in raw["stage:raw"]["detail"]
    snapshot = tmp_path / "raw_snapshot/sample.csv"
    snapshot.parent.mkdir()
    snapshot.write_text("year,amount\n2020,5\n", encoding="utf-8")
    _write(tmp_path, "artifacts_index.json", {"artifacts": [
        {"artifact_id": "raw_sample.csv", "path": "raw_snapshot/sample.csv", "artifact_type": "raw_data"},
    ]})
    manifest["lineage"][1]["source"] = str(tmp_path / "_uploads/sample.csv")
    staged = build_card_previews(tmp_path, graph, manifest, inputs, ["stage:raw"])["stage:raw"]
    assert "Snapshot: raw_snapshot/sample.csv" in staged["lines"]
    assert str(snapshot) in staged["detail"]
    assert "staging" in staged["detail"]
    assert "Original local path not recorded" in staged["detail"]
    snapshot.unlink()
    snapshot.symlink_to(tmp_path / "staged-input.csv")
    (tmp_path / "staged-input.csv").write_text("foreign\n", encoding="utf-8")
    unbound = build_card_previews(tmp_path, graph, manifest, inputs, ["stage:raw"])["stage:raw"]
    assert "Original folder not recorded" in unbound["lines"]
    assert not any("Snapshot:" in line for line in unbound["lines"])


def test_raw_shows_only_column_cues_bound_to_the_input(tmp_path):
    graph = _graph()
    inputs = {"upload": {"filename": "sample.csv"}, "form": {"labels": {"variable_labels": {
        "tax_amt": "Property tax", "outside": "Other input label",
    }}}}
    _write(tmp_path, "staged/metadata_registry.json", {"columns": [
        {"source_file": "sample.csv", "name": "year"},
        {"source_file": "other.csv", "name": "outside"},
        {"source_file": "sample.csv", "name": "tax_amt"},
    ]})
    card = build_card_previews(tmp_path, graph, {}, inputs, ["stage:raw"])["stage:raw"]
    assert "Columns: Property tax, year" in card["lines"]
    assert "tax_amt (Property tax)" in card["detail"]
    assert "outside" not in str(card)


def test_raw_can_use_one_recorded_input_when_legacy_run_inputs_are_missing(tmp_path):
    source = "/research/archived-workspace/field-study/sample.csv"
    manifest = {"lineage": [{"source": source, "artifact_id": "raw_sample.csv"}]}
    card = build_card_previews(tmp_path, _graph(), manifest, {}, ["stage:raw"])["stage:raw"]
    assert card["title"] == "sample.csv"
    assert "Folder: …/field-study" in card["lines"]
    assert source in card["detail"]


def test_cleaning_distinguishes_real_changes_and_kept_duplicates(tmp_path):
    graph = _graph()
    def clean():
        return build_card_previews(tmp_path, graph, {}, {}, ["stage:cleaned"])["stage:cleaned"]
    _write(tmp_path, "processed/cleaning_actions.json", {"actions": [
        {"action": "normalize_column_names", "details": {"y": "y"}},
    ]})
    assert "No recorded changes" in clean()["lines"]
    _write(tmp_path, "processed/cleaning_actions.json", {"actions": [
        {"action": "normalize_column_names", "details": {"y": "y", " X ": "x"}},
        {"action": "deduplicate_column_names", "details": [{"from": " X ", "to": "x"}]},
        {"action": "coerce_to_numeric", "column": "price"},
        {"action": "parse_date_candidate", "column": "day"},
        {"action": "duplicate_rows_found", "rows": 2, "kept": True},
    ]})
    preview = clean()
    assert len(preview["lines"]) <= 3
    assert "1 renamed" in preview["detail"]
    assert "1 converted to numeric" in preview["detail"]
    assert "1 parsed as dates" in preview["detail"]
    assert "2 duplicate rows kept" in preview["detail"]
    assert all(name in preview["detail"] for name in ("→ x", "price", "day"))
    assert "No recorded changes" not in preview["lines"]


def test_cleaning_exposes_legacy_duplicate_drops_and_recorded_conversion_details(tmp_path):
    _write(tmp_path, "processed/cleaning_actions.json", {"actions": [
        {"action": "normalize_column_names", "details": {"tax": "tax_2"}},
        {"action": "deduplicate_column_names", "details": [{"from": "tax", "to": "tax_2"}]},
        {"action": "coerce_to_numeric", "column": "price", "original_dtype": "object", "conversion_rate": 0.8734},
        {"action": "drop_duplicate_rows", "rows_dropped": 2},
    ]})
    _write(tmp_path, "imputation_summary.json", {"status": "completed", "method": "mice", "rows_imputed": 27})
    card = build_card_previews(tmp_path, _graph(), {}, {}, ["stage:cleaned"])["stage:cleaned"]
    assert "2 duplicate rows removed" in card["lines"]
    assert "Disambiguated: tax → tax_2" in card["detail"]
    assert "price (from object, 87.34% convertible)" in card["detail"]
    assert "27" not in card["detail"]


def test_model_uses_actual_family_and_engine_with_fallback(tmp_path):
    _model(tmp_path)
    _write(tmp_path, "model_results/inference_kernels/iv_2sls_1.json", {
        "model_id": "iv_2sls_1", "covariance_estimator": "unadjusted",
    })
    key = "model:iv_2sls_1"
    preview = build_card_previews(
        tmp_path, _graph(), {"requested_model_type": "ols"},
        {"form": {"covariance": "robust", "y": "wrong"}}, [key, "var:d:cleaned"],
    )
    assert set(preview) == {key}
    card = preview[key]
    assert card["title"] == "IV (2SLS)"
    assert len(card["lines"]) == 3
    assert "n=64" in card["lines"][0] and "y" in card["lines"][0]
    assert "unadjusted" in card["lines"][1]
    assert "linearmodels" in card["lines"][2] and "fallback" in card["lines"][2]
    assert "domain unavailable" in card["detail"]


def test_report_uses_first_bound_iv_endogenous_term_even_if_not_significant(tmp_path):
    _model(tmp_path)
    card = build_card_previews(tmp_path, _graph(), {}, {}, ["report:html"])["report:html"]
    assert card["title"] == "IV (2SLS) results"
    assert len(card["lines"]) <= 3
    assert card["lines"][0].startswith("d ")
    assert "2.5" in card["lines"][0] and "Not significant" in card["lines"][0]
    assert card["lines"][1] == "95% CI [-1, 6]"
    assert "endogenous" in card["detail"] and "does not establish" in card["detail"]
    assert "42" not in str(card["lines"])
    assert "5%" in card["detail"] and "this coefficient only" in card["detail"]


def test_outcome_fallback_requires_matching_effective_model_id(tmp_path):
    _model(tmp_path, y_column=None)
    key = "model:iv_2sls_1"
    routing = {"effective_model_id": "iv_2sls_1", "current_y": "income"}
    matching = build_card_previews(tmp_path, _graph(), {"model_routing": routing}, {}, [key])[key]
    assert matching["lines"][0] == "n=64 · y=income"
    routing["effective_model_id"] = "iv_2sls_2"
    different = build_card_previews(tmp_path, _graph(), {"model_routing": routing}, {}, [key])[key]
    assert different["lines"][0] == "n=64 · outcome unavailable"


@pytest.mark.parametrize("binding", ["absent", "multiple", "outside", "wrong-model", "oversize"])
def test_report_requires_unique_local_bounded_model_evidence(tmp_path, binding):
    root = tmp_path / "owner"
    graph = _graph()
    _model(root)
    if binding == "absent":
        graph["edges"].pop("report")
    elif binding == "multiple":
        graph["edges"]["extra"] = dict(graph["edges"]["report"])
    elif binding == "outside":
        _model(tmp_path / "other")
        path = root / "model_results/iv_2sls_1.json"
        path.unlink()
        path.symlink_to(tmp_path / "other/model_results/iv_2sls_1.json")
    elif binding == "wrong-model":
        _model(root, model_id="other_1")
    else:
        with (root / "model_results/iv_2sls_1.json").open("ab") as handle:
            handle.truncate(32 * 1024 * 1024)
    card = build_card_previews(root, graph, {}, {}, ["report:html"])["report:html"]
    assert card["lines"] == ["Effect evidence unavailable"]
    assert "2.5" not in card["detail"]


def test_report_marks_rounded_boundary_and_rejects_nonfinite_ci(tmp_path):
    _model(tmp_path, coefficients={"d": {
        "estimate": 2.5, "ci_lower": float("nan"), "ci_upper": 6, "p_value": 0.05,
    }})
    card = build_card_previews(tmp_path, _graph(), {}, {}, ["report:html"])["report:html"]
    assert "p≈.05" in card["lines"][0]
    assert card["lines"][1] == "CI unavailable"


@pytest.mark.parametrize("distribution,df,critical95,critical99", [
    ("z", None, 1.959963984540054, 2.5758293035489004),
    ("t", 4, 2.7764451051977987, 4.604094871349993),
])
def test_report_offers_all_coefficients_and_uses_bound_primary_and_reference_distribution(
    tmp_path, distribution, df, critical95, critical99,
):
    model_id = "iv_2sls_1" if distribution == "z" else "ols_1"
    family = "iv_2sls" if distribution == "z" else "ols_clustered"
    coefficients = {
        "Intercept": {"estimate": 9, "std_error": 1},
        "d": {"estimate": 2.5, "std_error": 1},
        "d2": {"result_id": "recorded-primary", "estimate": 0.8, "std_error": 0.2,
               "ci_lower": 0.8 - critical95 * 0.2, "ci_upper": 0.8 + critical95 * 0.2, "p_value": 0.03},
    }
    _write(tmp_path, f"model_results/{model_id}.json", {
        "model_id": model_id, "model_type": family, "schema_version": 1, "nobs": 64,
        "engine": "linearmodels" if distribution == "z" else "statsmodels",
        "contract_version": "ols_result_contract_v1" if distribution == "t" else None,
        "covariance_evidence": {"confidence_level": 0.95, "confidence_interval_method": "t",
                                 "effective_df": df} if distribution == "t" else None,
        "primary_estimand": {"result_id": "recorded-primary"}, "coefficients": coefficients,
    })
    kernel = build_inference_kernel(
        model_id=model_id, model_type=family, param_names=list(coefficients), params=[9, 2.5, 0.8],
        vcov=[[1, 0, 0], [0, 1, 0], [0, 0, 0.04]], reference_distribution=distribution,
        df_resid=df, df_method="clusters_minus_one" if df else "asymptotic",
        n_clusters=5 if df else None, loglik=None, nobs=64, covariance_estimator="cluster" if df else "robust",
    )
    _write(tmp_path, f"model_results/inference_kernels/{model_id}.json", kernel)

    card = build_card_previews(tmp_path, _graph(model_id), {}, {}, ["report:html"])["report:html"]
    report = card["report"]
    assert report["model_id"] == model_id
    assert report["default_term"] == "d2"
    assert card["lines"][0].startswith("d2 0.8")
    assert [coefficient["term"] for coefficient in report["coefficients"]] == list(coefficients)
    assert report["distribution"] == distribution
    assert report.get("df") == df
    chosen = report["coefficients"][2]
    assert chosen["saved_interval"] == {"level": 0.95, "lower": coefficients["d2"]["ci_lower"],
                                         "upper": coefficients["d2"]["ci_upper"]}
    alternative = next(interval for interval in chosen["intervals"] if interval["level"] == 0.99)
    assert alternative["lower"] == pytest.approx(0.8 - critical99 * 0.2, abs=1e-12)
    assert alternative["upper"] == pytest.approx(0.8 + critical99 * 0.2, abs=1e-12)


@pytest.mark.parametrize("problem", ["weighted", "wrong-model", "invalid-df", "wrong-estimate"])
def test_report_retains_saved_interval_when_alternatives_cannot_be_verified(tmp_path, problem):
    _model(tmp_path, schema_version=1, primary_estimand={"result_id": "missing"}, coefficients={
        "d": {"estimate": 2.5, "std_error": 1, "ci_lower": -1, "ci_upper": 6},
    })
    kernel = build_inference_kernel(
        model_id="iv_2sls_1", model_type="iv_2sls", param_names=["d"], params=[2.5], vcov=[[1]],
        reference_distribution="z", df_resid=None, loglik=None, nobs=64, covariance_estimator="robust",
    )
    if problem == "weighted":
        kernel["weights"] = "sampling"
    elif problem == "wrong-model":
        kernel["model_id"] = "other_model"
    elif problem == "invalid-df":
        kernel.update(reference_distribution="t", df_method="residual", df_resid=0)
    else:
        kernel["params"] = [3.5]
    _write(tmp_path, "model_results/inference_kernels/iv_2sls_1.json", kernel)
    card = build_card_previews(tmp_path, _graph(), {}, {}, ["report:html"])["report:html"]
    assert card["report"]["default_term"] is None
    assert "primary coefficient" in card["detail"]
    chosen = card["report"]["coefficients"][0]
    assert chosen["saved_interval"] == {"level": 0.95, "lower": -1.0, "upper": 6.0}
    assert chosen["intervals"] == []
    assert chosen["interval_unavailable"]


def test_report_names_coefficient_preview_limit_without_offering_a_partial_list(tmp_path):
    _model(tmp_path, coefficients={f"x{i}": {"estimate": i} for i in range(301)})
    card = build_card_previews(tmp_path, _graph(), {}, {}, ["report:html"])["report:html"]
    assert "report" not in card
    assert "301 saved coefficients" in card["detail"]
    assert "exceeds the preview limit" in card["detail"]
