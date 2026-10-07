* Workbench 1.8.11
* project: review
* run: selected-sheet
* lineage_hash: 6666666666666666666666666666666666666666666666666666666666666666
* Coverage
* result | data.subset | native | 
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

wb_sha "data.xlsx" "556c1e00b493dbb8c32c5cee748dba23ee37f3ad860eaef9610c3c04715af8fc"
frame create wb_src0
frame change wb_src0
import excel using "data.xlsx", firstrow clear sheet("Chosen")
frame copy wb_src0 wb1
frame change wb1
keep x
order x
scalar wb_number_0 = _N
unab wb_columns: _all
scalar wb_check_1 = (`"`wb_columns'"' == "x")
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(3)) <= 0.0+0.0*abs(3)
assert wb_check_1 == 1
