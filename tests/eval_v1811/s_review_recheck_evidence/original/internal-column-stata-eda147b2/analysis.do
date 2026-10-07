* Workbench 1.8.11
* project: review
* run: internal-column
* lineage_hash: 2222222222222222222222222222222222222222222222222222222222222222
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

wb_sha "data.csv" "0bea4e0503803b2c2abcc213d13f39d8a90afd7d4e346aa1ae854bcbae99482f"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
tempvar wb_category_1_0
egen long `wb_category_1_0' = group(category)
regress y wb_cat0 ib1.`wb_category_1_0'
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
scalar wb_number_3 = _b[wb_cat0]
scalar wb_number_4 = _se[_cons]
quietly summarize `wb_category_1_0' if category == 2.0
local wb_level = r(min)
scalar wb_number_5 = _se[`wb_level'.`wb_category_1_0']
quietly summarize `wb_category_1_0' if category == 3.0
local wb_level = r(min)
scalar wb_number_6 = _se[`wb_level'.`wb_category_1_0']
scalar wb_number_7 = _se[wb_cat0]
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
scalar wb_number_18 = (_b[wb_cat0]/_se[wb_cat0])
scalar wb_number_19 = 2*ttail(e(df_r),abs((_b[wb_cat0]/_se[wb_cat0])))
scalar wb_number_20 = e(df_r)
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
file close wb_review_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(1.3535431849425417)) <= 1e-08+1e-06*abs(1.3535431849425417)
assert !missing(wb_number_1) & abs(wb_number_1-(0.5355131851309874)) <= 1e-08+1e-06*abs(0.5355131851309874)
assert !missing(wb_number_2) & abs(wb_number_2-(1.5052757759719748)) <= 1e-08+1e-06*abs(1.5052757759719748)
assert !missing(wb_number_3) & abs(wb_number_3-(0.012904407887460556)) <= 1e-08+1e-06*abs(0.012904407887460556)
assert !missing(wb_number_4) & abs(wb_number_4-(0.1148576860774841)) <= 1e-08+1e-05*abs(0.1148576860774841)
assert !missing(wb_number_5) & abs(wb_number_5-(0.16341097766868193)) <= 1e-08+1e-05*abs(0.16341097766868193)
assert !missing(wb_number_6) & abs(wb_number_6-(0.16317681892709418)) <= 1e-08+1e-05*abs(0.16317681892709418)
assert !missing(wb_number_7) & abs(wb_number_7-(0.06663453232839193)) <= 1e-08+1e-05*abs(0.06663453232839193)
assert !missing(wb_number_8) & abs(wb_number_8-(240)) <= 0.0+0.0*abs(240)
assert !missing(wb_number_9) & abs(wb_number_9-(11.78452423314038)) <= 1e-08+1e-05*abs(11.78452423314038)
assert !missing(wb_number_10) & abs(wb_number_10-(1.6316144141067668e-25)) <= 1e-06+0.0*abs(1.6316144141067668e-25)
assert !missing(wb_number_11) & abs(wb_number_11-(236.0)) <= 0.0+0.0*abs(236.0)
assert !missing(wb_number_12) & abs(wb_number_12-(3.277094310131037)) <= 1e-08+1e-05*abs(3.277094310131037)
assert !missing(wb_number_13) & abs(wb_number_13-(0.0012067239241645097)) <= 1e-06+0.0*abs(0.0012067239241645097)
assert !missing(wb_number_14) & abs(wb_number_14-(236.0)) <= 0.0+0.0*abs(236.0)
assert !missing(wb_number_15) & abs(wb_number_15-(9.224813829987196)) <= 1e-08+1e-05*abs(9.224813829987196)
assert !missing(wb_number_16) & abs(wb_number_16-(1.6556596795009354e-17)) <= 1e-06+0.0*abs(1.6556596795009354e-17)
assert !missing(wb_number_17) & abs(wb_number_17-(236.0)) <= 0.0+0.0*abs(236.0)
assert !missing(wb_number_18) & abs(wb_number_18-(0.19365946509332954)) <= 1e-08+1e-05*abs(0.19365946509332954)
assert !missing(wb_number_19) & abs(wb_number_19-(0.8466091101084966)) <= 1e-06+0.0*abs(0.8466091101084966)
assert !missing(wb_number_20) & abs(wb_number_20-(236.0)) <= 0.0+0.0*abs(236.0)


