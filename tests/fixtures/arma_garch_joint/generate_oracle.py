"""Generate independent Stata fixtures in a new directory (no deletions)."""
from pathlib import Path
import json
import math
import re
import subprocess
import sys

output = Path(sys.argv[1]).resolve()
print(f"Oracle output directory: {output}", flush=True)
if "--convert-only" not in sys.argv:
    output.mkdir(parents=True, exist_ok=False)
script = Path(__file__).with_name("generate.do").resolve()
if "--convert-only" not in sys.argv:
    subprocess.run(["/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp", "-b", "do", str(script), str(output)], cwd=output, check=True, timeout=300)
log = next(output.glob("*.log")).read_text()
own = log[log.index(". do "):]
if re.search(r"(?m)^r\(\d+\);", own):
    raise RuntimeError(log[-4000:])
(output/"stata_run.txt").write_text(own)
for source in sorted(output.glob("stata_*.tsv")):
    raw = {k: float(v) for k, v in (line.split("\t") for line in source.read_text().splitlines())}
    if raw["converged"] != 1:
        raise RuntimeError(f"Stata did not converge: {source.name}")
    name = source.stem.removeprefix("stata_")
    case, vce = name.rsplit("_", 1)
    names = ([] if case == "garch11_zero" else ["mu"]) + ["ar1"]
    if case == "garch21_constant": names += ["ar2"]
    names += ["ma1"]
    # Stata stores variance terms before the variance intercept.
    variance = ["arch1", "arch2"] if case == "arch2_constant" else ["arch1", "garch1"]
    stata_names = names + variance + ["omega"]
    names += ["omega"] + variance
    positions = {name: i+1 for i, name in enumerate(stata_names)}
    payload = {
        "source": "Stata 18 arch; arch0(xb) arma0(zero)", "case": case, "vce": vce,
        "parameter_names": names, "stata_parameter_names": stata_names,
        "parameters": {n: raw[f"b{positions[n]}"] for n in names},
        "standard_errors": {n: raw[f"se{positions[n]}"] for n in names},
        "covariance": [[raw[f"v{positions[a]}_{positions[b]}"] for b in names] for a in names],
        "log_likelihood": raw["ll"], "nobs": int(raw["nobs"]), "converged": bool(raw["converged"]),
        "aic": -2*raw["ll"]+2*len(names), "bic": -2*raw["ll"]+len(names)*math.log(raw["nobs"]),
    }
    source.with_suffix(".json").write_text(json.dumps(payload, indent=2)+"\n")
print(log[-500:])
