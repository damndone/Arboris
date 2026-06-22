import pandas as pd
from pathlib import Path
from workbench.engine.dcdh_spec import normalize_treatment_path
from workbench.engine.dcdh_estimator import estimate_dcdh

_FIX = Path(__file__).parent / "fixtures" / "dcdh"


def test_excluded_risk_set_and_n_switchers_consistent():
    d = pd.read_csv(_FIX / "panel_baseline1.csv")
    n = normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")
    b = estimate_dcdh(n, cluster_var=None)
    # n_switchers per reported event_time matches the risk-set record for that ell
    rs = {int(r["ell"]): int(r["n_switchers"]) for r in b.diagnostics["risk_set_by_ell"]}
    for ev, nsw in zip(b.event_times, b.n_switchers):
        assert int(nsw) == rs[int(ev)]
    # excluded baseline=1 units carried through, and their IF rows are zero
    assert set(b.diagnostics["excluded_units"]) == set(n.excluded_units)
    assert len(n.excluded_units) > 0   # baseline1 fixture has baseline=1 units
