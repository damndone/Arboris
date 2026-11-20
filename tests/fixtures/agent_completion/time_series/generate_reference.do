version 18
args repo
cd "`repo'"
set more off
import delimited using tests/fixtures/agent_completion/time_series/input.csv, clear varnames(1) asdouble
tsset time
quietly dfuller y, lags(4) regress
scalar adf = r(Zt)
quietly wntestq innovation, lags(10)
scalar lb = r(stat)
scalar lbp = chi2tail(9, lb)
* The fixture has exactly zero mean, so regress residuals equal innovations.
quietly regress innovation
quietly estat archlm, lags(10)
matrix lm = r(arch)
scalar rawlm = lm[1,1]
file open out using tests/fixtures/agent_completion/time_series/reference_stata.csv, write replace
file write out "adf,ljung_box,ljung_box_p,arch_lm_raw" _n
file write out %24.17g (adf) "," %24.17g (lb) "," %24.17g (lbp) "," %24.17g (rawlm) _n
file close out
