"""Performance budget measured against the N=2540 independent oracle sample."""
from pathlib import Path
from time import perf_counter
import pandas as pd
from workbench.engine.packs.arma_garch.joint_mle import fit_joint_arma_garch
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec

ROOT = Path(__file__).resolve().parents[2]/"fixtures"/"arma_garch_joint"/"oracle_v1"

def test_joint_2540_fit_under_ten_seconds():
    values = pd.read_csv(ROOT/"data_garch11_constant.csv")["y"].to_numpy()
    assert len(values) == 2540
    started = perf_counter()
    result = fit_joint_arma_garch(values, mean_p=1, mean_q=1, include_constant=True,
        variance_spec=VarianceCandidateSpec.create(model="garch",p=1,q=1,distribution="normal"),
        time_index_semantics="observation_order")
    elapsed = perf_counter()-started
    print(f"joint_fit_n2540_seconds={elapsed:.6f}; iterations={result.convergence_details['iterations']}")
    assert result.converged
    assert elapsed < 10.
