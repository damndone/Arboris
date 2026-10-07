version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-iv-oracles/tests/fixtures/postestimation/iv_two_endogenous_v1811/data.csv", asdouble clear case(preserve)
ivregress 2sls y x1 (xe1 xe2 = z1 z2), vce(robust)
file write wbout "endogenous" _tab `"`e(endog)'"' _n
file write wbout "exogenous_and_instruments" _tab `"`e(exog)'"' _n
file write wbout "exogenous_regressors" _tab `"`e(exogr)'"' _n
file write wbout "small_option" _tab `"`e(small)'"' _n
file write wbout "vce" _tab `"`e(vce)'"' _n
file write wbout "nobs" _tab %24.17g (e(N)) _n
file write wbout "nominal_residual_df" _tab %24.17g (e(N)-colsof(e(b))) _n
file write wbout "b_Intercept" _tab %24.17g (_b[_cons]) _n
file write wbout "se_Intercept" _tab %24.17g (_se[_cons]) _n
file write wbout "p_Intercept" _tab %24.17g (2*normal(-abs(_b[_cons]/_se[_cons]))) _n
file write wbout "cov_Intercept_Intercept" _tab %24.17g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "cov_Intercept_x1" _tab %24.17g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "cov_Intercept_xe1" _tab %24.17g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"xe1"))) _n
file write wbout "cov_Intercept_xe2" _tab %24.17g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"xe2"))) _n
file write wbout "b_x1" _tab %24.17g (_b[x1]) _n
file write wbout "se_x1" _tab %24.17g (_se[x1]) _n
file write wbout "p_x1" _tab %24.17g (2*normal(-abs(_b[x1]/_se[x1]))) _n
file write wbout "cov_x1_Intercept" _tab %24.17g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "cov_x1_x1" _tab %24.17g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "cov_x1_xe1" _tab %24.17g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"xe1"))) _n
file write wbout "cov_x1_xe2" _tab %24.17g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"xe2"))) _n
file write wbout "b_xe1" _tab %24.17g (_b[xe1]) _n
file write wbout "se_xe1" _tab %24.17g (_se[xe1]) _n
file write wbout "p_xe1" _tab %24.17g (2*normal(-abs(_b[xe1]/_se[xe1]))) _n
file write wbout "cov_xe1_Intercept" _tab %24.17g (el(e(V),colnumb(e(V),"xe1"),colnumb(e(V),"_cons"))) _n
file write wbout "cov_xe1_x1" _tab %24.17g (el(e(V),colnumb(e(V),"xe1"),colnumb(e(V),"x1"))) _n
file write wbout "cov_xe1_xe1" _tab %24.17g (el(e(V),colnumb(e(V),"xe1"),colnumb(e(V),"xe1"))) _n
file write wbout "cov_xe1_xe2" _tab %24.17g (el(e(V),colnumb(e(V),"xe1"),colnumb(e(V),"xe2"))) _n
file write wbout "b_xe2" _tab %24.17g (_b[xe2]) _n
file write wbout "se_xe2" _tab %24.17g (_se[xe2]) _n
file write wbout "p_xe2" _tab %24.17g (2*normal(-abs(_b[xe2]/_se[xe2]))) _n
file write wbout "cov_xe2_Intercept" _tab %24.17g (el(e(V),colnumb(e(V),"xe2"),colnumb(e(V),"_cons"))) _n
file write wbout "cov_xe2_x1" _tab %24.17g (el(e(V),colnumb(e(V),"xe2"),colnumb(e(V),"x1"))) _n
file write wbout "cov_xe2_xe1" _tab %24.17g (el(e(V),colnumb(e(V),"xe2"),colnumb(e(V),"xe1"))) _n
file write wbout "cov_xe2_xe2" _tab %24.17g (el(e(V),colnumb(e(V),"xe2"),colnumb(e(V),"xe2"))) _n
test xe1 xe2
file write wbout "wald_statistic" _tab %24.17g (r(chi2)) _n
file write wbout "wald_df" _tab %24.17g (r(df)) _n
file write wbout "wald_p" _tab %24.17g (r(p)) _n
ivregress 2sls y x1 (xe1 xe2 = z1 z2), vce(robust) small
file write wbout "control_small_option" _tab `"`e(small)'"' _n
file write wbout "control_df_resid" _tab %24.17g (e(df_r)) _n
file write wbout "control_se_Intercept" _tab %24.17g (_se[_cons]) _n
file write wbout "control_se_x1" _tab %24.17g (_se[x1]) _n
file write wbout "control_se_xe1" _tab %24.17g (_se[xe1]) _n
file write wbout "control_se_xe2" _tab %24.17g (_se[xe2]) _n
test xe1 xe2
file write wbout "control_wald_F" _tab %24.17g (r(F)) _n
file write wbout "control_wald_p" _tab %24.17g (r(p)) _n
file write wbout "control_wald_df_den" _tab %24.17g (r(df_r)) _n
file close wbout
