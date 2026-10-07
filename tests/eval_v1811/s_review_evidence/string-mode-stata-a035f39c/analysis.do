* Workbench 1.8.11
* project: review
* run: string-mode
* lineage_hash: 4444444444444444444444444444444444444444444444444444444444444444
* Coverage
* result | data.fill_missing | native | 
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

wb_sha "data.csv" "63e535a65fadff855bb41ade0b8986f125a13d6d593613819b184f60b13e12da"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", asdouble clear case(preserve)
frame copy wb_src0 wb1
frame change wb1
tempvar wb_mode
egen `wb_mode' = mode(x), minmode
replace x = `wb_mode' if missing(x)
drop `wb_mode'
scalar wb_number_0 = _N
unab wb_columns: _all
scalar wb_check_1 = (`"`wb_columns'"' == "x")
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(4)) <= 0.0+0.0*abs(4)
assert wb_check_1 == 1

frame wb1: export delimited using "actual.csv", replace
