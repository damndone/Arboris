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

wb_sha "data.csv" "1e2f7b40315855bf1f5f99479fbd380116f8108efc208ed9ca492cd0bca09c48"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
drop if missing(y) | missing(x1) | missing(x2)
svyset psu [pw=weight], strata(stratum) singleunit(missing)
tempvar wb_survey_domain
generate byte `wb_survey_domain' = (!missing(subpop) & (subpop == 1))
svy , subpop(`wb_survey_domain'): regress y x1 x2
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
assert !missing(wb_number_0) & abs(wb_number_0-(5.481670504452019)) <= 1e-08+1e-06*abs(5.481670504452019)
assert !missing(wb_number_1) & abs(wb_number_1-(1.0799199713898355)) <= 1e-08+1e-06*abs(1.0799199713898355)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.331075539731843)) <= 1e-08+1e-06*abs(-0.331075539731843)
assert !missing(wb_number_3) & abs(wb_number_3-(0.6813935741579858)) <= 1e-08+1e-05*abs(0.6813935741579858)
assert !missing(wb_number_4) & abs(wb_number_4-(0.14263448306455281)) <= 1e-08+1e-05*abs(0.14263448306455281)
assert !missing(wb_number_5) & abs(wb_number_5-(0.08154009306687568)) <= 1e-08+1e-05*abs(0.08154009306687568)
assert !missing(wb_number_6) & abs(wb_number_6-(90)) <= 0.0+0.0*abs(90)
assert !missing(wb_number_7) & abs(wb_number_7-(8.04479336516469)) <= 1e-08+1e-05*abs(8.04479336516469)
assert !missing(wb_number_8) & abs(wb_number_8-(1.12125500197196e-05)) <= 1e-06+0.0*abs(1.12125500197196e-05)
assert !missing(wb_number_9) & abs(wb_number_9-(10)) <= 0.0+0.0*abs(10)
assert !missing(wb_number_10) & abs(wb_number_10-(7.571240475566421)) <= 1e-08+1e-05*abs(7.571240475566421)
assert !missing(wb_number_11) & abs(wb_number_11-(1.901277628831977e-05)) <= 1e-06+0.0*abs(1.901277628831977e-05)
assert !missing(wb_number_12) & abs(wb_number_12-(10)) <= 0.0+0.0*abs(10)
assert !missing(wb_number_13) & abs(wb_number_13-(-4.060279149550505)) <= 1e-08+1e-05*abs(-4.060279149550505)
assert !missing(wb_number_14) & abs(wb_number_14-(0.0022855361013486885)) <= 1e-06+0.0*abs(0.0022855361013486885)
assert !missing(wb_number_15) & abs(wb_number_15-(10)) <= 0.0+0.0*abs(10)
