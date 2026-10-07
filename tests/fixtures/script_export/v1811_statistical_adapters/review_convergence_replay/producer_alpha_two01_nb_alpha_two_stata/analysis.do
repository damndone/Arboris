version 18
set more off
file open wbout using "wb_results.tsv", write replace
* Workbench 1.8.11
* project: independent
* run: alpha_two
* lineage_hash: eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
* Coverage
* model | model.glm:negative_binomial | native | 
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

wb_sha "data.csv" "9707e4d6dc11d72fc6240b79a8ba79c8fd884b4edfa237905c086cddded60101"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
glm y x1 x2, family(nbinomial 2.0) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)
assert e(converged) == 1
estimates store wb_model1
generate long wb_sample_row = _n
generate byte wb_sample1 = e(sample)
scalar wb_number_0 = _b[_cons]
scalar wb_number_1 = _b[x1]
scalar wb_number_2 = _b[x2]
scalar wb_number_3 = _se[_cons]
scalar wb_number_4 = _se[x1]
scalar wb_number_5 = _se[x2]
scalar wb_number_6 = e(N)
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(0.431862033963731)) <= 1e-08+0*abs(0.431862033963731)
assert !missing(wb_number_1) & abs(wb_number_1-(0.499237797659053)) <= 1e-08+0*abs(0.499237797659053)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.319131636821243)) <= 1e-08+0*abs(-0.319131636821243)
assert !missing(wb_number_3) & abs(wb_number_3-(0.108234874866925)) <= 1e-06+0*abs(0.108234874866925)
assert !missing(wb_number_4) & abs(wb_number_4-(0.11295797337987)) <= 1e-06+0*abs(0.11295797337987)
assert !missing(wb_number_5) & abs(wb_number_5-(0.0991705432200099)) <= 1e-06+0*abs(0.0991705432200099)
assert !missing(wb_number_6) & abs(wb_number_6-(240)) <= 0.0+0.0*abs(240)

file write wbout "v_1_1" _tab %21.15g (e(V)[3,3]) _n
file write wbout "v_1_2" _tab %21.15g (e(V)[3,1]) _n
file write wbout "v_1_3" _tab %21.15g (e(V)[3,2]) _n
file write wbout "v_2_1" _tab %21.15g (e(V)[1,3]) _n
file write wbout "v_2_2" _tab %21.15g (e(V)[1,1]) _n
file write wbout "v_2_3" _tab %21.15g (e(V)[1,2]) _n
file write wbout "v_3_1" _tab %21.15g (e(V)[2,3]) _n
file write wbout "v_3_2" _tab %21.15g (e(V)[2,1]) _n
file write wbout "v_3_3" _tab %21.15g (e(V)[2,2]) _n
file write wbout "ll" _tab %21.15g (e(ll)) _n
file close wbout
