version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-m2/tests/fixtures/count_models/reference-v3/nb2.csv", asdouble clear case(preserve)
replace y=0.5 in 1
capture noisily glm y x1 x2, family(nbinomial 0.5) link(log) ml
file write wbout "glm_fractional_rc" _tab %21.15g (_rc) _n
capture noisily nbreg y x1 x2
file write wbout "nb_fractional_rc" _tab %21.15g (_rc) _n
replace y=-1 in 1
capture noisily glm y x1 x2, family(nbinomial 0.5) link(log) ml
file write wbout "glm_negative_rc" _tab %21.15g (_rc) _n
file close wbout
