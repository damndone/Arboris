import pandas as pd
from pathlib import Path
from workbench.engine.dcdh_spec import normalize_treatment_path
from workbench.econometrics import runner

_FIX = Path(__file__).parent / "fixtures" / "dcdh"


def test_run_dcdh_does_not_call_finalize_did_bundle(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("run_dcdh must NOT call _finalize_did_bundle")
    monkeypatch.setattr(runner, "_finalize_did_bundle", _boom)
    d = pd.read_csv(_FIX / "panel_nonabsorbing.csv")
    n = normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")
    runner.run_dcdh(n, cluster_var=None)    # must not raise
