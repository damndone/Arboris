* Workbench 1.8.11
* project: model-oracle
* run: glm_poisson
* lineage_hash: 1111111111111111111111111111111111111111111111111111111111111111
* Coverage
* model | model.glm | native | 
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
poisson count x z, iterate(100) tolerance(1e-12)
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
scalar wb_number_7 = (_b[_cons]/_se[_cons])
scalar wb_number_8 = 2*normal(-abs((_b[_cons]/_se[_cons])))
scalar wb_number_9 = (_b[x]/_se[x])
scalar wb_number_10 = 2*normal(-abs((_b[x]/_se[x])))
scalar wb_number_11 = (_b[z]/_se[z])
scalar wb_number_12 = 2*normal(-abs((_b[z]/_se[z])))
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
file close wb_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(0.10396571524991229)) <= 1e-08+1e-06*abs(0.10396571524991229)
assert !missing(wb_number_1) & abs(wb_number_1-(0.37818762298179404)) <= 1e-08+1e-06*abs(0.37818762298179404)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.22000781353014975)) <= 1e-08+1e-06*abs(-0.22000781353014975)
assert !missing(wb_number_3) & abs(wb_number_3-(0.05268928385125403)) <= 1e-08+1e-05*abs(0.05268928385125403)
assert !missing(wb_number_4) & abs(wb_number_4-(0.04757957492734309)) <= 1e-08+1e-05*abs(0.04757957492734309)
assert !missing(wb_number_5) & abs(wb_number_5-(0.05226849883001865)) <= 1e-08+1e-05*abs(0.05226849883001865)
assert !missing(wb_number_6) & abs(wb_number_6-(350)) <= 0.0+0.0*abs(350)
assert !missing(wb_number_7) & abs(wb_number_7-(1.9731852029611112)) <= 1e-08+1e-05*abs(1.9731852029611112)
assert !missing(wb_number_8) & abs(wb_number_8-(0.04847446569865196)) <= 1e-06+0.0*abs(0.04847446569865196)
assert !missing(wb_number_9) & abs(wb_number_9-(7.948528829005084)) <= 1e-08+1e-05*abs(7.948528829005084)
assert !missing(wb_number_10) & abs(wb_number_10-(1.887394208540221e-15)) <= 1e-06+0.0*abs(1.887394208540221e-15)
assert !missing(wb_number_11) & abs(wb_number_11-(-4.209185617624734)) <= 1e-08+1e-05*abs(-4.209185617624734)
assert !missing(wb_number_12) & abs(wb_number_12-(2.5629277905377592e-05)) <= 1e-06+0.0*abs(2.5629277905377592e-05)
