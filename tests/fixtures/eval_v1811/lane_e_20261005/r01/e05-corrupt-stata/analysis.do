* Workbench 1.8.11
* project: script
* run: 20261005_091811_675151_95c6f12b
* lineage_hash: 44cdd1794406cf58e7845d729b4a21bf1c8ddacba382ef059f60da06f836b26d
* Coverage
* step_76b2427e32344554a37924aa | data.cleaning | native | 
* step_eca26cfbad39adff69c00721 | data.subset | native | 
* step_226b4b10776b3612293e8e34 | data.feature_recipe | native | 
* step_5bb28f6498e4698e7347d1d5 | data.cleaning | native | 
* step_59722572b3c11a55aa32ba09 | model.ols | native | 
* step_522468aadb113d7b603dca9b | postestimation.wald | native | 
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

wb_sha "source_1ce21051b81091ccc6d9f8b2.dta" "1ce21051b81091ccc6d9f8b22102b1560bc1b11924f2076b1e94db0b3b002e2f"
frame create wb_src0
frame change wb_src0
use "source_1ce21051b81091ccc6d9f8b2.dta", clear
frame copy wb_src0 wb1
frame change wb1
scalar wb_number_0 = _N
unab wb_columns: _all
scalar wb_check_1 = (`"`wb_columns'"' == "g x z keep y")
frame copy wb1 wb2
frame change wb2
keep if (!missing(keep) & (keep == 1))
keep g x z keep y
order g x z keep y
scalar wb_number_2 = _N
unab wb_columns: _all
scalar wb_check_3 = (`"`wb_columns'"' == "g x z keep y")
frame copy wb2 wb3
frame change wb3
confirm numeric variable x
confirm numeric variable z
generate double xz = (x * z)
scalar wb_number_4 = _N
unab wb_columns: _all
scalar wb_check_5 = (`"`wb_columns'"' == "g x z keep y xz")
frame copy wb3 wb4
frame change wb4
scalar wb_number_6 = _N
unab wb_columns: _all
scalar wb_check_7 = (`"`wb_columns'"' == "g x z keep y xz")
frame copy wb4 wb_model_data5
frame change wb_model_data5
regress y x z xz, vce(cluster g)
estimates store wb_model5
generate long wb_sample_row = _n
generate byte wb_sample5 = e(sample)
scalar wb_number_8 = _b[_cons]
scalar wb_number_9 = _b[x]
scalar wb_number_10 = _b[z]
scalar wb_number_11 = _b[xz]
scalar wb_number_12 = _se[_cons]
scalar wb_number_13 = _se[x]
scalar wb_number_14 = _se[z]
scalar wb_number_15 = _se[xz]
scalar wb_number_16 = e(N)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_17 = (_b[_cons]/_se[_cons])
scalar wb_number_18 = 2*ttail(e(df_r),abs((_b[_cons]/_se[_cons])))
scalar wb_number_19 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_20 = (_b[x]/_se[x])
scalar wb_number_21 = 2*ttail(e(df_r),abs((_b[x]/_se[x])))
scalar wb_number_22 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_23 = (_b[z]/_se[z])
scalar wb_number_24 = 2*ttail(e(df_r),abs((_b[z]/_se[z])))
scalar wb_number_25 = e(df_r)
capture confirm scalar e(df_r)
if _rc exit 9
scalar wb_number_26 = (_b[xz]/_se[xz])
scalar wb_number_27 = 2*ttail(e(df_r),abs((_b[xz]/_se[xz])))
scalar wb_number_28 = e(df_r)
frame change wb_model_data5
estimates restore wb_model5
test ((1.0*_b[x]) = 0.0) ((1.0*_b[xz]) = 0.0)
scalar wb_number_29 = e(N)
scalar wb_number_30 = r(F)
scalar wb_number_31 = r(p)
scalar wb_number_32 = r(df)
scalar wb_number_33 = r(df_r)
file open wb_numbers using "numeric_actual.tsv", write text replace
file write wb_numbers %21.17g (wb_number_0) _n
file write wb_numbers %21.17g (wb_number_2) _n
file write wb_numbers %21.17g (wb_number_4) _n
file write wb_numbers %21.17g (wb_number_6) _n
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
file write wb_numbers %21.17g (wb_number_18) _n
file write wb_numbers %21.17g (wb_number_19) _n
file write wb_numbers %21.17g (wb_number_20) _n
file write wb_numbers %21.17g (wb_number_21) _n
file write wb_numbers %21.17g (wb_number_22) _n
file write wb_numbers %21.17g (wb_number_23) _n
file write wb_numbers %21.17g (wb_number_24) _n
file write wb_numbers %21.17g (wb_number_25) _n
file write wb_numbers %21.17g (wb_number_26) _n
file write wb_numbers %21.17g (wb_number_27) _n
file write wb_numbers %21.17g (wb_number_28) _n
file write wb_numbers %21.17g (wb_number_29) _n
file write wb_numbers %21.17g (wb_number_30) _n
file write wb_numbers %21.17g (wb_number_31) _n
file write wb_numbers %21.17g (wb_number_32) _n
file write wb_numbers %21.17g (wb_number_33) _n
file close wb_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(640)) <= 0.0+0.0*abs(640)
assert wb_check_1 == 1
assert !missing(wb_number_2) & abs(wb_number_2-(320)) <= 0.0+0.0*abs(320)
assert wb_check_3 == 1
assert !missing(wb_number_4) & abs(wb_number_4-(320)) <= 0.0+0.0*abs(320)
assert wb_check_5 == 1
assert !missing(wb_number_6) & abs(wb_number_6-(320)) <= 0.0+0.0*abs(320)
assert wb_check_7 == 1
assert !missing(wb_number_8) & abs(wb_number_8-(0.9675178036793878)) <= 1e-08+1e-06*abs(0.9675178036793878)
assert !missing(wb_number_9) & abs(wb_number_9-(0.587233907457428)) <= 1e-08+1e-06*abs(0.587233907457428)
assert !missing(wb_number_10) & abs(wb_number_10-(-0.1324647468019746)) <= 1e-08+1e-06*abs(-0.1324647468019746)
assert !missing(wb_number_11) & abs(wb_number_11-(0.2877185211968429)) <= 1e-08+1e-06*abs(0.2877185211968429)
assert !missing(wb_number_12) & abs(wb_number_12-(0.06938744595036184)) <= 1e-08+1e-05*abs(0.06938744595036184)
assert !missing(wb_number_13) & abs(wb_number_13-(0.05939583283342683)) <= 1e-08+1e-05*abs(0.05939583283342683)
assert !missing(wb_number_14) & abs(wb_number_14-(0.05576371929506281)) <= 1e-08+1e-05*abs(0.05576371929506281)
assert !missing(wb_number_15) & abs(wb_number_15-(0.060837730532374686)) <= 1e-08+1e-05*abs(0.060837730532374686)
assert !missing(wb_number_16) & abs(wb_number_16-(320)) <= 0.0+0.0*abs(320)
assert !missing(wb_number_17) & abs(wb_number_17-(13.943701060441503)) <= 1e-08+1e-05*abs(13.943701060441503)
assert !missing(wb_number_18) & abs(wb_number_18-(1.974202786152289e-11)) <= 1e-06+0.0*abs(1.974202786152289e-11)
assert !missing(wb_number_19) & abs(wb_number_19-(19.0)) <= 0.0+0.0*abs(19.0)
assert !missing(wb_number_20) & abs(wb_number_20-(9.886786318903908)) <= 1e-08+1e-05*abs(9.886786318903908)
assert !missing(wb_number_21) & abs(wb_number_21-(6.320519792921724e-09)) <= 1e-06+0.0*abs(6.320519792921724e-09)
assert !missing(wb_number_22) & abs(wb_number_22-(19.0)) <= 0.0+0.0*abs(19.0)
assert !missing(wb_number_23) & abs(wb_number_23-(-2.375464701360096)) <= 1e-08+1e-05*abs(-2.375464701360096)
assert !missing(wb_number_24) & abs(wb_number_24-(0.028205935498091514)) <= 1e-06+0.0*abs(0.028205935498091514)
assert !missing(wb_number_25) & abs(wb_number_25-(19.0)) <= 0.0+0.0*abs(19.0)
assert !missing(wb_number_26) & abs(wb_number_26-(4.729277681450231)) <= 1e-08+1e-05*abs(4.729277681450231)
assert !missing(wb_number_27) & abs(wb_number_27-(0.00014595711024510102)) <= 1e-06+0.0*abs(0.00014595711024510102)
assert !missing(wb_number_28) & abs(wb_number_28-(19.0)) <= 0.0+0.0*abs(19.0)
assert !missing(wb_number_29) & abs(wb_number_29-(320)) <= 0.0+0.0*abs(320)
assert !missing(wb_number_30) & abs(wb_number_30-(69.64771978987594)) <= 1e-08+1e-05*abs(69.64771978987594)
assert !missing(wb_number_31) & abs(wb_number_31-(1.7914693344639517e-09)) <= 1e-06+0.0*abs(1.7914693344639517e-09)
assert !missing(wb_number_32) & abs(wb_number_32-(2)) <= 0.0+0.0*abs(2)
assert !missing(wb_number_33) & abs(wb_number_33-(19.0)) <= 0.0+0.0*abs(19.0)
