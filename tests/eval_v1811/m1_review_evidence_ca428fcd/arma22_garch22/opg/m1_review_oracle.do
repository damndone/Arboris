version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-m1/tests/eval_v1811/m1_review_evidence_ca428fcd/arma22_garch22/data.csv", clear asdouble case(preserve)
tsset t
quietly arch y, ar(1/2) ma(1/2) arch(1/2) garch(1/2) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)
file write wbout "ll" _tab %21.15g (e(ll)) _n
file write wbout "nobs" _tab %21.15g (e(N)) _n
file write wbout "converged" _tab %21.15g (e(converged)) _n
matrix b=e(b)
matrix V=e(V)
quietly estat ic
matrix IC=r(S)
file write wbout "aic" _tab %21.15g (IC[1,5]) _n
file write wbout "bic" _tab %21.15g (IC[1,6]) _n
file write wbout "b_mu" _tab %21.15g (b[1,1]) _n
file write wbout "se_mu" _tab %21.15g (sqrt(V[1,1])) _n
file write wbout "lo_mu" _tab %21.15g (b[1,1]-invnormal(.975)*sqrt(V[1,1])) _n
file write wbout "hi_mu" _tab %21.15g (b[1,1]+invnormal(.975)*sqrt(V[1,1])) _n
file write wbout "b_ar1" _tab %21.15g (b[1,2]) _n
file write wbout "se_ar1" _tab %21.15g (sqrt(V[2,2])) _n
file write wbout "lo_ar1" _tab %21.15g (b[1,2]-invnormal(.975)*sqrt(V[2,2])) _n
file write wbout "hi_ar1" _tab %21.15g (b[1,2]+invnormal(.975)*sqrt(V[2,2])) _n
file write wbout "b_ar2" _tab %21.15g (b[1,3]) _n
file write wbout "se_ar2" _tab %21.15g (sqrt(V[3,3])) _n
file write wbout "lo_ar2" _tab %21.15g (b[1,3]-invnormal(.975)*sqrt(V[3,3])) _n
file write wbout "hi_ar2" _tab %21.15g (b[1,3]+invnormal(.975)*sqrt(V[3,3])) _n
file write wbout "b_ma1" _tab %21.15g (b[1,4]) _n
file write wbout "se_ma1" _tab %21.15g (sqrt(V[4,4])) _n
file write wbout "lo_ma1" _tab %21.15g (b[1,4]-invnormal(.975)*sqrt(V[4,4])) _n
file write wbout "hi_ma1" _tab %21.15g (b[1,4]+invnormal(.975)*sqrt(V[4,4])) _n
file write wbout "b_ma2" _tab %21.15g (b[1,5]) _n
file write wbout "se_ma2" _tab %21.15g (sqrt(V[5,5])) _n
file write wbout "lo_ma2" _tab %21.15g (b[1,5]-invnormal(.975)*sqrt(V[5,5])) _n
file write wbout "hi_ma2" _tab %21.15g (b[1,5]+invnormal(.975)*sqrt(V[5,5])) _n
file write wbout "b_arch1" _tab %21.15g (b[1,6]) _n
file write wbout "se_arch1" _tab %21.15g (sqrt(V[6,6])) _n
file write wbout "lo_arch1" _tab %21.15g (b[1,6]-invnormal(.975)*sqrt(V[6,6])) _n
file write wbout "hi_arch1" _tab %21.15g (b[1,6]+invnormal(.975)*sqrt(V[6,6])) _n
file write wbout "b_arch2" _tab %21.15g (b[1,7]) _n
file write wbout "se_arch2" _tab %21.15g (sqrt(V[7,7])) _n
file write wbout "lo_arch2" _tab %21.15g (b[1,7]-invnormal(.975)*sqrt(V[7,7])) _n
file write wbout "hi_arch2" _tab %21.15g (b[1,7]+invnormal(.975)*sqrt(V[7,7])) _n
file write wbout "b_garch1" _tab %21.15g (b[1,8]) _n
file write wbout "se_garch1" _tab %21.15g (sqrt(V[8,8])) _n
file write wbout "lo_garch1" _tab %21.15g (b[1,8]-invnormal(.975)*sqrt(V[8,8])) _n
file write wbout "hi_garch1" _tab %21.15g (b[1,8]+invnormal(.975)*sqrt(V[8,8])) _n
file write wbout "b_garch2" _tab %21.15g (b[1,9]) _n
file write wbout "se_garch2" _tab %21.15g (sqrt(V[9,9])) _n
file write wbout "lo_garch2" _tab %21.15g (b[1,9]-invnormal(.975)*sqrt(V[9,9])) _n
file write wbout "hi_garch2" _tab %21.15g (b[1,9]+invnormal(.975)*sqrt(V[9,9])) _n
file write wbout "b_omega" _tab %21.15g (b[1,10]) _n
file write wbout "se_omega" _tab %21.15g (sqrt(V[10,10])) _n
file write wbout "lo_omega" _tab %21.15g (b[1,10]-invnormal(.975)*sqrt(V[10,10])) _n
file write wbout "hi_omega" _tab %21.15g (b[1,10]+invnormal(.975)*sqrt(V[10,10])) _n
predict double innovation, residuals
predict double variance, variance
format innovation variance %24.17g
export delimited innovation variance using "series.csv", replace
quietly arch y, ar(1/2) ma(1/2) arch(1/2) garch(1/2) arch0(xb) arma0(zero) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)
file write wbout "explicit_ll" _tab %21.15g (e(ll)) _n

file close wbout
