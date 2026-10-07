* Workbench 1.8.11
* project: weighted
* run: analysis_robust
* lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
* Coverage
* weighted | model.ols | native | 
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
regress y x z [aw=aw], vce(robust)
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
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_7 = (_b[_cons]/_se[_cons])
scalar wb_number_8 = 2*ttail(e(df_r),abs((_b[_cons]/_se[_cons])))
scalar wb_number_9 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_10 = (_b[x]/_se[x])
scalar wb_number_11 = 2*ttail(e(df_r),abs((_b[x]/_se[x])))
scalar wb_number_12 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_13 = (_b[z]/_se[z])
scalar wb_number_14 = 2*ttail(e(df_r),abs((_b[z]/_se[z])))
scalar wb_number_15 = e(df_r)
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
file close wb_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(1.085282749557345)) <= 1e-08+1e-06*abs(1.085282749557345)
assert !missing(wb_number_1) & abs(wb_number_1-(0.6071313851092202)) <= 1e-08+1e-06*abs(0.6071313851092202)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.2043614817840667)) <= 1e-08+1e-06*abs(-0.2043614817840667)
assert !missing(wb_number_3) & abs(wb_number_3-(0.05381710188201347)) <= 1e-08+1e-05*abs(0.05381710188201347)
assert !missing(wb_number_4) & abs(wb_number_4-(0.047990782329352236)) <= 1e-08+1e-05*abs(0.047990782329352236)
assert !missing(wb_number_5) & abs(wb_number_5-(0.05265012682205399)) <= 1e-08+1e-05*abs(0.05265012682205399)
assert !missing(wb_number_6) & abs(wb_number_6-(350)) <= 0.0+0.0*abs(350)
assert !missing(wb_number_7) & abs(wb_number_7-(20.166131426710358)) <= 1e-08+1e-05*abs(20.166131426710358)
assert !missing(wb_number_8) & abs(wb_number_8-(2.0907927325230813e-60)) <= 1e-06+0.0*abs(2.0907927325230813e-60)
assert !missing(wb_number_9) & abs(wb_number_9-(347.0)) <= 0.0+0.0*abs(347.0)
assert !missing(wb_number_10) & abs(wb_number_10-(12.650999955420295)) <= 1e-08+1e-05*abs(12.650999955420295)
assert !missing(wb_number_11) & abs(wb_number_11-(1.9970260538258507e-30)) <= 1e-06+0.0*abs(1.9970260538258507e-30)
assert !missing(wb_number_12) & abs(wb_number_12-(347.0)) <= 0.0+0.0*abs(347.0)
assert !missing(wb_number_13) & abs(wb_number_13-(-3.8815002758638015)) <= 1e-08+1e-05*abs(-3.8815002758638015)
assert !missing(wb_number_14) & abs(wb_number_14-(0.00012425511795765678)) <= 1e-06+0.0*abs(0.00012425511795765678)
assert !missing(wb_number_15) & abs(wb_number_15-(347.0)) <= 0.0+0.0*abs(347.0)
