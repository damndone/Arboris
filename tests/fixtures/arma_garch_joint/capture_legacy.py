"""Capture the exact pre-wiring q=0 result; not an independent numeric oracle."""
from pathlib import Path
import json
import pandas as pd
from workbench.engine.packs.arma_garch.estimation import fit_joint_ar_garch
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec
root = Path(__file__).parent
values = pd.read_csv(root/"oracle_v1"/"data_garch11_constant.csv")["y"].to_numpy()[:220]
result = fit_joint_ar_garch(values, mean_p=1, include_constant=True, variance_spec=VarianceCandidateSpec.create(model="garch",p=1,q=1,distribution="normal"), hold_back=2, time_index_semantics="observation_order")
(root/"legacy_q0_payload.json").write_text(json.dumps(result.to_dict(), sort_keys=True, separators=(",",":"), allow_nan=False)+"\n")
