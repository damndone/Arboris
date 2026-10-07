* Workbench 1.8.11
* project: weighted
* run: analysis_clustered
* lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
* Coverage
* weighted | model.ols | native | 
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

wb_sha "data.csv" "0f643fba418a92bc7a08befa218425056e866314340e1148775107241af4e143"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
regress y x z [aw=aw], vce(cluster group)
estimates store wb_model1
generate long wb_sample_row = _n
generate byte wb_sample1 = e(sample)
scalar wb_number_0 = _b[_cons]
scalar wb_number_1 = _b[x]
scalar wb_number_2 = _b[z]
scalar wb_number_3 = _se[_cons]
scalar wb_number_4 = _se[x]
scalar wb_number_5 = _se[z]
scalar wb_number_6 = e(N)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_7 = (_b[_cons]/_se[_cons])
scalar wb_number_8 = 2*ttail(e(df_r),abs((_b[_cons]/_se[_cons])))
scalar wb_number_9 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_10 = (_b[x]/_se[x])
scalar wb_number_11 = 2*ttail(e(df_r),abs((_b[x]/_se[x])))
scalar wb_number_12 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_13 = (_b[z]/_se[z])
scalar wb_number_14 = 2*ttail(e(df_r),abs((_b[z]/_se[z])))
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
assert !missing(wb_number_0) & abs(wb_number_0-(1.085282749557345)) <= 1e-08+1e-06*abs(1.085282749557345)
assert !missing(wb_number_1) & abs(wb_number_1-(0.6071313851092202)) <= 1e-08+1e-06*abs(0.6071313851092202)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.2043614817840667)) <= 1e-08+1e-06*abs(-0.2043614817840667)
assert !missing(wb_number_3) & abs(wb_number_3-(0.05125740325389353)) <= 1e-08+1e-05*abs(0.05125740325389353)
assert !missing(wb_number_4) & abs(wb_number_4-(0.053246702664154856)) <= 1e-08+1e-05*abs(0.053246702664154856)
assert !missing(wb_number_5) & abs(wb_number_5-(0.0558248494212885)) <= 1e-08+1e-05*abs(0.0558248494212885)
assert !missing(wb_number_6) & abs(wb_number_6-(350)) <= 0.0+0.0*abs(350)
assert !missing(wb_number_7) & abs(wb_number_7-(21.17319022545112)) <= 1e-08+1e-05*abs(21.17319022545112)
assert !missing(wb_number_8) & abs(wb_number_8-(3.6868760298923884e-21)) <= 1e-06+0.0*abs(3.6868760298923884e-21)
assert !missing(wb_number_9) & abs(wb_number_9-(34.0)) <= 0.0+0.0*abs(34.0)
assert !missing(wb_number_10) & abs(wb_number_10-(11.40223440573598)) <= 1e-08+1e-05*abs(11.40223440573598)
assert !missing(wb_number_11) & abs(wb_number_11-(3.6530415561264087e-13)) <= 1e-06+0.0*abs(3.6530415561264087e-13)
assert !missing(wb_number_12) & abs(wb_number_12-(34.0)) <= 0.0+0.0*abs(34.0)
assert !missing(wb_number_13) & abs(wb_number_13-(-3.6607618990931767)) <= 1e-08+1e-05*abs(-3.6607618990931767)
assert !missing(wb_number_14) & abs(wb_number_14-(0.0008460299836023631)) <= 1e-06+0.0*abs(0.0008460299836023631)
assert !missing(wb_number_15) & abs(wb_number_15-(34.0)) <= 0.0+0.0*abs(34.0)
