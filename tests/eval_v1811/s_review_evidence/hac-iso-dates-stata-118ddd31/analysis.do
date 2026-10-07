* Workbench 1.8.11
* project: review
* run: iso-dates
* lineage_hash: 3333333333333333333333333333333333333333333333333333333333333333
* Coverage
* model | model.ols | native | 
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

wb_sha "data.csv" "4248a622d3d0e5c361e3721f7d0341675a5548cee1ce1c34ff0b02170a01ecb8"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
tsset time
newey y x, lag(2)
estimates store wb_model1
generate long wb_sample_row = _n
generate byte wb_sample1 = e(sample)
scalar wb_number_0 = _b[_cons]
scalar wb_number_1 = _b[x]
scalar wb_number_2 = _se[_cons]
scalar wb_number_3 = _se[x]
scalar wb_number_4 = e(N)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_5 = (_b[_cons]/_se[_cons])
scalar wb_number_6 = 2*ttail(e(df_r),abs((_b[_cons]/_se[_cons])))
scalar wb_number_7 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_8 = (_b[x]/_se[x])
scalar wb_number_9 = 2*ttail(e(df_r),abs((_b[x]/_se[x])))
scalar wb_number_10 = e(df_r)
file open wb_review_numbers using "numeric_actual.tsv", write text replace
file write wb_review_numbers %21.17g (wb_number_0) _n
file write wb_review_numbers %21.17g (wb_number_1) _n
file write wb_review_numbers %21.17g (wb_number_2) _n
file write wb_review_numbers %21.17g (wb_number_3) _n
file write wb_review_numbers %21.17g (wb_number_4) _n
file write wb_review_numbers %21.17g (wb_number_5) _n
file write wb_review_numbers %21.17g (wb_number_6) _n
file write wb_review_numbers %21.17g (wb_number_7) _n
file write wb_review_numbers %21.17g (wb_number_8) _n
file write wb_review_numbers %21.17g (wb_number_9) _n
file write wb_review_numbers %21.17g (wb_number_10) _n
file close wb_review_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(2.029731891227981)) <= 1e-08+1e-06*abs(2.029731891227981)
assert !missing(wb_number_1) & abs(wb_number_1-(0.2870153773878842)) <= 1e-08+1e-06*abs(0.2870153773878842)
assert !missing(wb_number_2) & abs(wb_number_2-(0.06617361483917072)) <= 1e-08+1e-05*abs(0.06617361483917072)
assert !missing(wb_number_3) & abs(wb_number_3-(0.07147968356724231)) <= 1e-08+1e-05*abs(0.07147968356724231)
assert !missing(wb_number_4) & abs(wb_number_4-(240)) <= 0.0+0.0*abs(240)
assert !missing(wb_number_5) & abs(wb_number_5-(30.672827775255588)) <= 1e-08+1e-05*abs(30.672827775255588)
assert !missing(wb_number_6) & abs(wb_number_6-(1.1803518241590357e-84)) <= 1e-06+0.0*abs(1.1803518241590357e-84)
assert !missing(wb_number_7) & abs(wb_number_7-(238.0)) <= 0.0+0.0*abs(238.0)
assert !missing(wb_number_8) & abs(wb_number_8-(4.015342025372613)) <= 1e-08+1e-05*abs(4.015342025372613)
assert !missing(wb_number_9) & abs(wb_number_9-(7.959985423803175e-05)) <= 1e-06+0.0*abs(7.959985423803175e-05)
assert !missing(wb_number_10) & abs(wb_number_10-(238.0)) <= 0.0+0.0*abs(238.0)


