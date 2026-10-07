version 18
set more off
file open wbout using "wb_results.tsv", write replace
import delimited "/Users/jiayuanren/项目规划/.worktrees/codex-v1811-evaluation/tests/fixtures/panel_cluster/staggered.csv", asdouble clear case(preserve)
xtset g time
generate double _evt_m5=(first_treat>0 & time-first_treat==-5)
generate double _evt_m4=(first_treat>0 & time-first_treat==-4)
generate double _evt_m3=(first_treat>0 & time-first_treat==-3)
generate double _evt_m2=(first_treat>0 & time-first_treat==-2)
generate double _evt_p0=(first_treat>0 & time-first_treat==0)
generate double _evt_p1=(first_treat>0 & time-first_treat==1)
generate double _evt_p2=(first_treat>0 & time-first_treat==2)
generate double _evt_p3=(first_treat>0 & time-first_treat==3)
generate double _evt_p4=(first_treat>0 & time-first_treat==4)
quietly xtreg y _evt_m5 _evt_m4 _evt_m3 _evt_m2 _evt_p0 _evt_p1 _evt_p2 _evt_p3 _evt_p4 i.time, fe vce(robust)
file write wbout "b_evt_m5" _tab %24.17g (_b[_evt_m5]) _n
file write wbout "s_evt_m5" _tab %24.17g (_se[_evt_m5]) _n
file write wbout "b_evt_m4" _tab %24.17g (_b[_evt_m4]) _n
file write wbout "s_evt_m4" _tab %24.17g (_se[_evt_m4]) _n
file write wbout "b_evt_m3" _tab %24.17g (_b[_evt_m3]) _n
file write wbout "s_evt_m3" _tab %24.17g (_se[_evt_m3]) _n
file write wbout "b_evt_m2" _tab %24.17g (_b[_evt_m2]) _n
file write wbout "s_evt_m2" _tab %24.17g (_se[_evt_m2]) _n
file write wbout "b_evt_p0" _tab %24.17g (_b[_evt_p0]) _n
file write wbout "s_evt_p0" _tab %24.17g (_se[_evt_p0]) _n
file write wbout "b_evt_p1" _tab %24.17g (_b[_evt_p1]) _n
file write wbout "s_evt_p1" _tab %24.17g (_se[_evt_p1]) _n
file write wbout "b_evt_p2" _tab %24.17g (_b[_evt_p2]) _n
file write wbout "s_evt_p2" _tab %24.17g (_se[_evt_p2]) _n
file write wbout "b_evt_p3" _tab %24.17g (_b[_evt_p3]) _n
file write wbout "s_evt_p3" _tab %24.17g (_se[_evt_p3]) _n
file write wbout "b_evt_p4" _tab %24.17g (_b[_evt_p4]) _n
file write wbout "s_evt_p4" _tab %24.17g (_se[_evt_p4]) _n
quietly test _evt_m5 _evt_m4 _evt_m3 _evt_m2
file write wbout "F" _tab %24.17g (r(F)) _n
file write wbout "df" _tab %24.17g (r(df)) _n
file write wbout "den" _tab %24.17g (r(df_r)) _n
file write wbout "p" _tab %24.17g (r(p)) _n

file close wbout
