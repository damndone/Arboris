* Workbench 1.8.11
* project: survey
* run: native
* lineage_hash: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
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

wb_sha "data.csv" "5f8d0cc66fc9efdfd08e6a06640ea410d58671fe93ac5cac2ad90d6aa68de937"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
drop if missing(y) | missing(x1) | missing(x2)
svyset psu [pw=weight], strata(stratum) singleunit(missing)
svy: regress y x1 x2
capture program drop wb_survey_df
program define wb_survey_df, eclass
    ereturn scalar df_r = e(N_psu) - e(N_strata) - e(rank) + 1
end
wb_survey_df
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
assert !missing(wb_number_0) & abs(wb_number_0-(4.652711573943123)) <= 1e-08+1e-06*abs(4.652711573943123)
assert !missing(wb_number_1) & abs(wb_number_1-(1.475820771771979)) <= 1e-08+1e-06*abs(1.475820771771979)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.40404481777033774)) <= 1e-08+1e-06*abs(-0.40404481777033774)
assert !missing(wb_number_3) & abs(wb_number_3-(1.5955241455226616)) <= 1e-08+1e-05*abs(1.5955241455226616)
assert !missing(wb_number_4) & abs(wb_number_4-(0.17732404110690134)) <= 1e-08+1e-05*abs(0.17732404110690134)
assert !missing(wb_number_5) & abs(wb_number_5-(0.08888234469730581)) <= 1e-08+1e-05*abs(0.08888234469730581)
assert !missing(wb_number_6) & abs(wb_number_6-(80)) <= 0.0+0.0*abs(80)
assert !missing(wb_number_7) & abs(wb_number_7-(2.9161022645752492)) <= 1e-08+1e-05*abs(2.9161022645752492)
assert !missing(wb_number_8) & abs(wb_number_8-(0.026766795825847126)) <= 1e-06+0.0*abs(0.026766795825847126)
assert !missing(wb_number_9) & abs(wb_number_9-(6)) <= 0.0+0.0*abs(6)
assert !missing(wb_number_10) & abs(wb_number_10-(8.322733694537604)) <= 1e-08+1e-05*abs(8.322733694537604)
assert !missing(wb_number_11) & abs(wb_number_11-(0.00016326932451573436)) <= 1e-06+0.0*abs(0.00016326932451573436)
assert !missing(wb_number_12) & abs(wb_number_12-(6)) <= 0.0+0.0*abs(6)
assert !missing(wb_number_13) & abs(wb_number_13-(-4.545838874371921)) <= 1e-08+1e-05*abs(-4.545838874371921)
assert !missing(wb_number_14) & abs(wb_number_14-(0.003909008379856854)) <= 1e-06+0.0*abs(0.003909008379856854)
assert !missing(wb_number_15) & abs(wb_number_15-(6)) <= 0.0+0.0*abs(6)
