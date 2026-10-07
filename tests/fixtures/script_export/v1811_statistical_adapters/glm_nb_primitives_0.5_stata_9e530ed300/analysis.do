* Workbench 1.8.11
* project: glm_nb
* run: 0.5
* lineage_hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
* Coverage
* full | model.glm:negative_binomial | native | 
* restricted | model.glm:negative_binomial | native | 
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
glm ynb x1 x2 x3, family(nbinomial 0.5) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)
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
frame copy wb_src0 wb_model_data2
frame change wb_model_data2
glm ynb x1, family(nbinomial 0.5) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)
assert e(converged) == 1
estimates store wb_model2
generate long wb_sample_row = _n
generate byte wb_sample2 = e(sample)
* Standalone native inference probe; public postestimation admission is checked separately.
frame change wb_model_data1
estimates restore wb_model1
scalar wb_number_9 = e(V)[4,4]
scalar wb_number_10 = e(V)[4,1]
scalar wb_number_11 = e(V)[4,2]
scalar wb_number_12 = e(V)[4,3]
scalar wb_number_13 = e(V)[1,4]
scalar wb_number_14 = e(V)[1,1]
scalar wb_number_15 = e(V)[1,2]
scalar wb_number_16 = e(V)[1,3]
scalar wb_number_17 = e(V)[2,4]
scalar wb_number_18 = e(V)[2,1]
scalar wb_number_19 = e(V)[2,2]
scalar wb_number_20 = e(V)[2,3]
scalar wb_number_21 = e(V)[3,4]
scalar wb_number_22 = e(V)[3,1]
scalar wb_number_23 = e(V)[3,2]
scalar wb_number_24 = e(V)[3,3]
frame change wb_model_data1
estimates restore wb_model1
test (x1=0) (x2=0)
scalar wb_number_25 = r(chi2)
scalar wb_number_26 = r(p)
scalar wb_number_27 = r(df)
frame change wb_model_data1
estimates restore wb_model1
test (x1-x2=1)
scalar wb_number_28 = r(chi2)
scalar wb_number_29 = r(p)
scalar wb_number_30 = r(df)
frame change wb_model_data1
estimates restore wb_model1
lincom x1+2*x2-.5
scalar wb_number_31 = r(estimate)
scalar wb_number_32 = r(se)
scalar wb_number_33 = r(estimate)/r(se)
scalar wb_number_34 = r(p)
frame change wb_model_data1
estimates restore wb_model1
nlcom (_b[x1]/_b[x2])
matrix wb_pb=r(b)
matrix wb_pv=r(V)
scalar wb_number_35 = wb_pb[1,1]
scalar wb_number_36 = sqrt(wb_pv[1,1])
scalar wb_number_37 = wb_pb[1,1]/sqrt(wb_pv[1,1])
scalar wb_number_38 = 2*normal(-abs(wb_pb[1,1]/sqrt(wb_pv[1,1])))
frame change wb_model_data1
estimates restore wb_model1
lrtest wb_model1 wb_model2
scalar wb_number_39 = r(chi2)
scalar wb_number_40 = r(p)
scalar wb_number_41 = r(df)
frame change wb_model_data1
estimates restore wb_model1
scalar wb_pn=e(N)
margins, dydx(x1 x2)
matrix wb_pb=r(b)
matrix wb_pv=r(V)
scalar wb_number_42 = wb_pb[1,1]
scalar wb_number_43 = wb_pb[1,2]
scalar wb_number_44 = sqrt(wb_pv[1,1])
scalar wb_number_45 = sqrt(wb_pv[2,2])
scalar wb_number_46 = wb_pn
frame change wb_model_data1
estimates restore wb_model1
scalar wb_pn=e(N)
margins, dydx(x1 x2) atmeans
matrix wb_pb=r(b)
matrix wb_pv=r(V)
scalar wb_number_47 = wb_pb[1,1]
scalar wb_number_48 = wb_pb[1,2]
scalar wb_number_49 = sqrt(wb_pv[1,1])
scalar wb_number_50 = sqrt(wb_pv[2,2])
scalar wb_number_51 = wb_pn
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
file write wb_numbers %21.17g (wb_number_34) _n
file write wb_numbers %21.17g (wb_number_35) _n
file write wb_numbers %21.17g (wb_number_36) _n
file write wb_numbers %21.17g (wb_number_37) _n
file write wb_numbers %21.17g (wb_number_38) _n
file write wb_numbers %21.17g (wb_number_39) _n
file write wb_numbers %21.17g (wb_number_40) _n
file write wb_numbers %21.17g (wb_number_41) _n
file write wb_numbers %21.17g (wb_number_42) _n
file write wb_numbers %21.17g (wb_number_43) _n
file write wb_numbers %21.17g (wb_number_44) _n
file write wb_numbers %21.17g (wb_number_45) _n
file write wb_numbers %21.17g (wb_number_46) _n
file write wb_numbers %21.17g (wb_number_47) _n
file write wb_numbers %21.17g (wb_number_48) _n
file write wb_numbers %21.17g (wb_number_49) _n
file write wb_numbers %21.17g (wb_number_50) _n
file write wb_numbers %21.17g (wb_number_51) _n
file close wb_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(0.5294190766274965)) <= 1e-08+0*abs(0.5294190766274965)
assert !missing(wb_number_1) & abs(wb_number_1-(0.3808453229171612)) <= 1e-08+0*abs(0.3808453229171612)
assert !missing(wb_number_2) & abs(wb_number_2-(-0.29806517727677795)) <= 1e-08+0*abs(-0.29806517727677795)
assert !missing(wb_number_3) & abs(wb_number_3-(-0.10833250363412572)) <= 1e-08+0*abs(-0.10833250363412572)
assert !missing(wb_number_4) & abs(wb_number_4-(0.14028025583591924)) <= 1e-06+0*abs(0.14028025583591924)
assert !missing(wb_number_5) & abs(wb_number_5-(0.06283421954867592)) <= 1e-06+0*abs(0.06283421954867592)
assert !missing(wb_number_6) & abs(wb_number_6-(0.05471088883162485)) <= 1e-06+0*abs(0.05471088883162485)
assert !missing(wb_number_7) & abs(wb_number_7-(0.1217725004803211)) <= 1e-06+0*abs(0.1217725004803211)
assert !missing(wb_number_8) & abs(wb_number_8-(300)) <= 0.0+0.0*abs(300)
assert !missing(wb_number_9) & abs(wb_number_9-(0.019678550177390956)) <= 1e-08+1e-06*abs(0.019678550177390956)
assert !missing(wb_number_10) & abs(wb_number_10-(-0.00033393023438837733)) <= 1e-08+1e-06*abs(-0.00033393023438837733)
assert !missing(wb_number_11) & abs(wb_number_11-(0.00012168684550802438)) <= 1e-08+1e-06*abs(0.00012168684550802438)
assert !missing(wb_number_12) & abs(wb_number_12-(-0.015188215245293268)) <= 1e-08+1e-06*abs(-0.015188215245293268)
assert !missing(wb_number_13) & abs(wb_number_13-(-0.0003339302343883775)) <= 1e-08+1e-06*abs(-0.0003339302343883775)
assert !missing(wb_number_14) & abs(wb_number_14-(0.003948139146291206)) <= 1e-08+1e-06*abs(0.003948139146291206)
assert !missing(wb_number_15) & abs(wb_number_15-(-4.492202954898318e-05)) <= 1e-08+1e-06*abs(-4.492202954898318e-05)
assert !missing(wb_number_16) & abs(wb_number_16-(-0.0005450070641983157)) <= 1e-08+1e-06*abs(-0.0005450070641983157)
assert !missing(wb_number_17) & abs(wb_number_17-(0.00012168684550802437)) <= 1e-08+1e-06*abs(0.00012168684550802437)
assert !missing(wb_number_18) & abs(wb_number_18-(-4.492202954898328e-05)) <= 1e-08+1e-06*abs(-4.492202954898328e-05)
assert !missing(wb_number_19) & abs(wb_number_19-(0.0029932813567464128)) <= 1e-08+1e-06*abs(0.0029932813567464128)
assert !missing(wb_number_20) & abs(wb_number_20-(0.00035850408651598664)) <= 1e-08+1e-06*abs(0.00035850408651598664)
assert !missing(wb_number_21) & abs(wb_number_21-(-0.015188215245293268)) <= 1e-08+1e-06*abs(-0.015188215245293268)
assert !missing(wb_number_22) & abs(wb_number_22-(-0.0005450070641983158)) <= 1e-08+1e-06*abs(-0.0005450070641983158)
assert !missing(wb_number_23) & abs(wb_number_23-(0.0003585040865159866)) <= 1e-08+1e-06*abs(0.0003585040865159866)
assert !missing(wb_number_24) & abs(wb_number_24-(0.014828541873229802)) <= 1e-08+1e-06*abs(0.014828541873229802)
assert !missing(wb_number_25) & abs(wb_number_25-(65.56604799118558)) <= 0.0+1e-06*abs(65.56604799118558)
assert !missing(wb_number_26) & abs(wb_number_26-(5.787800841522105e-15)) <= 0.0+1e-05*abs(5.787800841522105e-15)
assert !missing(wb_number_27) & abs(wb_number_27-(2)) <= 0.0+0.0*abs(2)
assert !missing(wb_number_28) & abs(wb_number_28-(14.662862700531432)) <= 0.0+1e-06*abs(14.662862700531432)
assert !missing(wb_number_29) & abs(wb_number_29-(0.00012855435494768384)) <= 0.0+1e-05*abs(0.00012855435494768384)
assert !missing(wb_number_30) & abs(wb_number_30-(1)) <= 0.0+0.0*abs(1)
assert !missing(wb_number_31) & abs(wb_number_31-(-0.7152850316363947)) <= 0.0+1e-06*abs(-0.7152850316363947)
assert !missing(wb_number_32) & abs(wb_number_32-(0.1254654392854101)) <= 0.0+1e-06*abs(0.1254654392854101)
assert !missing(wb_number_33) & abs(wb_number_33-(-5.70105230340968)) <= 0.0+1e-06*abs(-5.70105230340968)
assert !missing(wb_number_34) & abs(wb_number_34-(1.1907009230017913e-08)) <= 0.0+1e-05*abs(1.1907009230017913e-08)
assert !missing(wb_number_35) & abs(wb_number_35-(-1.2777249808135591)) <= 0.0+1e-06*abs(-1.2777249808135591)
assert !missing(wb_number_36) & abs(wb_number_36-(0.3132924544398737)) <= 0.0+1e-06*abs(0.3132924544398737)
assert !missing(wb_number_37) & abs(wb_number_37-(-4.078377767182315)) <= 0.0+1e-06*abs(-4.078377767182315)
assert !missing(wb_number_38) & abs(wb_number_38-(4.535103510326398e-05)) <= 0.0+1e-05*abs(4.535103510326398e-05)
assert !missing(wb_number_39) & abs(wb_number_39-(32.091685454637286)) <= 0.0+1e-06*abs(32.091685454637286)
assert !missing(wb_number_40) & abs(wb_number_40-(1.074927184180779e-07)) <= 0.0+1e-05*abs(1.074927184180779e-07)
assert !missing(wb_number_41) & abs(wb_number_41-(2)) <= 0.0+0.0*abs(2)
assert !missing(wb_number_42) & abs(wb_number_42-(0.6563673408291717)) <= 0.0+1e-06*abs(0.6563673408291717)
assert !missing(wb_number_43) & abs(wb_number_43-(-0.5137000133439795)) <= 0.0+1e-06*abs(-0.5137000133439795)
assert !missing(wb_number_44) & abs(wb_number_44-(0.12335275178705468)) <= 0.0+1e-05*abs(0.12335275178705468)
assert !missing(wb_number_45) & abs(wb_number_45-(0.10472884520065841)) <= 0.0+1e-05*abs(0.10472884520065841)
assert !missing(wb_number_46) & abs(wb_number_46-(300)) <= 0.0+0.0*abs(300)
assert !missing(wb_number_47) & abs(wb_number_47-(0.5746074027696974)) <= 0.0+1e-06*abs(0.5746074027696974)
assert !missing(wb_number_48) & abs(wb_number_48-(-0.4497113310012097)) <= 0.0+1e-06*abs(-0.4497113310012097)
assert !missing(wb_number_49) & abs(wb_number_49-(0.09460541302509871)) <= 0.0+1e-05*abs(0.09460541302509871)
assert !missing(wb_number_50) & abs(wb_number_50-(0.08236970423645469)) <= 0.0+1e-05*abs(0.08236970423645469)
assert !missing(wb_number_51) & abs(wb_number_51-(300)) <= 0.0+0.0*abs(300)
