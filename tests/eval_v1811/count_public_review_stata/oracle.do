version 18
set more off
import delimited "/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/tests/fixtures/postestimation/data.csv", clear varnames(1)
glm yb x1 x2 x3, family(poisson) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)
estimates store full_different_response
scalar ll_other = e(ll)
glm yc x1, family(poisson) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)
estimates store restricted
scalar ll_restricted = e(ll)
capture noisily lrtest full_different_response restricted
scalar incompatible_rc = _rc
glm yc x1 x2 x3, family(poisson) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)
estimates store full_same_response
lrtest full_same_response restricted
scalar valid_lr = r(chi2)
scalar valid_p = r(p)
file open wbout using "wb_results.tsv", write
file write wbout "incompatible_response_lr_rc" _tab %21.15g (incompatible_rc) _n
file write wbout "invalid_numeric_lr_if_not_rejected" _tab %21.15g (2*(ll_other-ll_restricted)) _n
file write wbout "same_response_lr" _tab %21.15g (valid_lr) _n
file write wbout "same_response_p" _tab %21.15g (valid_p) _n
file close wbout
