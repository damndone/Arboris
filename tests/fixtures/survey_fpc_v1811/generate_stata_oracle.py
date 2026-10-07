"""Retained Stata 18 single-stage FPC references, using a fresh batch directory."""
from pathlib import Path
import json
from uuid import uuid4

from tests.stata_oracle import emit, run

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "stata_reference.json"
if OUTPUT.exists():
    raise RuntimeError("Retained Stata oracle exists; choose a fresh output before rerunning")
CASES = {
    "without_fpc": ("design", None, "psu", "stratum", False),
    "population": ("design", "population_fpc", "psu", "stratum", False),
    "fraction": ("design", "fraction_fpc", "psu", "stratum", False),
    "zero_fraction": ("design", "zero_fpc", "psu", "stratum", False),
    "certainty": ("design", "certainty_fpc", "psu", "stratum", False),
    "population_certainty": ("design", "population_certainty_fpc", "psu", "stratum", False),
    "subpopulation": ("subpop", "population_fpc", "psu", "stratum", True),
    "lonely_census": ("lonely", "certainty_fpc", "psu", "stratum", False),
    "no_psu": ("design", "observation_fpc", "observation_id", "stratum", False),
    "no_strata": ("design", "unstratified_fpc", "psu", None, False),
}
body = []
terms = [("Intercept", "_cons"), ("x1", "x1"), ("x2", "x2")]
for case, (source, fpc, psu, stratum, domain) in CASES.items():
    body.append(f'import delimited using "{ROOT / (source + ".csv")}", asdouble clear case(preserve)')
    if psu == "observation_id":
        body.extend(["generate long observation_id = _n", "generate double observation_fpc = 20"])
    if stratum is None:
        body.append("generate double unstratified_fpc = 32")
    options = []
    if stratum:
        options.append(f"strata({stratum})")
    if fpc:
        options.append(f"fpc({fpc})")
    options.append("singleunit(missing)")
    body.append(f"svyset {psu} [pweight=weight], " + " ".join(options))
    body.append("svy, subpop(subpop): regress y x1 x2" if domain else "svy: regress y x1 x2")
    body.append(emit(f"{case}_df", "e(df_r)"))
    for canonical, term in terms:
        body.extend([emit(f"{case}_b_{canonical}", f"_b[{term}]"),
                     emit(f"{case}_se_{canonical}", f"_se[{term}]"),
                     emit(f"{case}_p_{canonical}", f"2*ttail(e(df_r),abs(_b[{term}]/_se[{term}]))")])
        for other_canonical, other in terms:
            body.append(emit(f"{case}_cov_{canonical}_{other_canonical}",
                             f'el(e(V),colnumb(e(V),"{term}"),colnumb(e(V),"{other}"))'))
    body.append("test x1 x2")
    body.extend([emit(f"{case}_wald", "r(F)"), emit(f"{case}_wald_df", "r(df)"),
                 emit(f"{case}_wald_ddf", "r(df_r)"), emit(f"{case}_wald_p", "r(p)")])
    body.append("lincom x1-x2")
    body.extend([emit(f"{case}_lincom", "r(estimate)"), emit(f"{case}_lincom_se", "r(se)"),
                 emit(f"{case}_lincom_p", "r(p)"), emit(f"{case}_lincom_lo", "r(lb)"),
                 emit(f"{case}_lincom_hi", "r(ub)")])
workdir = ROOT / f"stata_batch_{uuid4().hex[:10]}"
assert not workdir.exists()
values = run(workdir, "\n".join(body), name="survey_fpc")
OUTPUT.write_text(json.dumps({"reference": "Stata 18 svy: regress/test/lincom",
                              "batch_directory": workdir.name,
                              "cases": list(CASES), "values": values}, indent=2) + "\n")
print(f"Wrote {OUTPUT} with {len(CASES)} cases; all batch assets retained")
