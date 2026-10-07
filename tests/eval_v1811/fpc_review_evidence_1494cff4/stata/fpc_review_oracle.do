version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/design.csv", clear asdouble case(preserve)
svyset psu [pweight=weight], strata(stratum) fpc(population_fpc) singleunit(missing)
svy: regress y x1 x2
file write wbout "population_df" _tab %21.15g (e(df_r)) _n
file write wbout "population_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "population_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "population_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "population_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "population_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "population_se_x2" _tab %21.15g (_se[x2]) _n
test x1 x2
file write wbout "population_wald" _tab %21.15g (r(F)) _n
file write wbout "population_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "population_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "population_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "population_lincom_p" _tab %21.15g (r(p)) _n
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-fpc/tests/fixtures/survey_fpc_v1811/subpop.csv", clear asdouble case(preserve)
svyset psu [pweight=weight], strata(stratum) fpc(population_fpc) singleunit(missing)
svy, subpop(subpop): regress y x1 x2
file write wbout "subpopulation_df" _tab %21.15g (e(df_r)) _n
file write wbout "subpopulation_b_Intercept" _tab %21.15g (_b[_cons]) _n
file write wbout "subpopulation_se_Intercept" _tab %21.15g (_se[_cons]) _n
file write wbout "subpopulation_b_x1" _tab %21.15g (_b[x1]) _n
file write wbout "subpopulation_se_x1" _tab %21.15g (_se[x1]) _n
file write wbout "subpopulation_b_x2" _tab %21.15g (_b[x2]) _n
file write wbout "subpopulation_se_x2" _tab %21.15g (_se[x2]) _n
test x1 x2
file write wbout "subpopulation_wald" _tab %21.15g (r(F)) _n
file write wbout "subpopulation_wald_p" _tab %21.15g (r(p)) _n
lincom x1-x2
file write wbout "subpopulation_lincom" _tab %21.15g (r(estimate)) _n
file write wbout "subpopulation_lincom_se" _tab %21.15g (r(se)) _n
file write wbout "subpopulation_lincom_p" _tab %21.15g (r(p)) _n
file close wbout
