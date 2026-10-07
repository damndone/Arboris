* Workbench 1.8.11
* project: invalid_fpc
* run: negative
* lineage_hash: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
* Coverage
* model | model.ols | native_with_equivalence_note | Full single-stage linearization design including supplied FPC and domain; coefficient and joint-test df preserve the executed Workbench convention.
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

wb_sha "data.csv" "eb6f090ecb52d6217185214e757e95f9bb0a15afa824b2913c8baa45b2058db5"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
frame copy wb_src0 wb_model_data1
frame change wb_model_data1
drop if missing(y) | missing(x1) | missing(x2)
assert !missing(population) & population >= 0
quietly summarize population, meanonly
scalar wb_fpc_fraction = (r(max)<=1)
if !wb_fpc_fraction assert population>1 & population==floor(population)
tempvar wb_fpc_order wb_fpc_stratum wb_fpc_psu wb_fpc_tag wb_fpc_n
generate long `wb_fpc_order' = _n
egen long `wb_fpc_stratum' = group(stratum)
egen long `wb_fpc_psu' = group(`wb_fpc_stratum' psu)
egen byte `wb_fpc_tag' = tag(`wb_fpc_stratum' `wb_fpc_psu')
bysort `wb_fpc_stratum': egen long `wb_fpc_n' = total(`wb_fpc_tag')
bysort `wb_fpc_stratum': assert population==population[1]
if !wb_fpc_fraction assert population>=`wb_fpc_n'
sort `wb_fpc_order'
svyset psu [pw=weight], strata(stratum) fpc(population) singleunit(missing)
svy: regress y x1 x2
assert e(df_r) > 0
matrix wb_survey_v = e(V)
mata: assert(!hasmissing(st_matrix("wb_survey_v")))
estimates store wb_model1
generate long wb_sample_row = _n
generate byte wb_sample1 = e(sample)
scalar wb_number_0 = e(N)
file open wb_numbers using "numeric_actual.tsv", write text replace
file write wb_numbers %21.17g (wb_number_0) _n
file close wb_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(80)) <= 0.0+0.0*abs(80)
