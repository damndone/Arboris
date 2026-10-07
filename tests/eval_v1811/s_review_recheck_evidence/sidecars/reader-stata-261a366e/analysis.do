* Workbench 1.8.11
* project: review
* run: reader
* lineage_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
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

wb_sha "reader.csv" "253520e44c4003839663047f39812a4e6b9f84b8d74c97c27f75d4649a43ed1a"
frame create wb_src0
frame change wb_src0
import delimited using "reader.csv", varnames(1) delimiters("|") encoding("ISO-8859-1") asdouble clear case(preserve)
frame copy wb_src0 wb1
frame change wb1
keep city value
order city value
scalar wb_number_0 = _N
unab wb_columns: _all
scalar wb_check_1 = (`"`wb_columns'"' == "city value")
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(2)) <= 0.0+0.0*abs(2)
assert wb_check_1 == 1

frame wb1: export delimited using "actual.csv", replace
