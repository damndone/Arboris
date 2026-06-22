import json
from pathlib import Path
import pandas as pd
from workbench.engine.dcdh_spec import normalize_treatment_path
from workbench.econometrics import runner

_FIX = Path(__file__).parent / "fixtures" / "dcdh"


def _norm(name):
    d = pd.read_csv(_FIX / f"panel_{name}.csv")
    return normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")


def test_run_dcdh_result_shape():
    res = runner.run_dcdh(_norm("nonabsorbing"), cluster_var=None)
    es = res["event_study"]
    assert es["label_kind"] == "event_time"
    L = len(es["event_time"])
    for key in ("estimate", "se", "kind", "n_switchers", "pointwise_ci", "uniform_band"):
        assert len(es[key]) == L
    assert es["uniform_crit"] is not None
    assert res["overall_att"]["experimental"] is True
    assert res["honest_did"] is None and res["honest_did_supported"] is False
    json.dumps(res, allow_nan=False)        # JSON-safe


def test_run_dcdh_deterministic():
    a = runner.run_dcdh(_norm("nonabsorbing"), cluster_var=None)
    b = runner.run_dcdh(_norm("nonabsorbing"), cluster_var=None)
    assert json.dumps(a["event_study"], sort_keys=True) == json.dumps(b["event_study"], sort_keys=True)


def test_run_dcdh_effects_match_oracle():
    o = json.loads((_FIX / "dyn_nonabsorbing.json").read_text())
    res = runner.run_dcdh(_norm("nonabsorbing"), cluster_var=None)
    es = res["event_study"]
    eff = [es["estimate"][i] for i, k in enumerate(es["kind"]) if k == "effect"]
    for a, want in zip(eff, o["effect_estimate"]):
        assert abs(a - want) < 1e-6
