* Workbench 1.8.11
* project: categories
* run: branches
* lineage_hash: 3333333333333333333333333333333333333333333333333333333333333333
* Coverage
* weighted | model.ols | native | 
* plain | model.ols | native | 
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

wb_sha "data.csv" "050b189f5fcd4768e53803d4dfeed0b822fe264a03c4d5414075e42e6a313024"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
tempvar wb_category_1_0
egen long `wb_category_1_0' = group(region)
expand fw
regress y x ib1.`wb_category_1_0'
estimates store wb_model1
generate long wb_sample_row = _n
generate byte wb_sample1 = e(sample)
scalar wb_number_0 = _b[_cons]
quietly summarize `wb_category_1_0' if region == "south"
local wb_level = r(min)
scalar wb_number_1 = _b[`wb_level'.`wb_category_1_0']
quietly summarize `wb_category_1_0' if region == "west"
local wb_level = r(min)
scalar wb_number_2 = _b[`wb_level'.`wb_category_1_0']
scalar wb_number_3 = _b[x]
scalar wb_number_4 = _se[_cons]
quietly summarize `wb_category_1_0' if region == "south"
local wb_level = r(min)
scalar wb_number_5 = _se[`wb_level'.`wb_category_1_0']
quietly summarize `wb_category_1_0' if region == "west"
local wb_level = r(min)
scalar wb_number_6 = _se[`wb_level'.`wb_category_1_0']
scalar wb_number_7 = _se[x]
scalar wb_number_8 = e(N)
frame copy wb_src0 wb_model_data2
frame change wb_model_data2
tempvar wb_category_2_0
egen long `wb_category_2_0' = group(region)
regress y x ib1.`wb_category_2_0'
estimates store wb_model2
generate long wb_sample_row = _n
generate byte wb_sample2 = e(sample)
scalar wb_number_9 = _b[_cons]
quietly summarize `wb_category_2_0' if region == "south"
local wb_level = r(min)
scalar wb_number_10 = _b[`wb_level'.`wb_category_2_0']
quietly summarize `wb_category_2_0' if region == "west"
local wb_level = r(min)
scalar wb_number_11 = _b[`wb_level'.`wb_category_2_0']
scalar wb_number_12 = _b[x]
scalar wb_number_13 = _se[_cons]
quietly summarize `wb_category_2_0' if region == "south"
local wb_level = r(min)
scalar wb_number_14 = _se[`wb_level'.`wb_category_2_0']
quietly summarize `wb_category_2_0' if region == "west"
local wb_level = r(min)
scalar wb_number_15 = _se[`wb_level'.`wb_category_2_0']
scalar wb_number_16 = _se[x]
scalar wb_number_17 = e(N)
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
file write wb_numbers %21.17g (wb_number_16) _n
file write wb_numbers %21.17g (wb_number_17) _n
file close wb_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(1.1406181831101954)) <= 1e-08+1e-06*abs(1.1406181831101954)
assert !missing(wb_number_1) & abs(wb_number_1-(-0.08780030675457805)) <= 1e-08+1e-06*abs(-0.08780030675457805)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.10670733571832419)) <= 1e-08+1e-06*abs(-0.10670733571832419)
assert !missing(wb_number_3) & abs(wb_number_3-(0.5668151259087681)) <= 1e-08+1e-06*abs(0.5668151259087681)
assert !missing(wb_number_4) & abs(wb_number_4-(0.06512778819857358)) <= 1e-08+1e-05*abs(0.06512778819857358)
assert !missing(wb_number_5) & abs(wb_number_5-(0.0938599257916859)) <= 1e-08+1e-05*abs(0.0938599257916859)
assert !missing(wb_number_6) & abs(wb_number_6-(0.0910083263007167)) <= 1e-08+1e-05*abs(0.0910083263007167)
assert !missing(wb_number_7) & abs(wb_number_7-(0.036096598808836394)) <= 1e-08+1e-05*abs(0.036096598808836394)
assert !missing(wb_number_8) & abs(wb_number_8-(692)) <= 0.0+0.0*abs(692)
assert !missing(wb_number_9) & abs(wb_number_9-(1.1525369575209923)) <= 1e-08+1e-06*abs(1.1525369575209923)
assert !missing(wb_number_10) & abs(wb_number_10-(-0.07713734612483514)) <= 1e-08+1e-06*abs(-0.07713734612483514)
assert !missing(wb_number_11) & abs(wb_number_11-(-0.12606025144491617)) <= 1e-08+1e-06*abs(-0.12606025144491617)
assert !missing(wb_number_12) & abs(wb_number_12-(0.5722984010583434)) <= 1e-08+1e-06*abs(0.5722984010583434)
assert !missing(wb_number_13) & abs(wb_number_13-(0.0907095488404284)) <= 1e-08+1e-05*abs(0.0907095488404284)
assert !missing(wb_number_14) & abs(wb_number_14-(0.12857751264891099)) <= 1e-08+1e-05*abs(0.12857751264891099)
assert !missing(wb_number_15) & abs(wb_number_15-(0.1283082512402164)) <= 1e-08+1e-05*abs(0.1283082512402164)
assert !missing(wb_number_16) & abs(wb_number_16-(0.051233154659256375)) <= 1e-08+1e-05*abs(0.051233154659256375)
assert !missing(wb_number_17) & abs(wb_number_17-(350)) <= 0.0+0.0*abs(350)
