version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-final-oracles/tests/fixtures/postestimation/data.csv", asdouble clear case(preserve)
glm ynb x1 x2 x3, family(nbinomial 1) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)
file write wbout "b__cons" _tab %24.17g (_b[_cons]) _n
file write wbout "se__cons" _tab %24.17g (_se[_cons]) _n
file write wbout "b_x1" _tab %24.17g (_b[x1]) _n
file write wbout "se_x1" _tab %24.17g (_se[x1]) _n
file write wbout "b_x2" _tab %24.17g (_b[x2]) _n
file write wbout "se_x2" _tab %24.17g (_se[x2]) _n
file write wbout "b_x3" _tab %24.17g (_b[x3]) _n
file write wbout "se_x3" _tab %24.17g (_se[x3]) _n
file write wbout "nobs" _tab %24.17g (e(N)) _n
file write wbout "df_resid" _tab %24.17g (e(df)) _n
file write wbout "converged" _tab %24.17g (e(converged)) _n
file write wbout "ll_full" _tab %24.17g (e(ll)) _n
matrix review_cov=e(V)
estimates store review_full
file write wbout "cov_1_1" _tab %24.17g (review_cov[1,1]) _n
file write wbout "cov_1_2" _tab %24.17g (review_cov[1,2]) _n
file write wbout "cov_1_3" _tab %24.17g (review_cov[1,3]) _n
file write wbout "cov_1_4" _tab %24.17g (review_cov[1,4]) _n
file write wbout "cov_2_1" _tab %24.17g (review_cov[2,1]) _n
file write wbout "cov_2_2" _tab %24.17g (review_cov[2,2]) _n
file write wbout "cov_2_3" _tab %24.17g (review_cov[2,3]) _n
file write wbout "cov_2_4" _tab %24.17g (review_cov[2,4]) _n
file write wbout "cov_3_1" _tab %24.17g (review_cov[3,1]) _n
file write wbout "cov_3_2" _tab %24.17g (review_cov[3,2]) _n
file write wbout "cov_3_3" _tab %24.17g (review_cov[3,3]) _n
file write wbout "cov_3_4" _tab %24.17g (review_cov[3,4]) _n
file write wbout "cov_4_1" _tab %24.17g (review_cov[4,1]) _n
file write wbout "cov_4_2" _tab %24.17g (review_cov[4,2]) _n
file write wbout "cov_4_3" _tab %24.17g (review_cov[4,3]) _n
file write wbout "cov_4_4" _tab %24.17g (review_cov[4,4]) _n
test x1 x2
file write wbout "wj_stat" _tab %24.17g (r(chi2)) _n
file write wbout "wj_df" _tab %24.17g (r(df)) _n
file write wbout "wj_p" _tab %24.17g (r(p)) _n
test x1-x2=1
file write wbout "ws_stat" _tab %24.17g (r(chi2)) _n
file write wbout "ws_df" _tab %24.17g (r(df)) _n
file write wbout "ws_p" _tab %24.17g (r(p)) _n
lincom x1+2*x2-.5
file write wbout "lc_est" _tab %24.17g (r(estimate)) _n
file write wbout "lc_se" _tab %24.17g (r(se)) _n
nlcom _b[x1]/_b[x2]
matrix review_b=r(b)
matrix review_V=r(V)
file write wbout "nl_est" _tab %24.17g (review_b[1,1]) _n
file write wbout "nl_se" _tab %24.17g (sqrt(review_V[1,1])) _n
margins, dydx(x1 x2)
matrix review_b=r(b)
matrix review_V=r(V)
file write wbout "ma_x1_est" _tab %24.17g (review_b[1,1]) _n
file write wbout "ma_x1_se" _tab %24.17g (sqrt(review_V[1,1])) _n
file write wbout "ma_x2_est" _tab %24.17g (review_b[1,2]) _n
file write wbout "ma_x2_se" _tab %24.17g (sqrt(review_V[2,2])) _n
margins, dydx(x1 x2) atmeans
matrix review_b=r(b)
matrix review_V=r(V)
file write wbout "mm_x1_est" _tab %24.17g (review_b[1,1]) _n
file write wbout "mm_x1_se" _tab %24.17g (sqrt(review_V[1,1])) _n
file write wbout "mm_x2_est" _tab %24.17g (review_b[1,2]) _n
file write wbout "mm_x2_se" _tab %24.17g (sqrt(review_V[2,2])) _n
glm ynb x1, family(nbinomial 1) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)
file write wbout "ll_restricted" _tab %24.17g (e(ll)) _n
estimates store review_restricted
lrtest review_full review_restricted
file write wbout "lr_stat" _tab %24.17g (r(chi2)) _n
file write wbout "lr_df" _tab %24.17g (r(df)) _n
file write wbout "lr_p" _tab %24.17g (r(p)) _n
file close wbout
