version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/design.csv", asdouble clear case(preserve)
svyset psu [pweight=weight], strata(stratum) singleunit(missing)
svy: regress y x1 x2
file write wbout "without_fpc_df" _tab %21.15g (e(df_r)) _n
file write wbout "without_fpc_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "without_fpc_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "without_fpc_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "without_fpc_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "without_fpc_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "without_fpc_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "without_fpc_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "without_fpc_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "without_fpc_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "without_fpc_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "without_fpc_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "without_fpc_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "without_fpc_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "without_fpc_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "without_fpc_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "without_fpc_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "without_fpc_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "without_fpc_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "without_fpc_wald" _tab %21.15g (r(F)) _n
file write wbout "without_fpc_wald_df" _tab %21.15g (r(df)) _n
file write wbout "without_fpc_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "without_fpc_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "without_fpc_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "without_fpc_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "without_fpc_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "without_fpc_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "without_fpc_lincom_hi" _tab %21.15g (r(ub)) _n
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/design.csv", asdouble clear case(preserve)
svyset psu [pweight=weight], strata(stratum) fpc(population_fpc) singleunit(missing)
svy: regress y x1 x2
file write wbout "population_df" _tab %21.15g (e(df_r)) _n
file write wbout "population_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "population_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "population_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "population_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "population_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "population_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "population_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "population_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "population_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "population_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "population_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "population_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "population_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "population_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "population_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "population_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "population_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "population_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "population_wald" _tab %21.15g (r(F)) _n
file write wbout "population_wald_df" _tab %21.15g (r(df)) _n
file write wbout "population_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "population_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "population_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "population_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "population_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "population_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "population_lincom_hi" _tab %21.15g (r(ub)) _n
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/design.csv", asdouble clear case(preserve)
svyset psu [pweight=weight], strata(stratum) fpc(fraction_fpc) singleunit(missing)
svy: regress y x1 x2
file write wbout "fraction_df" _tab %21.15g (e(df_r)) _n
file write wbout "fraction_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "fraction_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "fraction_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "fraction_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "fraction_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "fraction_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "fraction_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "fraction_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "fraction_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "fraction_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "fraction_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "fraction_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "fraction_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "fraction_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "fraction_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "fraction_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "fraction_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "fraction_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "fraction_wald" _tab %21.15g (r(F)) _n
file write wbout "fraction_wald_df" _tab %21.15g (r(df)) _n
file write wbout "fraction_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "fraction_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "fraction_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "fraction_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "fraction_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "fraction_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "fraction_lincom_hi" _tab %21.15g (r(ub)) _n
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/design.csv", asdouble clear case(preserve)
svyset psu [pweight=weight], strata(stratum) fpc(zero_fpc) singleunit(missing)
svy: regress y x1 x2
file write wbout "zero_fraction_df" _tab %21.15g (e(df_r)) _n
file write wbout "zero_fraction_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "zero_fraction_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "zero_fraction_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "zero_fraction_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "zero_fraction_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "zero_fraction_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "zero_fraction_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "zero_fraction_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "zero_fraction_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "zero_fraction_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "zero_fraction_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "zero_fraction_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "zero_fraction_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "zero_fraction_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "zero_fraction_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "zero_fraction_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "zero_fraction_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "zero_fraction_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "zero_fraction_wald" _tab %21.15g (r(F)) _n
file write wbout "zero_fraction_wald_df" _tab %21.15g (r(df)) _n
file write wbout "zero_fraction_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "zero_fraction_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "zero_fraction_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "zero_fraction_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "zero_fraction_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "zero_fraction_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "zero_fraction_lincom_hi" _tab %21.15g (r(ub)) _n
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/design.csv", asdouble clear case(preserve)
svyset psu [pweight=weight], strata(stratum) fpc(certainty_fpc) singleunit(missing)
svy: regress y x1 x2
file write wbout "certainty_df" _tab %21.15g (e(df_r)) _n
file write wbout "certainty_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "certainty_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "certainty_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "certainty_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "certainty_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "certainty_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "certainty_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "certainty_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "certainty_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "certainty_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "certainty_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "certainty_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "certainty_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "certainty_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "certainty_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "certainty_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "certainty_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "certainty_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "certainty_wald" _tab %21.15g (r(F)) _n
file write wbout "certainty_wald_df" _tab %21.15g (r(df)) _n
file write wbout "certainty_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "certainty_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "certainty_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "certainty_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "certainty_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "certainty_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "certainty_lincom_hi" _tab %21.15g (r(ub)) _n
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/design.csv", asdouble clear case(preserve)
svyset psu [pweight=weight], strata(stratum) fpc(population_certainty_fpc) singleunit(missing)
svy: regress y x1 x2
file write wbout "population_certainty_df" _tab %21.15g (e(df_r)) _n
file write wbout "population_certainty_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "population_certainty_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "population_certainty_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "population_certainty_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "population_certainty_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "population_certainty_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "population_certainty_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "population_certainty_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "population_certainty_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "population_certainty_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "population_certainty_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "population_certainty_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "population_certainty_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "population_certainty_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "population_certainty_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "population_certainty_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "population_certainty_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "population_certainty_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "population_certainty_wald" _tab %21.15g (r(F)) _n
file write wbout "population_certainty_wald_df" _tab %21.15g (r(df)) _n
file write wbout "population_certainty_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "population_certainty_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "population_certainty_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "population_certainty_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "population_certainty_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "population_certainty_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "population_certainty_lincom_hi" _tab %21.15g (r(ub)) _n
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/subpop.csv", asdouble clear case(preserve)
svyset psu [pweight=weight], strata(stratum) fpc(population_fpc) singleunit(missing)
svy, subpop(subpop): regress y x1 x2
file write wbout "subpopulation_df" _tab %21.15g (e(df_r)) _n
file write wbout "subpopulation_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "subpopulation_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "subpopulation_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "subpopulation_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "subpopulation_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "subpopulation_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "subpopulation_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "subpopulation_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "subpopulation_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "subpopulation_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "subpopulation_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "subpopulation_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "subpopulation_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "subpopulation_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "subpopulation_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "subpopulation_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "subpopulation_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "subpopulation_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "subpopulation_wald" _tab %21.15g (r(F)) _n
file write wbout "subpopulation_wald_df" _tab %21.15g (r(df)) _n
file write wbout "subpopulation_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "subpopulation_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "subpopulation_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "subpopulation_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "subpopulation_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "subpopulation_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "subpopulation_lincom_hi" _tab %21.15g (r(ub)) _n
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/lonely.csv", asdouble clear case(preserve)
svyset psu [pweight=weight], strata(stratum) fpc(certainty_fpc) singleunit(missing)
svy: regress y x1 x2
file write wbout "lonely_census_df" _tab %21.15g (e(df_r)) _n
file write wbout "lonely_census_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "lonely_census_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "lonely_census_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "lonely_census_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "lonely_census_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "lonely_census_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "lonely_census_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "lonely_census_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "lonely_census_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "lonely_census_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "lonely_census_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "lonely_census_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "lonely_census_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "lonely_census_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "lonely_census_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "lonely_census_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "lonely_census_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "lonely_census_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "lonely_census_wald" _tab %21.15g (r(F)) _n
file write wbout "lonely_census_wald_df" _tab %21.15g (r(df)) _n
file write wbout "lonely_census_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "lonely_census_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "lonely_census_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "lonely_census_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "lonely_census_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "lonely_census_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "lonely_census_lincom_hi" _tab %21.15g (r(ub)) _n
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/design.csv", asdouble clear case(preserve)
generate long observation_id = _n
generate double observation_fpc = 20
svyset observation_id [pweight=weight], strata(stratum) fpc(observation_fpc) singleunit(missing)
svy: regress y x1 x2
file write wbout "no_psu_df" _tab %21.15g (e(df_r)) _n
file write wbout "no_psu_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "no_psu_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "no_psu_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "no_psu_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "no_psu_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "no_psu_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "no_psu_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "no_psu_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "no_psu_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "no_psu_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "no_psu_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "no_psu_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "no_psu_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "no_psu_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "no_psu_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "no_psu_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "no_psu_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "no_psu_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "no_psu_wald" _tab %21.15g (r(F)) _n
file write wbout "no_psu_wald_df" _tab %21.15g (r(df)) _n
file write wbout "no_psu_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "no_psu_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "no_psu_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "no_psu_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "no_psu_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "no_psu_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "no_psu_lincom_hi" _tab %21.15g (r(ub)) _n
import delimited using "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/design.csv", asdouble clear case(preserve)
generate double unstratified_fpc = 32
svyset psu [pweight=weight], fpc(unstratified_fpc) singleunit(missing)
svy: regress y x1 x2
file write wbout "no_strata_df" _tab %21.15g (e(df_r)) _n
file write wbout "no_strata_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "no_strata_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "no_strata_p_Intercept" _tab %21.15g (2*ttail(e(df_r),abs(_b[_cons]/_se[_cons]))) _n
file write wbout "no_strata_cov_Intercept_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"_cons"))) _n
file write wbout "no_strata_cov_Intercept_x1" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x1"))) _n
file write wbout "no_strata_cov_Intercept_x2" _tab %21.15g (el(e(V),colnumb(e(V),"_cons"),colnumb(e(V),"x2"))) _n
file write wbout "no_strata_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "no_strata_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "no_strata_p_x1" _tab %21.15g (2*ttail(e(df_r),abs(_b[x1]/_se[x1]))) _n
file write wbout "no_strata_cov_x1_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"_cons"))) _n
file write wbout "no_strata_cov_x1_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x1"))) _n
file write wbout "no_strata_cov_x1_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x1"),colnumb(e(V),"x2"))) _n
file write wbout "no_strata_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "no_strata_se_x2" _tab %21.15g (_se[x2]) _n
file write wbout "no_strata_p_x2" _tab %21.15g (2*ttail(e(df_r),abs(_b[x2]/_se[x2]))) _n
file write wbout "no_strata_cov_x2_Intercept" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"_cons"))) _n
file write wbout "no_strata_cov_x2_x1" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x1"))) _n
file write wbout "no_strata_cov_x2_x2" _tab %21.15g (el(e(V),colnumb(e(V),"x2"),colnumb(e(V),"x2"))) _n
test x1 x2
file write wbout "no_strata_wald" _tab %21.15g (r(F)) _n
file write wbout "no_strata_wald_df" _tab %21.15g (r(df)) _n
file write wbout "no_strata_wald_ddf" _tab %21.15g (r(df_r)) _n
file write wbout "no_strata_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "no_strata_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "no_strata_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "no_strata_lincom_p" _tab %21.15g (r(p)) _n
file write wbout "no_strata_lincom_lo" _tab %21.15g (r(lb)) _n
file write wbout "no_strata_lincom_hi" _tab %21.15g (r(ub)) _n
file close wbout
