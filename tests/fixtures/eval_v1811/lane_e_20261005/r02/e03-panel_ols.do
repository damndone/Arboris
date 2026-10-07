version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-evaluation/tests/fixtures/eval_v1811/lane_e_20261005/r02/panel_ols.csv", asdouble clear case(preserve)
xtset g time
quietly xtreg y x1 x2 i.time , fe vce(robust)
file write wbout "b" _tab %24.17g (_b[x1]) _n
file write wbout "se" _tab %24.17g (_se[x1]) _n
file write wbout "t" _tab %24.17g (_b[x1]/_se[x1]) _n
file write wbout "df" _tab %24.17g (e(df_r)) _n
file write wbout "p" _tab %24.17g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
quietly lincom x1-x2
file write wbout "lc" _tab %24.17g (r(estimate)) _n
file write wbout "lc_se" _tab %24.17g (r(se)) _n
file write wbout "lc_p" _tab %24.17g (r(p)) _n
quietly test x1 x2
file write wbout "wald" _tab %24.17g (r(F)) _n
file write wbout "wald_df" _tab %24.17g (r(df)) _n
file write wbout "wald_den" _tab %24.17g (r(df_r)) _n
file write wbout "wald_p" _tab %24.17g (r(p)) _n

file close wbout
