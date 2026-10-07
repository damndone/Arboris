* Workbench 1.8.11
* project: glm_nb
* run: 1.0
* lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
* Coverage
* full | model.glm:negative_binomial | native | 
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

wb_sha "data.csv" "2e1b92f07632a8c88d047074f77cd6e5f9552b4f932f7d6ed2499161a0bf3084"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
glm ynb x1 x2 x3, family(nbinomial 1.0) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)
assert e(converged) == 1
estimates store wb_model1
generate long wb_sample_row = _n
generate byte wb_sample1 = e(sample)
scalar wb_number_0 = _b[_cons]
scalar wb_number_1 = _b[x1]
scalar wb_number_2 = _b[x2]
scalar wb_number_3 = _b[x3]
scalar wb_number_4 = _se[_cons]
scalar wb_number_5 = _se[x1]
scalar wb_number_6 = _se[x2]
scalar wb_number_7 = _se[x3]
scalar wb_number_8 = e(N)
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
file close wb_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(0.524033398275554)) <= 1e-08+0*abs(0.524033398275554)
assert !missing(wb_number_1) & abs(wb_number_1-(0.37889378683709035)) <= 1e-08+0*abs(0.37889378683709035)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.28894515154376593)) <= 1e-08+0*abs(-0.28894515154376593)
assert !missing(wb_number_3) & abs(wb_number_3-(-0.10121807811349151)) <= 1e-08+0*abs(-0.10121807811349151)
assert !missing(wb_number_4) & abs(wb_number_4-(0.16986251046239487)) <= 1e-06+0*abs(0.16986251046239487)
assert !missing(wb_number_5) & abs(wb_number_5-(0.07594663821229021)) <= 1e-06+0*abs(0.07594663821229021)
assert !missing(wb_number_6) & abs(wb_number_6-(0.06578041865981685)) <= 1e-06+0*abs(0.06578041865981685)
assert !missing(wb_number_7) & abs(wb_number_7-(0.14744903698769615)) <= 1e-06+0*abs(0.14744903698769615)
assert !missing(wb_number_8) & abs(wb_number_8-(300)) <= 0.0+0.0*abs(300)
