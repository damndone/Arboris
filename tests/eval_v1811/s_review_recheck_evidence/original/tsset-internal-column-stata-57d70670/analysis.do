* Workbench 1.8.11
* project: review
* run: tsset-internal-column
* lineage_hash: 4444444444444444444444444444444444444444444444444444444444444444
* Coverage
* result | data.tsset | native | 
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

wb_sha "data.csv" "939eb0dbfb058ae46a294f9560682d2169e55d365d0a4255344bb1aba7a21853"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb1
frame change wb1
tempvar wb_time
capture confirm string variable time
if !_rc generate double `wb_time' = cond(missing(clock(time, "YMDhms")), clock(time, "YMD"), clock(time, "YMDhms"))
else generate double `wb_time' = time
assert !missing(`wb_time')
sort  `wb_time'
drop `wb_time'
scalar wb_number_0 = _N
unab wb_columns: _all
scalar wb_check_1 = (`"`wb_columns'"' == "time __wb_time")
file open wb_review_numbers using "numeric_actual.tsv", write text replace
file write wb_review_numbers %21.17g (wb_number_0) _n
file close wb_review_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(2)) <= 0.0+0.0*abs(2)
assert wb_check_1 == 1

frame wb1: export delimited using "actual.csv", replace
