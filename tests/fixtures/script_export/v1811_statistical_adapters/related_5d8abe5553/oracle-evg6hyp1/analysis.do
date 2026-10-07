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

wb_sha "data.csv" "eacb266ef543aef43a8488e410bf7c172241d6af18761eefb4d9494b4bcd5630"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
drop if missing(y) | missing(x1) | missing(x2)
svyset psu [pw=weight], strata(stratum) singleunit(scaled)
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
assert !missing(wb_number_0) & abs(wb_number_0-(4.767273406190223)) <= 1e-08+1e-06*abs(4.767273406190223)
assert !missing(wb_number_1) & abs(wb_number_1-(1.4497508730782993)) <= 1e-08+1e-06*abs(1.4497508730782993)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.3932150269716552)) <= 1e-08+1e-06*abs(-0.3932150269716552)
assert !missing(wb_number_3) & abs(wb_number_3-(1.9181699566528825)) <= 1e-08+1e-05*abs(1.9181699566528825)
assert !missing(wb_number_4) & abs(wb_number_4-(0.22676508126636166)) <= 1e-08+1e-05*abs(0.22676508126636166)
assert !missing(wb_number_5) & abs(wb_number_5-(0.08998008468090576)) <= 1e-08+1e-05*abs(0.08998008468090576)
assert !missing(wb_number_6) & abs(wb_number_6-(75)) <= 0.0+0.0*abs(75)
assert !missing(wb_number_7) & abs(wb_number_7-(2.4853237793948635)) <= 1e-08+1e-05*abs(2.4853237793948635)
assert !missing(wb_number_8) & abs(wb_number_8-(0.055477941548960685)) <= 1e-06+0.0*abs(0.055477941548960685)
assert !missing(wb_number_9) & abs(wb_number_9-(5)) <= 0.0+0.0*abs(5)
assert !missing(wb_number_10) & abs(wb_number_10-(6.393183928417093)) <= 1e-08+1e-05*abs(6.393183928417093)
assert !missing(wb_number_11) & abs(wb_number_11-(0.0013871321631685222)) <= 1e-06+0.0*abs(0.0013871321631685222)
assert !missing(wb_number_12) & abs(wb_number_12-(5)) <= 0.0+0.0*abs(5)
assert !missing(wb_number_13) & abs(wb_number_13-(-4.370022859681721)) <= 1e-08+1e-05*abs(-4.370022859681721)
assert !missing(wb_number_14) & abs(wb_number_14-(0.007221909379973519)) <= 1e-06+0.0*abs(0.007221909379973519)
assert !missing(wb_number_15) & abs(wb_number_15-(5)) <= 0.0+0.0*abs(5)
