"""Persist full engine/oracle comparisons and timings without modifying oracles."""
from pathlib import Path
from time import perf_counter
import json
import numpy as np
import pandas as pd
from workbench.engine.packs.arma_garch.joint_mle import fit_joint_arma_garch
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec
root = Path(__file__).parent
rows = []
for case in ("garch11_constant", "garch11_zero", "garch21_constant", "arch2_constant"):
    values = pd.read_csv(root/"oracle_v1"/f"data_{case}.csv")["y"].to_numpy()
    for vce in ("opg", "oim", "robust"):
        oracle = json.loads((root/"oracle_v1"/f"stata_{case}_{vce}.json").read_text())
        started = perf_counter()
        result = fit_joint_arma_garch(values, mean_p=2 if case=="garch21_constant" else 1, mean_q=1,
            include_constant=case!="garch11_zero", vce=vce,
            variance_spec=VarianceCandidateSpec.create(model="arch" if case=="arch2_constant" else "garch",p=2 if case=="arch2_constant" else 1,q=0 if case=="arch2_constant" else 1,distribution="normal"),
            time_index_semantics="observation_order")
        elapsed = perf_counter()-started
        payload = result.to_dict()
        parameter_diffs = {n: abs(payload["parameters"][n]-oracle["parameters"][n]) for n in oracle["parameter_names"]}
        se_relative = {n: abs(payload["standard_errors"][n]/oracle["standard_errors"][n]-1) for n in oracle["parameter_names"]}
        rows.append({"case":case,"vce":vce,"stata":oracle,"workbench":payload,
            "max_parameter_absolute_difference": max(parameter_diffs.values()),
            "max_se_relative_difference":max(se_relative.values()),
            "ll_relative_difference":abs(payload["log_likelihood"]/oracle["log_likelihood"]-1),
            "covariance_absolute_difference":float(np.max(np.abs(np.asarray(payload["covariance"]["matrix"])-oracle["covariance"]))),
            "elapsed_seconds":elapsed})
        print(f"{case} {vce}: ll={payload['log_likelihood']:.12f}, parameter max={max(parameter_diffs.values()):.3g}, SE max={max(se_relative.values()):.3g}, elapsed={elapsed:.6f}s")
# Keep bulky conditional series in the fixture CSV and tests; evidence records parameters and inference.
for row in rows:
    row["workbench"].pop("conditional_series")
(root/"comparison_v1.json").write_text(json.dumps(rows,indent=2,allow_nan=False)+"\n")
