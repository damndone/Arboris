"""The delivery gate binds only fits whose family serves the outcome, and owns those families by declaration."""
from __future__ import annotations

from tests.test_agent_completion import artifact
from workbench.agent import completion
from workbench.agent.completion_outcome import NOT_SERVED, OUTCOME_FAMILY, not_served_step, outcome_family_types
from workbench.engine.registry import MODEL_REGISTRY

UNSERVED = {"check_id": "outcome.type_served", "status": "caution", "blinding": "outcome_distribution",
            "summary": "The outcome is binary, and ols is declared for continuous outcomes.",
            "evidence": {"outcome_type": "binary", "family": "ols", "family_serves": ["continuous"],
                         "families_serving_outcome_type": ["glm", "logit", "probit"],
                         "default_family_for_outcome_type": "logit"}}
HOLDS = {"check_id": "fit.separation", "status": "holds", "blinding": "post_fit", "summary": "No separation."}


def _fit(project, name, model_type, estimate, fingerprint, checks):
    ref, _ = artifact(project, "r", name, "model_result", {
        "model_type": model_type, "model_id": name, "nobs": 1200,
        "coefficients": {"income_k": {"estimate": estimate, "std_error": .01}},
        "point_estimation_fingerprint": fingerprint * 64, "analysis_sample_fingerprint": "c" * 64}, ["data"])
    artifact(project, "r", f"checks_{name}", "model_checks",
             {"schema_version": 1, "model_id": name, "model_type": model_type, "checks": checks}, [name])
    return ref


def _binary_project(project):
    source, digest = artifact(project, "r", "data", "processed_data", {"rows": "fixture"})
    seed = _fit(project, "ols_1", "ols", .013, "a", [UNSERVED])
    logit = _fit(project, "logit_1", "logit", .062, "b", [HOLDS])
    probit = _fit(project, "probit_1", "probit", .037, "d", [HOLDS])
    report, _ = artifact(project, "r", "report", "report", {"sections": [{"text": "Logit with probit comparison."}]},
                         ["logit_1", "checks_logit_1", "probit_1"])
    return {"source": {**source, "sha256": digest}, "seed": seed, "logit": logit, "probit": probit, "report": report}


def test_the_outcome_family_playbook_is_read_from_the_registry_declarations():
    owned = {name for names in completion.PLAYBOOKS.values() for name in names}
    families = outcome_family_types(owned)
    assert {"logit", "probit", "glm"} <= set(families)
    assert not owned & set(families)
    for name in families:
        assert set(MODEL_REGISTRY[name].serves_y_types) - {"continuous"}
    assert completion.playbook_types(OUTCOME_FAMILY) == families
    assert OUTCOME_FAMILY in completion.CONTRACT_SCHEMA["properties"]["playbooks"]["items"]["enum"]


def test_an_imported_ols_on_a_binary_outcome_is_never_the_bound_primary(tmp_path):
    fits = _binary_project(tmp_path)
    contract = {"playbooks": ["ols"], "source": fits["source"]}
    evidence, notes = completion.derive_evidence(tmp_path, contract, {})
    assert fits["seed"] not in evidence.get("models", [])
    assert "ols:primary" not in notes["bound_by_workbench"]
    result = completion.evaluate(tmp_path, contract, {"models": [fits["seed"]]})
    assert result["status"] == "partial" and NOT_SERVED in result["missing"]
    assert result["outcome_not_served"]["families_serving_outcome_type"] == ["glm", "logit", "probit"]


def test_a_logit_primary_with_its_checks_and_a_probit_comparison_meets_the_outcome_family_playbook(tmp_path):
    fits = _binary_project(tmp_path)
    contract = {"playbooks": [OUTCOME_FAMILY], "source": fits["source"]}
    evidence, notes = completion.derive_evidence(tmp_path, contract, {"models": [fits["logit"]], "report": fits["report"]})
    assert evidence["models"] == [fits["logit"]]
    assert {"run_id": "r", "artifact_id": "checks_logit_1"} in evidence["diagnostics"]
    assert fits["probit"] in evidence["sensitivity"] and fits["seed"] not in evidence["sensitivity"]
    result = completion.evaluate(tmp_path, contract, evidence)
    assert result["missing"] == [] and result["status"] == "requirements_met"


def test_a_failing_check_keeps_the_outcome_family_diagnostics_missing(tmp_path):
    fits = _binary_project(tmp_path)
    artifact(tmp_path, "r", "checks_logit_1", "model_checks", {"model_id": "logit_1", "checks": [
        {**HOLDS, "status": "fails", "summary": "Complete separation."}]}, ["logit_1"])
    contract = {"playbooks": [OUTCOME_FAMILY], "source": fits["source"]}
    evidence, _ = completion.derive_evidence(tmp_path, contract, {"models": [fits["logit"]], "report": fits["report"]})
    assert f"{OUTCOME_FAMILY}:diagnostics:computed_and_model_bound" in completion.evaluate(tmp_path, contract, evidence)["missing"]


def test_a_focused_question_bound_to_the_unserved_fit_is_partial(tmp_path):
    fits = _binary_project(tmp_path)
    contract = {"scope": "question", "playbooks": [], "source": fits["source"]}
    result = completion.evaluate(tmp_path, contract, {"results": [fits["seed"]]})
    assert NOT_SERVED in result["missing"] and result["outcome_not_served"]["family"] == "ols"


def test_the_next_step_names_the_serving_families_and_the_rerun_path():
    step = not_served_step(UNSERVED["evidence"])
    assert "glm, logit, probit" in step and "model.rerun" in step and OUTCOME_FAMILY in step


def test_every_playbook_has_a_label_for_each_missing_requirement_in_both_languages():
    # aeb81ade retest: the first partial notice for an outcome_family plan raised KeyError and ended the turn.
    for family in completion.CONTRACT_SCHEMA["properties"]["playbooks"]["items"]["enum"]:
        assert family in completion.PLAYBOOK_LABELS
        for requirement in ("model:x", "diagnostics:computed_and_model_bound", "sensitivity:distinct_point_estimation"):
            for language in ("en", "zh"):
                assert completion._missing_label(f"{family}:{requirement}", language)


def test_a_partial_notice_for_an_outcome_family_plan_is_written(tmp_path):
    fits = _binary_project(tmp_path)
    contract = {"playbooks": [OUTCOME_FAMILY], "source": fits["source"]}
    result = completion.evaluate(tmp_path, contract, {"models": [fits["logit"]]})
    assert result["status"] == "partial"
    for language in ("en", "zh"):
        assert completion.partial_notice(result, language)


def test_the_report_accepts_the_fit_checks_the_gate_binds_as_diagnostics(tmp_path):
    # aeb81ade retest: the gate's ready report.compose named checks_logit_1 and the report refused it.
    from workbench.agent.report_sources import collect_report_sources
    fits = _binary_project(tmp_path)
    evidence, _ = completion.derive_evidence(
        tmp_path, {"playbooks": [OUTCOME_FAMILY], "source": fits["source"]}, {"models": [fits["logit"]]})
    refs = ([{**ref, "role": "primary"} for ref in evidence["models"]]
            + [{**ref, "role": "diagnostic"} for ref in evidence["diagnostics"]])
    assert {"run_id": "r", "artifact_id": "checks_logit_1", "role": "diagnostic"} in refs
    collected = collect_report_sources(tmp_path, fits["source"], refs)
    assert any(row["field"].endswith("status") and row["value"] == "holds" for row in collected["diagnostic_rows"])
