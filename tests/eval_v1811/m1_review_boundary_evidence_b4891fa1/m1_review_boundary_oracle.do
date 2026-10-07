version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-m1/tests/eval_v1811/m1_review_evidence_ca428fcd/arma22_garch22/data.csv", clear asdouble case(preserve)
tsset t
constraint define 1 [ARCH]L.garch=0
quietly arch y, ar(1/2) ma(1/2) arch(1/2) garch(1/2) constraints(1) arch0(xb) arma0(zero) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)
file write wbout "ll" _tab %21.15g (e(ll)) _n
file write wbout "converged" _tab %21.15g (e(converged)) _n
matrix b=e(b)
file write wbout "mu" _tab %21.15g (b[1,1]) _n
file write wbout "ar1" _tab %21.15g (b[1,2]) _n
file write wbout "ar2" _tab %21.15g (b[1,3]) _n
file write wbout "ma1" _tab %21.15g (b[1,4]) _n
file write wbout "ma2" _tab %21.15g (b[1,5]) _n
file write wbout "arch1" _tab %21.15g (b[1,6]) _n
file write wbout "arch2" _tab %21.15g (b[1,7]) _n
file write wbout "garch1" _tab %21.15g (b[1,8]) _n
file write wbout "garch2" _tab %21.15g (b[1,9]) _n
file write wbout "omega" _tab %21.15g (b[1,10]) _n

file close wbout
