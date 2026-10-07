version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-evaluation/tests/fixtures/postestimation/iv_two_endogenous_v1811/data.csv", asdouble clear case(preserve)
quietly ivregress 2sls y x1 (xe1 xe2=z1 z2), vce(robust)
quietly test xe1 xe2
file write wbout "wald" _tab %24.17g (r(chi2)) _n
file write wbout "wald_df" _tab %24.17g (r(df)) _n
file write wbout "wald_p" _tab %24.17g (r(p)) _n
quietly lincom x1-.4*xe1+.1
file write wbout "lincom" _tab %24.17g (r(estimate)) _n
file write wbout "lincom_se" _tab %24.17g (r(se)) _n
file write wbout "lincom_p" _tab %24.17g (r(p)) _n
quietly nlcom exp(_b[xe2]), post
file write wbout "nlcom" _tab %24.17g (_b[_nl_1]) _n
file write wbout "nlcom_se" _tab %24.17g (_se[_nl_1]) _n

file close wbout
