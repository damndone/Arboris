version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-final-oracles/tests/fixtures/postestimation/data.csv", asdouble clear case(preserve)
glm ynb x1 x2 x3, family(nbinomial 1) link(log) irls scale(1) iterate(1000) tolerance(1e-14)
file write wbout "b__cons" _tab %24.17g (_b[_cons]) _n
file write wbout "se__cons" _tab %24.17g (_se[_cons]) _n
file write wbout "b_x1" _tab %24.17g (_b[x1]) _n
file write wbout "se_x1" _tab %24.17g (_se[x1]) _n
file write wbout "b_x2" _tab %24.17g (_b[x2]) _n
file write wbout "se_x2" _tab %24.17g (_se[x2]) _n
file write wbout "b_x3" _tab %24.17g (_b[x3]) _n
file write wbout "se_x3" _tab %24.17g (_se[x3]) _n
file write wbout "ll_full" _tab %24.17g (e(ll)) _n
file write wbout "nobs" _tab %24.17g (e(N)) _n
file write wbout "df_resid" _tab %24.17g (e(df)) _n
file write wbout "converged" _tab %24.17g (e(converged)) _n
estimates store full
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
matrix nb_nl_b=r(b)
matrix nb_nl_v=r(V)
file write wbout "nl_est" _tab %24.17g (nb_nl_b[1,1]) _n
file write wbout "nl_se" _tab %24.17g (sqrt(nb_nl_v[1,1])) _n
margins, dydx(x1 x2)
matrix nb_ma_b=r(b)
matrix nb_ma_v=r(V)
file write wbout "ma_x1_est" _tab %24.17g (nb_ma_b[1,1]) _n
file write wbout "ma_x1_se" _tab %24.17g (sqrt(nb_ma_v[1,1])) _n
file write wbout "ma_x2_est" _tab %24.17g (nb_ma_b[1,2]) _n
file write wbout "ma_x2_se" _tab %24.17g (sqrt(nb_ma_v[2,2])) _n
margins, dydx(x1 x2) atmeans
matrix nb_mm_b=r(b)
matrix nb_mm_v=r(V)
file write wbout "mm_x1_est" _tab %24.17g (nb_mm_b[1,1]) _n
file write wbout "mm_x1_se" _tab %24.17g (sqrt(nb_mm_v[1,1])) _n
file write wbout "mm_x2_est" _tab %24.17g (nb_mm_b[1,2]) _n
file write wbout "mm_x2_se" _tab %24.17g (sqrt(nb_mm_v[2,2])) _n
glm ynb x1, family(nbinomial 1) link(log) irls scale(1) iterate(1000) tolerance(1e-14)
file write wbout "ll_restricted" _tab %24.17g (e(ll)) _n
estimates store restricted
lrtest full restricted
file write wbout "lr_stat" _tab %24.17g (r(chi2)) _n
file write wbout "lr_df" _tab %24.17g (r(df)) _n
file write wbout "lr_p" _tab %24.17g (r(p)) _n
file close wbout
