version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-evaluation/tests/fixtures/eval_v1811/lane_e_20261005/r02/e06-values.csv", asdouble clear case(preserve)
tsset t
quietly arima value, arima(0,0,0) noconstant tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-12) iterate(1000)
file write wbout "ll" _tab %24.17g (e(ll)) _n
file write wbout "variance" _tab %24.17g (_b[/sigma]^2) _n
quietly arima value if t<=140, arima(0,0,0) noconstant tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-12) iterate(1000)
file write wbout "prefix_variance" _tab %24.17g (_b[/sigma]^2) _n

file close wbout
