version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-m2/tests/fixtures/count_models/reference-v3/poisson.csv", asdouble clear case(preserve)
nbreg y x1 x2, difficult iterate(1000) tolerance(1e-10) ltolerance(1e-12)
file write wbout "converged" _tab %21.15g (e(converged)) _n
file write wbout "ll" _tab %21.15g (e(ll)) _n
file write wbout "b_log" _tab %21.15g (_b[/lnalpha]) _n
file write wbout "se_log" _tab %21.15g (_se[/lnalpha]) _n
file write wbout "lr" _tab %21.15g (e(chi2_c)) _n
file close wbout
