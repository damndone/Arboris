"""Persist native fixed-NB fractional response evidence in a fresh directory."""
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from tests.stata_oracle import emit, run

HERE = Path(__file__).resolve().parent
output = HERE / "fractional-oracle"
if output.exists():
    raise ValueError("Use a fresh output directory; preserve previous artifacts.")
output.mkdir()
frame = pd.read_csv(HERE.parent / "reference-v3/nb2.csv", float_precision="round_trip")
frame["y"] = frame.y + .25
frame.to_csv(output / "data.csv", index=False, float_format="%.17g")
body = [f'import delimited "{output / "data.csv"}", asdouble clear case(preserve)',
        "glm y x1 x2, family(nbinomial 0.5) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)"]
for term in ["_cons", "x1", "x2"]:
    for stat in ["b", "se"]:
        body.append(emit(f"{stat}_{term}", f"_{stat}[{term}]").replace("%21.15g", "%24.17g"))
body.extend(emit(key, expression).replace("%21.15g", "%24.17g")
            for key, expression in [("ll", "e(ll)"), ("converged", "e(converged)"), ("n", "e(N)")])
reference = run(output / "stata", "\n".join(body))
(output / "stata.json").write_text(json.dumps(reference, indent=2) + "\n")
subprocess.run(["Rscript", str(HERE / "fractional.R"), str(output)], check=True)
print(json.dumps(reference, indent=2))
