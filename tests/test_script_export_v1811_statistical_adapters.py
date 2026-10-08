"""Approved FPC and fixed-alpha GLM-NB scripts, with native evidence retained."""
from dataclasses import replace
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from workbench.script_export.plan import LANGUAGES, ScriptPlan, ScriptStep, ScriptSource, ScriptExportRefusal
from workbench.script_export.render import export_script
from workbench.postestimation.registry import VALIDATED
from evidence_retention import run_dir
from test_script_export_data_oracles import execute

REPO = Path(__file__).resolve().parents[1]
OWNED = REPO / "tests/fixtures/script_export/v1811_statistical_adapters"
FPC = REPO / "tests/fixtures/survey_fpc_v1811"
NB = REPO / "tests/fixtures/postestimation/glm_negative_binomial_v1811/native-r/oracle.json"
TOL = {"coefficients": {"abs": 1e-8, "rel": 0}, "std_errors": {"abs": 1e-6, "rel": 0},
       "statistics.value": {"abs": 1e-8, "rel": 1e-6}, "statistics.p_value": {"abs": 0, "rel": 1e-5}}


def directory(label):
    path = run_dir("script-adapter-runs") / f"{label}_{uuid4().hex[:10]}"
    path.mkdir()
    return path


def input_source(path, original):
    data = original.read_bytes()
    (path / "data.csv").write_bytes(data)
    return ScriptSource("source", "csv", "data.csv", hashlib.sha256(data).hexdigest())


def native_run(plan, language, path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(REPO / "backend"))
    exported = export_script(plan, language, require_native=True)
    assert all(item.status != "snapshot" for item in exported.coverage)
    run_exported(exported, plan, path, monkeypatch)


def run_exported(exported, plan, path, monkeypatch, *, expect_failure=False):
    monkeypatch.setenv("PYTHONPATH", str(REPO / "backend"))
    language = exported.language
    started = time.perf_counter()
    try:
        code, output = execute(exported, path, plan)
    finally:
        log = path / "analysis.log"
        if log.exists():
            raw = log.read_bytes()
            local = run_dir("script-adapter-raw-logs") / path.name / log.name
            local.parent.mkdir(parents=True, exist_ok=True)
            assert not local.exists()
            local.write_bytes(raw); local.chmod(0o600)
            assert subprocess.run(["git", "check-ignore", "--quiet", str(local)], cwd=REPO).returncode == 0
            header = re.compile(rb"(?m)^([ \t]*(?:Serial number|Licensed to)[ \t]*:[ \t]*)([^\r\n]*)(\r?\n|$)")
            sanitized = header.sub(lambda m: m.group(1)+b"[REDACTED]"+m.group(3), raw)
            payload = lambda text: header.sub(lambda m: m.group(1)+m.group(3), text)
            assert payload(raw) == payload(sanitized)
            log.write_bytes(sanitized)
            (path / "log_protection.json").write_text(json.dumps({"raw_sha256": hashlib.sha256(raw).hexdigest(),
                "redacted_sha256": hashlib.sha256(sanitized).hexdigest(), "ignored_raw": str(local.relative_to(REPO)),
                "outside_header_values_byte_identical": True, "raw_mode": "0600"}, indent=2)+"\n")
    (path / "timing.json").write_text(json.dumps({"elapsed_seconds": time.perf_counter()-started, "language": language, "includes_process_startup_and_evidence": True})+"\n")
    assert (code != 0 if expect_failure else code == 0), output
    if expect_failure: assert not (path / "numeric_actual.tsv").exists(), "Invalid design reached numeric checks"
    print("Native evidence:", path.relative_to(REPO), language)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("case", ["population", "fraction", "subpopulation", "lonely_census", "no_psu", "no_strata", "zero_fraction"])
def test_approved_single_stage_fpc_is_executed_natively(language, case, monkeypatch):
    reference = json.loads((FPC / "oracle_reference.json").read_text())["cases"][case]
    path = directory(f"fpc_{case}_{language}")
    data = pd.read_csv(FPC / f"{reference['source']}.csv")
    if not reference["psu"]: data["observation_fpc"] = 20
    if not reference["strata"]: data["unstratified_fpc"] = 32
    data.to_csv(path / "input.csv", index=False)
    design = {"sampling_weight": "weight", "survey_fpc_col": reference["fpc"], "survey_df": "design"}
    if reference["psu"]: design["survey_psu_col"] = "psu"
    if reference["strata"]: design["survey_strata_col"] = "stratum"
    if reference["domain"]: design["survey_subpop"] = "subpop == 1"
    parameters = {"model_type": "ols", "y": "y", "x": ["x1", "x2"], "covariance": "survey_design",
                  "weights": {"kind": "sampling", "column": "weight"}, "model_options": {"survey_design": design}}
    public = lambda name: "Intercept" if name == "(Intercept)" else name
    expected = {"nobs": len(data), "coefficients": {public(t): v for t,v in reference["coefficients"].items()},
                "std_errors": {public(t): v for t,v in reference["standard_errors"].items()},
                "statistics": {public(t): {"value": v, "p_value": reference["p"][t], "df": reference["design_df"],
                                           "distribution": "t"} for t,v in reference["t"].items()}}
    model = ScriptStep("model", "model", "model.ols", parameters, ("source",), expected=expected, tolerances=TOL)
    plan = ScriptPlan("fpc", case, (input_source(path, path / "input.csv"),), (model,), "1.8.11", "a"*64)
    native_run(plan, language, path, monkeypatch)


def nb_plan(path, alpha=1., generic=False):
    original = json.loads(NB.read_text())
    reference = original["full_precision"]
    if alpha != 1:
        reference = json.loads((OWNED / "native-r-alpha-half/oracle.json").read_text())["full_precision"]
    params = {"model_type": "glm", "y": "ynb", "x": ["x1", "x2", "x3"], "covariance": "unadjusted",
              "model_options": {"family": "negative_binomial", "alpha": alpha}}
    public = lambda t: "Intercept" if t == "(Intercept)" else t
    expected = {"nobs": int(reference["nobs"]), "coefficients": {public(t): float(v) for t,v in reference["params"].items()},
                "std_errors": {public(t): float(v) for t,v in reference["std_error"].items()}}
    model = ScriptStep("full", "model", "model.glm" if generic else "model.glm:negative_binomial", params,
                       ("source",), expected=expected, tolerances=TOL)
    plan = ScriptPlan("glm_nb", str(alpha), (input_source(path, NB.parents[2] / "data.csv"),), (model,), "1.8.11", "b"*64)
    return plan, reference


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("generic", [False, True])
def test_fixed_alpha_glm_nb_final_eim_model_matches_approved_oracle(language, generic, monkeypatch):
    path = directory(f"glm_nb_{language}_{generic}")
    plan, _ = nb_plan(path, generic=generic)
    native_run(plan, language, path, monkeypatch)


def large_dispersion_data():
    """Public synthetic reviewer case, independent of retained oracle assets."""
    rng = np.random.default_rng(191204)
    x1, x2 = rng.normal(size=(2, 240))
    mu = np.exp(.3+.45*x1-.2*x2)
    return pd.DataFrame({"x1": x1, "x2": x2, "y": rng.negative_binomial(.5, .5/(.5+mu))})


@pytest.mark.parametrize("alpha", [1e20, 1e308])
def test_r_fixed_alpha_convergence_is_certified_before_publishing(alpha, monkeypatch):
    from workbench.econometrics.runner import run_glm
    path = directory(f"glm_nb_convergence_{alpha}_r")
    data = large_dispersion_data()
    data.to_csv(path / "input.csv", index=False)
    parameters = {"model_type": "glm", "y": "y", "x": ["x1", "x2"], "covariance": "unadjusted",
                  "model_options": {"family": "negative_binomial", "alpha": alpha}}
    expected = {"nobs": len(data)}
    if alpha == 1e20:
        owner, fitted = run_glm(data, "y", ["x1", "x2"], "model", "negative_binomial", alpha=alpha)
        assert owner["convergence"]["converged"]
        (path / "completed_owner.json").write_text(json.dumps(owner, indent=2)+"\n")
        names = ["Intercept", "x1", "x2"]
        expected.update(coefficients=dict(zip(names, map(float, fitted.params))),
                        std_errors=dict(zip(names, map(float, fitted.bse))))
    else:
        with pytest.raises(ValueError) as rejected:
            run_glm(data, "y", ["x1", "x2"], "model", "negative_binomial", alpha=alpha)
        (path / "owner_failure.json").write_text(json.dumps({"error": str(rejected.value)})+"\n")
    step = ScriptStep("model", "model", "model.glm:negative_binomial", parameters, ("source",), expected=expected, tolerances=TOL)
    plan = ScriptPlan("glm_nb_convergence", str(alpha), (input_source(path, path / "input.csv"),), (step,), "1.8.11", "f"*64)
    exported = export_script(plan, "r", require_native=True)
    if alpha == 1e20:
        tail = '\nwrite.table(data.frame(iterations=wb_iteration,parameter_change=wb_parameter_change,scaled_score=wb_scaled_score),"convergence.tsv",sep="\\t",row.names=FALSE,quote=FALSE)\n'
        exported = replace(exported, text=exported.text+tail)
    run_exported(exported, plan, path, monkeypatch, expect_failure=alpha == 1e308)
    if alpha == 1e20:
        certificate = pd.read_csv(path / "convergence.tsv", sep="\t").iloc[0]
        assert certificate.parameter_change <= 1e-12
        assert certificate.scaled_score <= 1e-10


POST_CASES = ("wald_joint", "wald_shifted", "lincom", "nlcom", "lr_drop_x2_x3", "margins_average", "margins_means")


def post_plan(plan, reference, case):
    specs = {
        "wald_joint": ("wald", {"constraints": [{"terms": {"x1": 1}, "value": 0}, {"terms": {"x2": 1}, "value": 0}]}),
        "wald_shifted": ("wald", {"constraints": [{"terms": {"x1": 1, "x2": -1}, "value": 1}]}),
        "lincom": ("lincom", {"terms": {"x1": 1, "x2": 2}, "constant": -.5}),
        "nlcom": ("nlcom", {"expression": "x1 / x2"}),
        "lr_drop_x2_x3": ("lr", {}),
        "margins_average": ("margins", {"variables": ["x1", "x2"], "at": "average"}),
        "margins_means": ("margins", {"variables": ["x1", "x2"], "at": "means"}),
    }
    operation, spec = specs[case]
    steps = list(plan.steps); models = ["full"]
    if operation == "lr":
        steps.append(replace(steps[0], step_id="restricted", parameters={**steps[0].parameters, "x": ["x1"]}, expected={}))
        models.append("restricted")
    if operation == "margins":
        r = reference["margins"]["average" if case.endswith("average") else "at_means"]
        expected = {"nobs": int(reference["nobs"]), "coefficients": {t: float(v["estimate"]) for t,v in r.items()},
                    "std_errors": {t: float(v["std_error"]) for t,v in r.items()}}
    else:
        r = reference[case]
        expected = {}
        if operation in {"lincom", "nlcom"}:
            estimate, se = float(r["estimate"]), float(r["std_error"])
            expected.update(coefficients={"estimate": estimate}, std_errors={"estimate": se})
            statistic = estimate/se; p = float(2*stats.norm.sf(abs(statistic))); df = None; distribution = "z"
        else:
            statistic, p = float(r["statistic"]), float(r["p_value"])
            df = int(r.get("df_num", r.get("df"))); distribution = "chi2"
        expected["statistics"] = {"test": {"value": statistic, "p_value": p, "df": df, "distribution": distribution}}
    post_tolerances = {"coefficients": {"abs": 0., "rel": 1e-6},
                       "std_errors": {"abs": 0., "rel": 1e-5 if operation == "margins" else 1e-6},
                       "statistics.value": {"abs": 0., "rel": 1e-6},
                       "statistics.p_value": {"abs": 0., "rel": 1e-5}}
    steps.append(ScriptStep(case, "postestimation", "postestimation."+operation, {**spec, "models": models},
                            tuple(models), expected=expected, tolerances=post_tolerances))
    return replace(plan, steps=tuple(steps)), operation


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("alpha", [1., .5])
@pytest.mark.parametrize("case", POST_CASES)
def test_fixed_alpha_glm_nb_five_operation_consumer_gate_is_truthful(language, alpha, case, monkeypatch):
    path = directory(f"glm_nb_gate_{case}_{alpha}_{language}")
    plan, reference = nb_plan(path, alpha)
    plan, operation = post_plan(plan, reference, case)
    (path / "plan.json").write_text(json.dumps(plan.to_dict(), indent=2)+"\n")
    if ("glm:negative_binomial", operation) not in VALIDATED:
        with pytest.raises(ScriptExportRefusal) as caught: export_script(plan, language, require_native=True)
        (path / "consumer_refusal.json").write_text(json.dumps({"mode": "actual_refusal", "feature_state": "unvalidated", "code": caught.value.code, "message": str(caught.value)})+"\n")
        assert caught.value.code == "NOT_YET_VALIDATED"
    else:
        (path / "consumer_mode.json").write_text(json.dumps({"mode": "actual_native_execution", "feature_state": "validated"})+"\n")
        native_run(plan, language, path, monkeypatch)


@pytest.mark.parametrize("language", LANGUAGES)
def test_glm_nb_different_alpha_matches_independent_native_r(language, monkeypatch):
    path = directory(f"glm_nb_alpha_half_{language}")
    plan, _ = nb_plan(path, .5)
    native_run(plan, language, path, monkeypatch)


@pytest.mark.parametrize("alpha", [None, True, "1", 0, -1, pytest.param(10**400, id="overflow_integer")])
def test_glm_nb_requires_explicit_positive_numeric_alpha(alpha):
    path = directory("invalid_alpha")
    plan, _ = nb_plan(path)
    step = plan.steps[0]
    invalid = replace(step, parameters={**step.parameters, "model_options": {"family": "negative_binomial", "alpha": alpha}})
    with pytest.raises(ScriptExportRefusal): export_script(replace(plan, steps=(invalid,)), "python", require_native=True)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("alpha", [1., .5])
def test_local_native_inference_primitives_preserve_final_eim(language, alpha, monkeypatch):
    """Standalone fitted-model probe, not a claim of public consumer admission."""
    from workbench.script_export.exporters import postestimation
    from workbench.script_export.runtime import RenderContext
    from workbench.script_export.syntax import literal
    path = directory(f"glm_nb_primitives_{alpha}_{language}")
    plan, reference = nb_plan(path, alpha)
    full = plan.steps[0]
    restricted = replace(full, step_id="restricted", parameters={**full.parameters, "x": ["x1"]}, expected={})
    model_plan = replace(plan, steps=(full, restricted))
    exported = export_script(model_plan, language, require_native=True)
    marker = ("*" if language == "stata" else "#")+" Closing self-checks"
    prefix, closing = exported.text.split(marker)
    ctx = RenderContext(language)
    ctx.checks = closing.strip().splitlines()
    ctx.distributions["full"] = "z"
    lines = ["# Standalone inference primitive probe; public postestimation admission is checked separately."] if language != "stata" else ["* Standalone native inference probe; public postestimation admission is checked separately."]
    if language != "stata": lines.append(postestimation.PY_HELPER if language == "python" else postestimation.R_HELPER)
    model_ref = "results['full']" if language == "python" else 'results[["full"]]'
    covariance = model_ref+"['covariance']" if language == "python" else model_ref+"$covariance"
    for i, row in enumerate(reference["covariance"]):
        for j, value in enumerate(row):
            if language == "stata":
                indices = [4, 1, 2, 3]
                expression = f"e(V)[{indices[i]},{indices[j]}]"
            else:
                expression = f"{covariance}[{i},{j}]" if language == "python" else f"{covariance}[{i+1},{j+1}]"
            if language == "stata" and i == j == 0: lines.extend(["frame change wb_model_data1", "estimates restore wb_model1"])
            lines += ctx.numeric_check(full, "statistics.value", expression, float(value))
    for key in ("full", "restricted"):
        if language == "stata":
            lines += [f"frame change wb_model_data{1 if key == 'full' else 2}", f"estimates restore wb_model{1 if key == 'full' else 2}"]
            expression = "e(ll)"
        else:
            expression = f"results[{key!r}]['loglik']" if language == "python" else f'results[["{key}"]]$loglik'
        lines += ctx.numeric_check(full, "statistics.value", expression, float(reference["lr_drop_x2_x3"]["loglik_"+key]))
    for case in POST_CASES:
        complete, operation = post_plan(plan, reference, case)
        step = complete.steps[-1]
        from workbench.contracts.common.envelope import thaw_json
        spec = thaw_json(step.parameters)
        result = "wb_probe"; stata_values = None
        if language == "python":
            expressions = {
                "wald": f"wb_wald({model_ref}, {list(spec.get('constraints', ()))!r})",
                "lincom": f"wb_lincom({model_ref}, {dict(spec.get('terms', {}))!r}, -.5)",
                "nlcom": f"wb_nlcom({model_ref}, lambda b: b['x1']/b['x2'])",
                "lr": "wb_lr(results['full'], results['restricted'])",
                "margins": f"wb_margins({model_ref}, ['x1', 'x2'], {spec.get('at')!r})",
            }
            lines.append(f"{result} = {expressions[operation]}")
        elif language == "r":
            if operation == "wald":
                constraints = spec["constraints"]
                matrix = [[item["terms"].get(name, 0) for name in ["Intercept", "x1", "x2", "x3"]] for item in constraints]
                vector = [item.get("value", 0) for item in constraints]
                flat = [value for row in matrix for value in row]
                expression = f"wb_wald({model_ref}, matrix({literal(flat,'r')},nrow={len(matrix)},byrow=TRUE),{literal(vector,'r')})"
            else:
                expression = {"lincom": f"wb_lincom({model_ref}, c(0,1,2,0), -.5)",
                    "nlcom": f'wb_nlcom({model_ref}, function(b) b[["x1"]]/b[["x2"]])',
                    "lr": 'wb_lr(results[["full"]],results[["restricted"]])',
                    "margins": f'wb_margins({model_ref},c("x1","x2"),{literal(spec.get("at"),"r")})'}.get(operation)
            lines.append(f"{result} <- {expression}")
        else:
            lines += ["frame change wb_model_data1", "estimates restore wb_model1"]
            if operation == "wald":
                lines.append("test (x1=0) (x2=0)" if case == "wald_joint" else "test (x1-x2=1)")
                stata_values = {"statistics": {"test": {"value": "r(chi2)", "p_value": "r(p)", "df": "r(df)"}}}
            elif operation == "lr":
                lines.append("lrtest wb_model1 wb_model2")
                stata_values = {"statistics": {"test": {"value": "r(chi2)", "p_value": "r(p)", "df": "r(df)"}}}
            elif operation == "lincom":
                lines.append("lincom x1+2*x2-.5")
                stata_values = {"coefficients": {"estimate": "r(estimate)"}, "std_errors": {"estimate": "r(se)"},
                    "statistics": {"test": {"value": "r(estimate)/r(se)", "p_value": "r(p)"}}}
            elif operation == "nlcom":
                lines += ["nlcom (_b[x1]/_b[x2])", "matrix wb_pb=r(b)", "matrix wb_pv=r(V)"]
                statistic = "wb_pb[1,1]/sqrt(wb_pv[1,1])"
                stata_values = {"coefficients": {"estimate": "wb_pb[1,1]"}, "std_errors": {"estimate": "sqrt(wb_pv[1,1])"},
                    "statistics": {"test": {"value": statistic, "p_value": f"2*normal(-abs({statistic}))"}}}
            else:
                lines += ["scalar wb_pn=e(N)", "margins, dydx(x1 x2)"+(" atmeans" if spec["at"] == "means" else ""), "matrix wb_pb=r(b)", "matrix wb_pv=r(V)"]
                stata_values = {"nobs": "wb_pn", "coefficients": {t: f"wb_pb[1,{i}]" for i,t in enumerate(("x1","x2"),1)},
                    "std_errors": {t: f"sqrt(wb_pv[{i},{i}])" for i,t in enumerate(("x1","x2"),1)}}
        lines += postestimation.checks(step, ctx, result, stata_values)
    probe = replace(exported, text=prefix+"\n".join(lines)+"\n"+marker+"\n"+"\n".join(ctx.checks)+"\n")
    # Reuse the protected native runner while keeping this probe's status explicit.
    run_exported(probe, model_plan, path, monkeypatch)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("invalid", ["mixed", "missing", "within_stratum", "small_population", "noninteger", "negative", "boolean"])
def test_invalid_fpc_fails_before_numeric_checks(language, invalid, monkeypatch):
    path = directory(f"invalid_fpc_{invalid}_{language}")
    data = pd.read_csv(FPC / "design.csv")
    fpc = "population"
    data[fpc] = 8.
    if invalid == "mixed": data.loc[data.stratum == data.stratum.iloc[0], fpc] = .5
    elif invalid == "missing": data.loc[0, fpc] = np.nan
    elif invalid == "within_stratum": data.loc[0, fpc] = 9
    elif invalid == "small_population":
        data[fpc] = 2.
        data["psu"] = np.arange(len(data))
    elif invalid == "noninteger": data[fpc] = 4.5
    elif invalid == "negative": data.loc[0, fpc] = -1
    elif invalid == "boolean": data[fpc] = False
    data.to_csv(path / "input.csv", index=False)
    design = {"sampling_weight": "weight", "survey_psu_col": "psu", "survey_strata_col": "stratum", "survey_fpc_col": fpc}
    params = {"model_type": "ols", "y": "y", "x": ["x1", "x2"], "covariance": "survey_design",
              "weights": {"kind": "sampling", "column": "weight"}, "model_options": {"survey_design": design}}
    step = ScriptStep("model", "model", "model.ols", params, ("source",), expected={"nobs": len(data)})
    plan = ScriptPlan("invalid_fpc", invalid, (input_source(path, path / "input.csv"),), (step,), "1.8.11", "c"*64)
    run_exported(export_script(plan, language, require_native=True), plan, path, monkeypatch, expect_failure=True)


@pytest.mark.parametrize("language", LANGUAGES)
def test_independent_nb_fixed_alpha_retains_oim_boundary(language):
    path = directory("independent_nb_fixed_alpha")
    plan, _ = nb_plan(path)
    full = plan.steps[0]
    step = replace(full, operation="model.negative_binomial", parameters={**full.parameters, "model_type": "negative_binomial"})
    with pytest.raises(ScriptExportRefusal) as caught:
        export_script(replace(plan, steps=(step,)), language, require_native=True)
    assert caught.value.code == "NOT_FULLY_NATIVE"


@pytest.mark.parametrize("language", LANGUAGES)
def test_fpc_replicate_combination_retains_explicit_refusal(language):
    path = directory("replicate_fpc")
    params = {"model_type": "ols", "y": "y", "x": ["x1", "x2"], "covariance": "survey_design",
              "weights": {"kind": "sampling", "column": "weight"}, "model_options": {"survey_design": {
                  "sampling_weight": "weight", "survey_psu_col": "psu", "survey_strata_col": "stratum",
                  "survey_fpc_col": "population", "survey_method": "brr"}}}
    step = ScriptStep("model", "model", "model.ols", params, ("source",))
    plan = ScriptPlan("replicate_fpc", "refusal", (input_source(path, FPC / "design.csv"),), (step,), "1.8.11", "c"*64)
    with pytest.raises(ScriptExportRefusal) as caught: export_script(plan, language, require_native=True)
    assert caught.value.code == "NOT_FULLY_NATIVE"
