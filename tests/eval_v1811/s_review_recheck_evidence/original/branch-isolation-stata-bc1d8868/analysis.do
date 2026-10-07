* Workbench 1.8.11
* project: review
* run: branch-isolation
* lineage_hash: 1111111111111111111111111111111111111111111111111111111111111111
* Coverage
* categorical | model.ols | native | 
* continuous | model.ols | native | 
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

wb_sha "data.csv" "0bea4e0503803b2c2abcc213d13f39d8a90afd7d4e346aa1ae854bcbae99482f"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
tempvar wb_category_1_0
egen long `wb_category_1_0' = group(category)
regress y x ib1.`wb_category_1_0'
estimates store wb_model1
generate long wb_sample_row = _n
generate byte wb_sample1 = e(sample)
scalar wb_number_0 = _b[_cons]
quietly summarize `wb_category_1_0' if category == 2.0
local wb_level = r(min)
scalar wb_number_1 = _b[`wb_level'.`wb_category_1_0']
quietly summarize `wb_category_1_0' if category == 3.0
local wb_level = r(min)
scalar wb_number_2 = _b[`wb_level'.`wb_category_1_0']
scalar wb_number_3 = _b[x]
scalar wb_number_4 = _se[_cons]
quietly summarize `wb_category_1_0' if category == 2.0
local wb_level = r(min)
scalar wb_number_5 = _se[`wb_level'.`wb_category_1_0']
quietly summarize `wb_category_1_0' if category == 3.0
local wb_level = r(min)
scalar wb_number_6 = _se[`wb_level'.`wb_category_1_0']
scalar wb_number_7 = _se[x]
scalar wb_number_8 = e(N)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_9 = (_b[_cons]/_se[_cons])
scalar wb_number_10 = 2*ttail(e(df_r),abs((_b[_cons]/_se[_cons])))
scalar wb_number_11 = e(df_r)
quietly summarize `wb_category_1_0' if category == 2.0
local wb_level = r(min)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_12 = (_b[`wb_level'.`wb_category_1_0']/_se[`wb_level'.`wb_category_1_0'])
scalar wb_number_13 = 2*ttail(e(df_r),abs((_b[`wb_level'.`wb_category_1_0']/_se[`wb_level'.`wb_category_1_0'])))
scalar wb_number_14 = e(df_r)
quietly summarize `wb_category_1_0' if category == 3.0
local wb_level = r(min)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_15 = (_b[`wb_level'.`wb_category_1_0']/_se[`wb_level'.`wb_category_1_0'])
scalar wb_number_16 = 2*ttail(e(df_r),abs((_b[`wb_level'.`wb_category_1_0']/_se[`wb_level'.`wb_category_1_0'])))
scalar wb_number_17 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_18 = (_b[x]/_se[x])
scalar wb_number_19 = 2*ttail(e(df_r),abs((_b[x]/_se[x])))
scalar wb_number_20 = e(df_r)
frame copy wb_src0 wb_model_data2
frame change wb_model_data2
regress y x category
estimates store wb_model2
generate long wb_sample_row = _n
generate byte wb_sample2 = e(sample)
scalar wb_number_21 = _b[_cons]
scalar wb_number_22 = _b[x]
scalar wb_number_23 = _b[category]
scalar wb_number_24 = _se[_cons]
scalar wb_number_25 = _se[x]
scalar wb_number_26 = _se[category]
scalar wb_number_27 = e(N)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_28 = (_b[_cons]/_se[_cons])
scalar wb_number_29 = 2*ttail(e(df_r),abs((_b[_cons]/_se[_cons])))
scalar wb_number_30 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_31 = (_b[x]/_se[x])
scalar wb_number_32 = 2*ttail(e(df_r),abs((_b[x]/_se[x])))
scalar wb_number_33 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_34 = (_b[category]/_se[category])
scalar wb_number_35 = 2*ttail(e(df_r),abs((_b[category]/_se[category])))
scalar wb_number_36 = e(df_r)
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
file write wb_review_numbers %21.17g (wb_number_11) _n
file write wb_review_numbers %21.17g (wb_number_12) _n
file write wb_review_numbers %21.17g (wb_number_13) _n
file write wb_review_numbers %21.17g (wb_number_14) _n
file write wb_review_numbers %21.17g (wb_number_15) _n
file write wb_review_numbers %21.17g (wb_number_16) _n
file write wb_review_numbers %21.17g (wb_number_17) _n
file write wb_review_numbers %21.17g (wb_number_18) _n
file write wb_review_numbers %21.17g (wb_number_19) _n
file write wb_review_numbers %21.17g (wb_number_20) _n
file write wb_review_numbers %21.17g (wb_number_21) _n
file write wb_review_numbers %21.17g (wb_number_22) _n
file write wb_review_numbers %21.17g (wb_number_23) _n
file write wb_review_numbers %21.17g (wb_number_24) _n
file write wb_review_numbers %21.17g (wb_number_25) _n
file write wb_review_numbers %21.17g (wb_number_26) _n
file write wb_review_numbers %21.17g (wb_number_27) _n
file write wb_review_numbers %21.17g (wb_number_28) _n
file write wb_review_numbers %21.17g (wb_number_29) _n
file write wb_review_numbers %21.17g (wb_number_30) _n
file write wb_review_numbers %21.17g (wb_number_31) _n
file write wb_review_numbers %21.17g (wb_number_32) _n
file write wb_review_numbers %21.17g (wb_number_33) _n
file write wb_review_numbers %21.17g (wb_number_34) _n
file write wb_review_numbers %21.17g (wb_number_35) _n
file write wb_review_numbers %21.17g (wb_number_36) _n
file close wb_review_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(1.2708994017897324)) <= 1e-08+1e-06*abs(1.2708994017897324)
assert !missing(wb_number_1) & abs(wb_number_1-(0.7035527108942035)) <= 1e-08+1e-06*abs(0.7035527108942035)
assert !missing(wb_number_2) & abs(wb_number_2-(1.5708783411633434)) <= 1e-08+1e-06*abs(1.5708783411633434)
assert !missing(wb_number_3) & abs(wb_number_3-(0.3286601725683639)) <= 1e-08+1e-06*abs(0.3286601725683639)
assert !missing(wb_number_4) & abs(wb_number_4-(0.10937400678256705)) <= 1e-08+1e-05*abs(0.10937400678256705)
assert !missing(wb_number_5) & abs(wb_number_5-(0.1563678541895355)) <= 1e-08+1e-05*abs(0.1563678541895355)
assert !missing(wb_number_6) & abs(wb_number_6-(0.1535480729297494)) <= 1e-08+1e-05*abs(0.1535480729297494)
assert !missing(wb_number_7) & abs(wb_number_7-(0.0642479068074436)) <= 1e-08+1e-05*abs(0.0642479068074436)
assert !missing(wb_number_8) & abs(wb_number_8-(240)) <= 0.0+0.0*abs(240)
assert !missing(wb_number_9) & abs(wb_number_9-(11.619757190721288)) <= 1e-08+1e-05*abs(11.619757190721288)
assert !missing(wb_number_10) & abs(wb_number_10-(5.575649993018833e-25)) <= 1e-06+0.0*abs(5.575649993018833e-25)
assert !missing(wb_number_11) & abs(wb_number_11-(236.0)) <= 0.0+0.0*abs(236.0)
assert !missing(wb_number_12) & abs(wb_number_12-(4.499343644131729)) <= 1e-08+1e-05*abs(4.499343644131729)
assert !missing(wb_number_13) & abs(wb_number_13-(1.070297878290555e-05)) <= 1e-06+0.0*abs(1.070297878290555e-05)
assert !missing(wb_number_14) & abs(wb_number_14-(236.0)) <= 0.0+0.0*abs(236.0)
assert !missing(wb_number_15) & abs(wb_number_15-(10.230531137190138)) <= 1e-08+1e-05*abs(10.230531137190138)
assert !missing(wb_number_16) & abs(wb_number_16-(1.4335782806912002e-20)) <= 1e-06+0.0*abs(1.4335782806912002e-20)
assert !missing(wb_number_17) & abs(wb_number_17-(236.0)) <= 0.0+0.0*abs(236.0)
assert !missing(wb_number_18) & abs(wb_number_18-(5.115500082413364)) <= 1e-08+1e-05*abs(5.115500082413364)
assert !missing(wb_number_19) & abs(wb_number_19-(6.477886934670725e-07)) <= 1e-06+0.0*abs(6.477886934670725e-07)
assert !missing(wb_number_20) & abs(wb_number_20-(236.0)) <= 0.0+0.0*abs(236.0)
assert !missing(wb_number_21) & abs(wb_number_21-(0.4566572648686139)) <= 1e-08+1e-06*abs(0.4566572648686139)
assert !missing(wb_number_22) & abs(wb_number_22-(0.33613214971634603)) <= 1e-08+1e-06*abs(0.33613214971634603)
assert !missing(wb_number_23) & abs(wb_number_23-(0.7861311171736707)) <= 1e-08+1e-06*abs(0.7861311171736707)
assert !missing(wb_number_24) & abs(wb_number_24-(0.1656192709774661)) <= 1e-08+1e-05*abs(0.1656192709774661)
assert !missing(wb_number_25) & abs(wb_number_25-(0.06297017907816094)) <= 1e-08+1e-05*abs(0.06297017907816094)
assert !missing(wb_number_26) & abs(wb_number_26-(0.07666303913940116)) <= 1e-08+1e-05*abs(0.07666303913940116)
assert !missing(wb_number_27) & abs(wb_number_27-(240)) <= 0.0+0.0*abs(240)
assert !missing(wb_number_28) & abs(wb_number_28-(2.757271313739486)) <= 1e-08+1e-05*abs(2.757271313739486)
assert !missing(wb_number_29) & abs(wb_number_29-(0.006282536599842314)) <= 1e-06+0.0*abs(0.006282536599842314)
assert !missing(wb_number_30) & abs(wb_number_30-(237.0)) <= 0.0+0.0*abs(237.0)
assert !missing(wb_number_31) & abs(wb_number_31-(5.337957659277517)) <= 1e-08+1e-05*abs(5.337957659277517)
assert !missing(wb_number_32) & abs(wb_number_32-(2.1978864882588204e-07)) <= 1e-06+0.0*abs(2.1978864882588204e-07)
assert !missing(wb_number_33) & abs(wb_number_33-(237.0)) <= 0.0+0.0*abs(237.0)
assert !missing(wb_number_34) & abs(wb_number_34-(10.254369328408696)) <= 1e-08+1e-05*abs(10.254369328408696)
assert !missing(wb_number_35) & abs(wb_number_35-(1.1722180535591328e-20)) <= 1e-06+0.0*abs(1.1722180535591328e-20)
assert !missing(wb_number_36) & abs(wb_number_36-(237.0)) <= 0.0+0.0*abs(237.0)


