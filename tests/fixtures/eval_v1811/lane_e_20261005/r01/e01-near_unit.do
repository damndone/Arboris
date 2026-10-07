version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-evaluation/tests/fixtures/eval_v1811/lane_e_20261005/r01/near_unit.csv", asdouble clear case(preserve)
tsset t
quietly arch y, ar(1/1) ma(1/1) arch(1) garch(1) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)
matrix b=e(b)
matrix V=e(V)
file write wbout "b_mu" _tab %24.17g (b[1,1]) _n
file write wbout "se_mu" _tab %24.17g (sqrt(V[1,1])) _n
file write wbout "b_ar1" _tab %24.17g (b[1,2]) _n
file write wbout "se_ar1" _tab %24.17g (sqrt(V[2,2])) _n
file write wbout "b_ma1" _tab %24.17g (b[1,3]) _n
file write wbout "se_ma1" _tab %24.17g (sqrt(V[3,3])) _n
file write wbout "b_arch1" _tab %24.17g (b[1,4]) _n
file write wbout "se_arch1" _tab %24.17g (sqrt(V[4,4])) _n
file write wbout "b_garch1" _tab %24.17g (b[1,5]) _n
file write wbout "se_garch1" _tab %24.17g (sqrt(V[5,5])) _n
file write wbout "b_omega" _tab %24.17g (b[1,6]) _n
file write wbout "se_omega" _tab %24.17g (sqrt(V[6,6])) _n
file write wbout "ll" _tab %24.17g (e(ll)) _n
file write wbout "n" _tab %24.17g (e(N)) _n
file write wbout "converged" _tab %24.17g (e(converged)) _n
quietly estat ic
matrix IC=r(S)
file write wbout "aic" _tab %24.17g (IC[1,5]) _n
file write wbout "bic" _tab %24.17g (IC[1,6]) _n

file close wbout
