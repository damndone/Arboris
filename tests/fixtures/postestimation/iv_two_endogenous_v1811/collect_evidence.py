"""Persist actual public artifacts, native errors, and protected-asset hashes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np
from scipy import stats

from workbench.postestimation.registry import run_operation

ROOT = Path(__file__).resolve().parent
print("Writing retained comparison evidence to", ROOT, flush=True)
target = ROOT / "comparison.json"
if target.exists():
    raise RuntimeError("Comparison evidence already retained")
log = (ROOT / "pytest_final_01.txt").read_text()
matches = re.findall(r"Retained public IV run: (.+)", log)
if len(matches) != 1:
    raise RuntimeError("Expected one completed retained public run")
run_root = Path(matches[0])
sources = {
    "public_kernel.json": run_root / "model_results/inference_kernels/iv_2sls_1.json",
    "public_primary.json": run_root / "model_results/iv_2sls_1.json",
    "public_run_inputs.json": run_root / "run_inputs.json",
}
for name, source in sources.items():
    destination = ROOT / name
    if destination.exists():
        raise RuntimeError(f"Retained artifact already exists: {destination}")
    destination.write_bytes(source.read_bytes())
kernel = json.loads((ROOT / "public_kernel.json").read_text())
request = {"constraints": [{"terms": {"xe1": 1}, "value": 0},
                           {"terms": {"xe2": 1}, "value": 0}]}
start = time.perf_counter()
wald = run_operation("wald", [kernel], request)
elapsed = time.perf_counter() - start
comparison = {}
for software in ("r", "stata"):
    reference = json.loads((ROOT / f"{software}_reference.json").read_text())
    order = [reference["terms"].index(t) for t in kernel["param_names"]]
    covariance = np.asarray(reference["covariance"])[np.ix_(order, order)]
    params = np.asarray(kernel["params"])
    se = np.sqrt(np.diag(kernel["vcov"]))
    z = params / se
    p = 2 * stats.norm.sf(abs(z))
    values = {}
    for name, actual, expected in (
        ("params", params, [reference["params"][t] for t in kernel["param_names"]]),
        ("covariance", kernel["vcov"], covariance),
        ("std_error", se, [reference["std_error"][t] for t in kernel["param_names"]]),
        ("z", z, [reference["z"][t] for t in kernel["param_names"]]),
        ("p", p, [reference["p"][t] for t in kernel["param_names"]]),
    ):
        expected = np.asarray(expected)
        delta = abs(np.asarray(actual) - expected)
        values[name] = {"max_abs": float(delta.max()),
                        "max_rel": float((delta / abs(expected)).max())}
    values["wald_statistic"] = {"max_abs": abs(wald["statistic"] - reference["wald_joint"]["statistic"])}
    values["wald_p"] = {"max_abs": abs(wald["p_value"] - reference["wald_joint"]["p_value"])}
    comparison[software] = values
before = json.loads((ROOT / "protected_assets_before.json").read_text())
after = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in before}
assert before == after, "Protected reference assets changed"
(ROOT / "protected_assets_after.json").write_text(json.dumps(after, indent=2) + "\n")
evidence = {"public_run_root": str(run_root), "workbench_wald": wald,
            "kernel_settings": {key: kernel[key] for key in (
                "reference_distribution", "covariance_estimator", "df_method", "df_resid", "nobs")},
            "max_differences": comparison, "wald_seconds_single_call": elapsed,
            "protected_assets_unchanged": len(before),
            "new_data_sha256": hashlib.sha256((ROOT / "data.csv").read_bytes()).hexdigest()}
target.write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(evidence, indent=2))
