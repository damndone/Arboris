version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-evaluation/tests/fixtures/eval_v1811/lane_e_20261005/r01/fixed.csv", asdouble clear case(preserve)
quietly glm y x1 x2, family(nbinomial 0.7) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)
file write wbout "b__cons" _tab %24.17g (_b[_cons]) _n
file write wbout "se__cons" _tab %24.17g (_se[_cons]) _n
file write wbout "b_x1" _tab %24.17g (_b[x1]) _n
file write wbout "se_x1" _tab %24.17g (_se[x1]) _n
file write wbout "b_x2" _tab %24.17g (_b[x2]) _n
file write wbout "se_x2" _tab %24.17g (_se[x2]) _n
file write wbout "ll" _tab %24.17g (e(ll)) _n
file write wbout "n" _tab %24.17g (e(N)) _n

file close wbout
