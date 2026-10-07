version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-m2/tests/fixtures/count_models/reference-v3/poisson.csv", asdouble clear case(preserve)
nbreg y x1 x2, difficult iterate(1000) tolerance(1e-10) ltolerance(1e-12)
file write wbout "b__cons" _tab %24.17g (_b[_cons]) _n
file write wbout "se__cons" _tab %24.17g (_se[_cons]) _n
file write wbout "b_x1" _tab %24.17g (_b[x1]) _n
file write wbout "se_x1" _tab %24.17g (_se[x1]) _n
file write wbout "b_x2" _tab %24.17g (_b[x2]) _n
file write wbout "se_x2" _tab %24.17g (_se[x2]) _n
file write wbout "b_lnalpha" _tab %24.17g (_b[/lnalpha]) _n
file write wbout "se_lnalpha" _tab %24.17g (_se[/lnalpha]) _n
file write wbout "ll" _tab %24.17g (e(ll)) _n
file write wbout "n" _tab %24.17g (e(N)) _n
file write wbout "converged" _tab %24.17g (e(converged)) _n
file write wbout "lr" _tab %24.17g (e(chi2_c)) _n
file write wbout "p_lr" _tab %24.17g (cond(e(chi2_c) > 0, chi2tail(1, e(chi2_c))/2, 1)) _n
file close wbout
