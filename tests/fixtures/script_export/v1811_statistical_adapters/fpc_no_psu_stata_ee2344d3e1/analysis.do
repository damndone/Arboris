* Workbench 1.8.11
* project: fpc
* run: no_psu
* lineage_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
* Coverage
* model | model.ols | native_with_equivalence_note | Full single-stage linearization design including supplied FPC and domain; coefficient and joint-test df preserve the executed Workbench convention.
version 18
set more off
set type double
capture program drop wb_repost
program define wb_repost, eclass
    args beta covariance
    ereturn repost b=`beta' V=`covariance', rename
end
capture program drop wb_sha
program define wb_sha
    args filename expected
    tempfile digestfile
    shell shasum -a 256 "`filename'" > "`digestfile'"
    tempname fh
    file open `fh' using "`digestfile'", read text
    file read `fh' line
    file close `fh'
    if substr("`line'",1,64) != "`expected'" {
        display as error "SHA256 mismatch"
        exit 9
    }
end

wb_sha "data.csv" "3481e26e6470f035ed8c2e7339a091f39e2b6b26bf2935bef0cb86901843334a"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
drop if missing(y) | missing(x1) | missing(x2)
assert !missing(observation_fpc) & observation_fpc >= 0
quietly summarize observation_fpc, meanonly
scalar wb_fpc_fraction = (r(max)<=1)
if !wb_fpc_fraction assert observation_fpc>1 & observation_fpc==floor(observation_fpc)
tempvar wb_fpc_order wb_fpc_stratum wb_fpc_psu wb_fpc_tag wb_fpc_n
generate long `wb_fpc_order' = _n
egen long `wb_fpc_stratum' = group(stratum)
generate long `wb_fpc_psu' = _n
egen byte `wb_fpc_tag' = tag(`wb_fpc_stratum' `wb_fpc_psu')
bysort `wb_fpc_stratum': egen long `wb_fpc_n' = total(`wb_fpc_tag')
bysort `wb_fpc_stratum': assert observation_fpc==observation_fpc[1]
if !wb_fpc_fraction assert observation_fpc>=`wb_fpc_n'
sort `wb_fpc_order'
svyset _n [pw=weight], strata(stratum) fpc(observation_fpc) singleunit(missing)
svy: regress y x1 x2
assert e(df_r) > 0
matrix wb_survey_v = e(V)
mata: assert(!hasmissing(st_matrix("wb_survey_v")))
estimates store wb_model1
generate long wb_sample_row = _n
generate byte wb_sample1 = e(sample)
scalar wb_number_0 = _b[_cons]
scalar wb_number_1 = _b[x1]
scalar wb_number_2 = _b[x2]
scalar wb_number_3 = _se[_cons]
scalar wb_number_4 = _se[x1]
scalar wb_number_5 = _se[x2]
scalar wb_number_6 = e(N)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_7 = (_b[_cons]/_se[_cons])
scalar wb_number_8 = 2*ttail(e(df_r),abs((_b[_cons]/_se[_cons])))
scalar wb_number_9 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_10 = (_b[x1]/_se[x1])
scalar wb_number_11 = 2*ttail(e(df_r),abs((_b[x1]/_se[x1])))
scalar wb_number_12 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_13 = (_b[x2]/_se[x2])
scalar wb_number_14 = 2*ttail(e(df_r),abs((_b[x2]/_se[x2])))
scalar wb_number_15 = e(df_r)
file open wb_numbers using "numeric_actual.tsv", write text replace
file write wb_numbers %21.17g (wb_number_0) _n
file write wb_numbers %21.17g (wb_number_1) _n
file write wb_numbers %21.17g (wb_number_2) _n
file write wb_numbers %21.17g (wb_number_3) _n
file write wb_numbers %21.17g (wb_number_4) _n
file write wb_numbers %21.17g (wb_number_5) _n
file write wb_numbers %21.17g (wb_number_6) _n
file write wb_numbers %21.17g (wb_number_7) _n
file write wb_numbers %21.17g (wb_number_8) _n
file write wb_numbers %21.17g (wb_number_9) _n
file write wb_numbers %21.17g (wb_number_10) _n
file write wb_numbers %21.17g (wb_number_11) _n
file write wb_numbers %21.17g (wb_number_12) _n
file write wb_numbers %21.17g (wb_number_13) _n
file write wb_numbers %21.17g (wb_number_14) _n
file write wb_numbers %21.17g (wb_number_15) _n
file close wb_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(4.652711573943111)) <= 1e-08+0*abs(4.652711573943111)
assert !missing(wb_number_1) & abs(wb_number_1-(1.475820771771979)) <= 1e-08+0*abs(1.475820771771979)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.40404481777033774)) <= 1e-08+0*abs(-0.40404481777033774)
assert !missing(wb_number_3) & abs(wb_number_3-(0.525250512865861)) <= 1e-06+0*abs(0.525250512865861)
assert !missing(wb_number_4) & abs(wb_number_4-(0.05532321733839088)) <= 1e-06+0*abs(0.05532321733839088)
assert !missing(wb_number_5) & abs(wb_number_5-(0.059616095688174754)) <= 1e-06+0*abs(0.059616095688174754)
assert !missing(wb_number_6) & abs(wb_number_6-(80)) <= 0.0+0.0*abs(80)
assert !missing(wb_number_7) & abs(wb_number_7-(8.858080972747807)) <= 1e-08+1e-06*abs(8.858080972747807)
assert !missing(wb_number_8) & abs(wb_number_8-(3.8383334444344105e-13)) <= 0+1e-05*abs(3.8383334444344105e-13)
assert !missing(wb_number_9) & abs(wb_number_9-(72)) <= 0.0+0.0*abs(72)
assert !missing(wb_number_10) & abs(wb_number_10-(26.676336676967825)) <= 1e-08+1e-06*abs(26.676336676967825)
assert !missing(wb_number_11) & abs(wb_number_11-(4.657314431140665e-39)) <= 0+1e-05*abs(4.657314431140665e-39)
assert !missing(wb_number_12) & abs(wb_number_12-(72)) <= 0.0+0.0*abs(72)
assert !missing(wb_number_13) & abs(wb_number_13-(-6.777445136355729)) <= 1e-08+1e-06*abs(-6.777445136355729)
assert !missing(wb_number_14) & abs(wb_number_14-(2.836264977185451e-09)) <= 0+1e-05*abs(2.836264977185451e-09)
assert !missing(wb_number_15) & abs(wb_number_15-(72)) <= 0.0+0.0*abs(72)
