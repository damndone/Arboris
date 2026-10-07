"""VERIFICATION LEVEL: local Stata 18 MP and R MASS, deterministic count data.

Run once per new output directory; previous oracle artifacts are preserved.
"""
from pathlib import Path
import json
import subprocess
import sys
import uuid

import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.stata_oracle import emit, run

ROOT = Path(__file__).resolve().parent

def main():
    output = ROOT / (sys.argv[1] if len(sys.argv) > 1 else f"oracle-{uuid.uuid4().hex}")
    if output.exists():
        raise ValueError("Use a new output directory to preserve oracle artifacts")
    print(f"Oracle output: {output}", flush=True)
    output.mkdir()
    rng = np.random.default_rng(20261004)
    for name, n in [("nb2", 1200), ("nb1", 1500), ("poisson", 2000)]:
        x1, x2 = rng.normal(size=(2, n))
        mu = np.exp(0.4 + 0.35 * x1 - 0.2 * x2)
        if name == "nb2":
            y = rng.negative_binomial(1 / 0.65, 1 / (1 + 0.65 * mu))
        elif name == "nb1":
            y = rng.negative_binomial(mu / 0.8, 1 / 1.8)
        else:
            y = np.random.default_rng(0).poisson(mu)
        pd.DataFrame({"y": y, "x1": x1, "x2": x2}).to_csv(output / f"{name}.csv", index=False, float_format="%.17g")
    commands = [("nb2", "nbreg y x1 x2, difficult iterate(1000) tolerance(1e-12) ltolerance(1e-12)", "lnalpha"),
                ("nb1", "nbreg y x1 x2, dispersion(constant) difficult iterate(1000) tolerance(1e-12) ltolerance(1e-12)", "lndelta"),
                ("fixed", "glm y x1 x2, family(nbinomial 0.5) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)", None),
                ("poisson", "nbreg y x1 x2, difficult iterate(1000) tolerance(1e-10) ltolerance(1e-12)", "lnalpha")]
    results = {}
    for name, command, ancillary in commands:
        data = "nb2" if name == "fixed" else name
        lines = [f'import delimited "{output / (data + ".csv")}", asdouble clear case(preserve)', command]
        for term in ["_cons", "x1", "x2"] + ([ancillary] if ancillary else []):
            for stat, expr in [("b", f"_b[{'/' if term == ancillary else ''}{term}]"), ("se", f"_se[{'/' if term == ancillary else ''}{term}]")]:
                lines.append(emit(f"{stat}_{term}", expr).replace("%21.15g", "%24.17g"))
        for key, expr in [("ll", "e(ll)"), ("n", "e(N)"), ("converged", "e(converged)")]:
            lines.append(emit(key, expr).replace("%21.15g", "%24.17g"))
        if ancillary:
            lines.extend([emit("lr", "e(chi2_c)").replace("%21.15g", "%24.17g"),
                          emit("p_lr", "cond(e(chi2_c) > 0, chi2tail(1, e(chi2_c))/2, 1)").replace("%21.15g", "%24.17g")])
        results[name] = run(output / f"stata_{name}", "\n".join(lines))
    (output / "stata.json").write_text(json.dumps(results, indent=2) + "\n")
    subprocess.run(["Rscript", str(ROOT / "generate_oracle.R"), str(output)], check=True)

if __name__ == "__main__":
    main()
