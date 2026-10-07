"""Retain exact native differences and bytewise no-FPC baseline evidence."""
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import types

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "comparison.json"
if OUTPUT.exists():
    raise RuntimeError("Evidence already retained; choose a fresh output before rerunning")
test_path = ROOT.parents[1] / "test_survey_fpc_v1811.py"
spec = importlib.util.spec_from_file_location("fpc_evidence_tests", test_path)
tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tests)


def maximum(a, b):
    return float(np.max(np.abs(np.asarray(a) - np.asarray(b))))


comparisons = {}
for name, reference in tests.REFERENCE.items():
    design, result = tests._fit(reference)
    terms = result.terms
    estimates = [result.estimates[t] for t in terms]
    se = [result.standard_errors[t] for t in terms]
    t_values = np.asarray(estimates) / se
    p = 2 * stats.t.sf(abs(t_values), result.inference_degf)
    wald = result.joint_test(["x1", "x2"])
    item = {
        "design_df": result.inference_degf,
        "workbench_x1_se": result.standard_errors["x1"],
        "r_x1_se": reference["standard_errors"]["x1"],
        "workbench_wald": wald.statistic,
        "r_wald": reference["wald"]["statistic"],
        "r_max_abs": {
            "coefficients": maximum(estimates, [reference["coefficients"][t] for t in terms]),
            "covariance": maximum(result.covariance, reference["covariance"]),
            "se": maximum(se, [reference["standard_errors"][t] for t in terms]),
            "t": maximum(t_values, [reference["t"][t] for t in terms]),
            "p": maximum(p, [reference["p"][t] for t in terms]),
            "ci": maximum([list(result.ci_lower.values()), list(result.ci_upper.values())],
                          [[reference["ci_lower"][t] for t in terms], [reference["ci_upper"][t] for t in terms]]),
            "wald": abs(wald.statistic - reference["wald"]["statistic"]),
            "wald_p": abs(wald.p_value - reference["wald"]["p"]),
        },
    }
    if name in tests.STATA["cases"]:
        native = tests.STATA["values"]
        labels = ["Intercept" if t == "(Intercept)" else t for t in terms]
        item["stata_x1_se"] = native[f"{name}_se_x1"]
        item["stata_wald"] = native[f"{name}_wald"]
        item["stata_max_abs"] = {
            "coefficients": maximum(estimates, [native[f"{name}_b_{t}"] for t in labels]),
            "covariance": maximum(result.covariance,
                                  [[native[f"{name}_cov_{a}_{b}"] for b in labels] for a in labels]),
            "se": maximum(se, [native[f"{name}_se_{t}"] for t in labels]),
            "p": maximum(p, [native[f"{name}_p_{t}"] for t in labels]),
            "wald": abs(wald.statistic - native[f"{name}_wald"]),
            "wald_p": abs(wald.p_value - native[f"{name}_wald_p"]),
        }
    comparisons[name] = item

baseline = "3c8679c273c20ed31c2f58e493d420c2d98952c7"
source = subprocess.check_output(["git", "show", f"{baseline}:backend/workbench/survey/design.py"], text=True)
module = types.ModuleType("workbench.survey._fpc_baseline_evidence")
module.__package__ = "workbench.survey"
sys.modules[module.__name__] = module
exec(compile(source, "baseline_design.py", "exec"), module.__dict__)
regressions = []
for dataset in ("design", "subpop", "lonely"):
    for policy in tests.SurveyDesign.__dataclass_fields__["lonely_psu"].default, "remove", "adjust", "average", "certainty":
        frame = tests._data(dataset)
        options = dict(frame=frame, weight="weight", strata="stratum", psu="psu", lonely_psu=policy)
        actual = tests.SurveyDesign(**options)
        original = module.SurveyDesign(**options)
        for domain in (False, True):
            mask = (frame.subpop.to_numpy() == 1) if domain and "subpop" in frame else None
            contributions = frame[["x1", "x2"]].to_numpy()
            if mask is not None:
                contributions = contributions[mask]
            results = []
            for design in (actual, original):
                try:
                    results.append(design._design_variance(contributions, mask=mask).tobytes())
                except tests.SurveyEngineError as exc:
                    results.append(str(exc))
            assert results[0] == results[1], (dataset, policy, domain)
            regressions.append({"dataset": dataset, "policy": policy, "domain": domain,
                                "bytewise_equal_or_identical_error": True})
OUTPUT.write_text(json.dumps({"cases": comparisons, "baseline": baseline,
                              "no_fpc_regressions": regressions}, indent=2) + "\n")
print(f"Verified {len(comparisons)} native cases and {len(regressions)} bytewise baseline cases")
