from __future__ import annotations

import shutil
import subprocess

import pytest

from workbench.engine.packs.multiple_comparisons import run_games_howell, run_scheffe

from test_multiple_comparisons_pack import GROUPS


def _run_r(script: str) -> list[float]:
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript is required for the external Oracle")
    output = subprocess.run(
        ["Rscript", "--vanilla", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return [float(item) for item in output.split(",")]


def test_scheffe_matches_base_r_pairwise_formula_oracle() -> None:
    result = run_scheffe(GROUPS)
    comparison = result["result"]["comparisons"][0]
    oracle = _run_r(
        "options(digits=17); a<-c(1,1.2,.9,1.1,1,1.1); "
        "b<-c(2,2.1,1.9,2.2,2); c<-c(3,3.5,2.7,3.1); "
        "x<-c(a,b,c); g<-factor(rep(1:3,c(length(a),length(b),length(c)))); "
        "mse<-sum(tapply(x,g,function(v) sum((v-mean(v))^2)))/12; "
        "d<-mean(a)-mean(b); se<-sqrt(mse*(1/length(a)+1/length(b))); "
        "t<-d/se; p<-pf(t^2/2,2,12,lower.tail=FALSE); "
        "crit<-sqrt(2*qf(.95,2,12))*se; cat(d,t,p,d-crit,d+crit,sep=',')"
    )
    assert comparison["mean_difference"] == pytest.approx(oracle[0], abs=1e-14)
    assert comparison["statistic"] == pytest.approx(oracle[1], abs=1e-14)
    assert comparison["p_value"] == pytest.approx(oracle[2], abs=1e-14)
    assert comparison["confidence_interval"] == pytest.approx(oracle[3:5], abs=1e-14)


def test_games_howell_matches_base_r_studentized_range_oracle() -> None:
    result = run_games_howell(GROUPS)
    comparison = result["result"]["comparisons"][0]
    oracle = _run_r(
        "options(digits=17); a<-c(1,1.2,.9,1.1,1,1.1); "
        "b<-c(2,2.1,1.9,2.2,2); va<-var(a); vb<-var(b); "
        "d<-mean(a)-mean(b); v<-va/length(a)+vb/length(b); "
        "df<-v^2/((va/length(a))^2/(length(a)-1)+(vb/length(b))^2/(length(b)-1)); "
        "q<-abs(d)/sqrt(.5*v); p<-ptukey(q,3,df,lower.tail=FALSE); "
        "crit<-qtukey(.95,3,df)*sqrt(.5*v); cat(d,df,q,p,d-crit,d+crit,sep=',')"
    )
    assert comparison["mean_difference"] == pytest.approx(oracle[0], abs=1e-12)
    assert comparison["degrees_of_freedom"] == pytest.approx(oracle[1], abs=1e-12)
    assert comparison["statistic"] == pytest.approx(oracle[2], abs=1e-12)
    assert comparison["p_value"] == pytest.approx(oracle[3], abs=1e-12)
    # SciPy's inverse CDF and R's qtukey agree to roughly 1e-9 in q; after
    # multiplying by this standard error the endpoint difference is below
    # 1e-10 while the p-value tail remains checked at 1e-12 absolute.
    assert comparison["confidence_interval"] == pytest.approx(oracle[4:6], abs=1e-10)
