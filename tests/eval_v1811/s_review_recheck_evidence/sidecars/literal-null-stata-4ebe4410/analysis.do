* Workbench 1.8.11
* project: sidecar
* run: executed
* lineage_hash: ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
* Coverage
* completed | model.ols | snapshot | FPC is supplied, but the frozen Workbench linearization engine does not apply FPC; native FPC would change the executed covariance. Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.
* post | postestimation.wald | snapshot | Dependent post-estimation needs its own completed Workbench result sidecar; no fitted state is reconstructed. Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.
* selected | data.subset | native | 
* independent | model.ols | native | 
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

wb_sha "data.csv" "5f8d0cc66fc9efdfd08e6a06640ea410d58671fe93ac5cac2ad90d6aa68de937"
frame create wb_src0
frame change wb_src0
import delimited using "data.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
* Workbench completed this step: Sampling OLS completed in Workbench
wb_sha "completed.csv" "5f8d0cc66fc9efdfd08e6a06640ea410d58671fe93ac5cac2ad90d6aa68de937"
frame create wb1
frame change wb1
import delimited using "completed.csv", varnames(1) delimiters(",") encoding("UTF-8") asdouble clear case(preserve)
scalar wb_number_0 = _N
unab wb_columns: _all
scalar wb_check_1 = (`"`wb_columns'"' == "stratum psu y x1 x2 weight fpc subpop")
tempfile wb_result_bridge
tempname wb_result_writer
file open `wb_result_writer' using "`wb_result_bridge'", write text
file write `wb_result_writer' `"import base64"' _n
file write `wb_result_writer' `"import json"' _n
file write `wb_result_writer' `"import os"' _n
file write `wb_result_writer' `"from pathlib import Path"' _n
file write `wb_result_writer' `"import sys"' _n
file write `wb_result_writer' `"from workbench.contracts.common.envelope import thaw_json"' _n
file write `wb_result_writer' `"from workbench.script_export.result_snapshot import ResultSnapshotRef, read_result_snapshot"' _n
file write `wb_result_writer' `""' _n
file write `wb_result_writer' `"configuration = json.loads(base64.b64decode(sys.argv[2]))"' _n
file write `wb_result_writer' `"reference = ResultSnapshotRef(**configuration['reference'])"' _n
file write `wb_result_writer' `"values = read_result_snapshot(Path(sys.argv[1]), reference, expected_binding=configuration['binding'])"' _n
file write `wb_result_writer' `"for name, distribution in configuration['distributions'].items():"' _n
file write `wb_result_writer' `"    if values['statistics'][name]['distribution'] != distribution:"' _n
file write `wb_result_writer' `"        raise AssertionError('Result sidecar reference distribution differs')"' _n
file write `wb_result_writer' `"if sys.argv[3] == 'r':"' _n
file write `wb_result_writer' `"    print(json.dumps(thaw_json(values), ensure_ascii=False, allow_nan=False))"' _n
file write `wb_result_writer' `"elif sys.argv[3] == 'stata':"' _n
file write `wb_result_writer' `"    lines = []"' _n
file write `wb_result_writer' `"    for index, path in enumerate(configuration['queries']):"' _n
file write `wb_result_writer' `"        value = values"' _n
file write `wb_result_writer' `"        for key in path:"' _n
file write `wb_result_writer' `"            value = value[key]"' _n
file write `wb_result_writer' `"        if value is not None and type(value) not in (int, float):"' _n
file write `wb_result_writer' `"            raise AssertionError('Result sidecar query is not numeric')"' _n
file write `wb_result_writer' `"        token = '.' if value is None else repr(value)"' _n
file write `wb_result_writer' `"        lines.append('scalar wb_result_' + str(configuration['index']) + '_' + str(index) + ' = ' + token)"' _n
file write `wb_result_writer' `"    lines.append('scalar wb_result_valid_' + str(configuration['index']) + ' = 1')"' _n
file write `wb_result_writer' `"    fd = os.open(sys.argv[4], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)"' _n
file write `wb_result_writer' `"    with os.fdopen(fd, 'w', encoding='utf-8') as handle:"' _n
file write `wb_result_writer' `"        handle.write('\n'.join(lines) + '\n')"' _n
file write `wb_result_writer' `"else:"' _n
file write `wb_result_writer' `"    raise AssertionError('Unsupported result bridge mode')"' _n
file close `wb_result_writer'
tempfile wb_result_commands
shell python3 "`wb_result_bridge'" . eyJyZWZlcmVuY2UiOiB7ImZpbGVuYW1lIjogImNvbXBsZXRlZF9yZXN1bHQuanNvbiIsICJzaGEyNTYiOiAiMmViYjlhYjdmYWFkZGVmM2ExYTFjNGEzMDc0Zjg2MWUxZDUxYTBlYjgwMjBlNDU1ODQzMTJlMzZiMzEwMGQ1NCIsICJzY2hlbWFfdmVyc2lvbiI6IDF9LCAiYmluZGluZyI6IHsicHJvamVjdF9pZCI6ICJzaWRlY2FyIiwgInJ1bl9pZCI6ICJleGVjdXRlZCIsICJsaW5lYWdlX2hhc2giOiAiZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZiIsICJzdGVwX2lkIjogImNvbXBsZXRlZCIsICJraW5kIjogIm1vZGVsIiwgIm9wZXJhdGlvbiI6ICJtb2RlbC5vbHMiLCAicGFyYW1ldGVyc19zaGEyNTYiOiAiYWM1ZDZiMzc1YWRhOTIwYTBmM2MyZDI5NzFmM2I4ZTk5NTA0YWYwN2ExMjY0MTE1MjUwYzA1NDg0N2FiNmZiMiIsICJpbnB1dHMiOiBbInNvdXJjZSJdLCAibW9kZWxzIjogW119LCAicXVlcmllcyI6IFtbIm5vYnMiXSwgWyJjb2VmZmljaWVudHMiLCAiSW50ZXJjZXB0Il0sIFsiY29lZmZpY2llbnRzIiwgIngxIl0sIFsiY29lZmZpY2llbnRzIiwgIngyIl0sIFsic3RkX2Vycm9ycyIsICJJbnRlcmNlcHQiXSwgWyJzdGRfZXJyb3JzIiwgIngxIl0sIFsic3RkX2Vycm9ycyIsICJ4MiJdLCBbInN0YXRpc3RpY3MiLCAiSW50ZXJjZXB0IiwgInZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJJbnRlcmNlcHQiLCAiZGYiXSwgWyJzdGF0aXN0aWNzIiwgIkludGVyY2VwdCIsICJwX3ZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ4MSIsICJ2YWx1ZSJdLCBbInN0YXRpc3RpY3MiLCAieDEiLCAiZGYiXSwgWyJzdGF0aXN0aWNzIiwgIngxIiwgInBfdmFsdWUiXSwgWyJzdGF0aXN0aWNzIiwgIngyIiwgInZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ4MiIsICJkZiJdLCBbInN0YXRpc3RpY3MiLCAieDIiLCAicF92YWx1ZSJdXSwgImRpc3RyaWJ1dGlvbnMiOiB7IkludGVyY2VwdCI6ICJ0IiwgIngxIjogInQiLCAieDIiOiAidCJ9LCAiaW5kZXgiOiAxfQ== stata "`wb_result_commands'"
confirm file "`wb_result_commands'"
do "`wb_result_commands'"
assert scalar(wb_result_valid_1) == 1
scalar wb_number_2 = scalar(wb_result_1_0)
scalar wb_number_3 = scalar(wb_result_1_1)
scalar wb_number_4 = scalar(wb_result_1_2)
scalar wb_number_5 = scalar(wb_result_1_3)
scalar wb_number_6 = scalar(wb_result_1_4)
scalar wb_number_7 = scalar(wb_result_1_5)
scalar wb_number_8 = scalar(wb_result_1_6)
scalar wb_number_9 = scalar(wb_result_1_7)
scalar wb_number_10 = scalar(wb_result_1_8)
scalar wb_number_11 = scalar(wb_result_1_9)
scalar wb_number_12 = scalar(wb_result_1_10)
scalar wb_number_13 = scalar(wb_result_1_11)
scalar wb_number_14 = scalar(wb_result_1_12)
scalar wb_number_15 = scalar(wb_result_1_13)
scalar wb_number_16 = scalar(wb_result_1_14)
scalar wb_number_17 = scalar(wb_result_1_15)
* Workbench completed this step: Actual persisted design Wald
frame copy wb1 wb2
frame change wb2
tempfile wb_result_commands
shell python3 "`wb_result_bridge'" . eyJyZWZlcmVuY2UiOiB7ImZpbGVuYW1lIjogInBvc3RfcmVzdWx0Lmpzb24iLCAic2hhMjU2IjogIjA2NTg4Nzg2MTUxMGY5Yjg5MGQ1MzY2Mjk4M2M5MmQyNDlkMDA2YTJkOTg3NmNkMjgxZmRiODY2ZDlhOWE0Y2QiLCAic2NoZW1hX3ZlcnNpb24iOiAxfSwgImJpbmRpbmciOiB7InByb2plY3RfaWQiOiAic2lkZWNhciIsICJydW5faWQiOiAiZXhlY3V0ZWQiLCAibGluZWFnZV9oYXNoIjogImZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmZmYiLCAic3RlcF9pZCI6ICJwb3N0IiwgImtpbmQiOiAicG9zdGVzdGltYXRpb24iLCAib3BlcmF0aW9uIjogInBvc3Rlc3RpbWF0aW9uLndhbGQiLCAicGFyYW1ldGVyc19zaGEyNTYiOiAiZWFlMGMyYzIzNmQyNmRlMWQ2ZjQ4ZDk2MmNlZjU3N2UyMzYwOWJmZGFmNmFiZTJjMjQ5NWUzMGUxYjcyZjhjZSIsICJpbnB1dHMiOiBbImNvbXBsZXRlZCJdLCAibW9kZWxzIjogWyJjb21wbGV0ZWQiXX0sICJxdWVyaWVzIjogW1sic3RhdGlzdGljcyIsICJ0ZXN0IiwgInZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ0ZXN0IiwgImRmIl0sIFsic3RhdGlzdGljcyIsICJ0ZXN0IiwgImRmX2Rlbm9taW5hdG9yIl0sIFsic3RhdGlzdGljcyIsICJ0ZXN0IiwgInBfdmFsdWUiXV0sICJkaXN0cmlidXRpb25zIjogeyJ0ZXN0IjogIkYiLCAicHJvYmUiOiAiUmVjb3JkZWQgXCJjdXN0b21cIiAkSE9NRSBgdW5zYWZlYFxccGF0aFxucmVmZXJlbmNlIn0sICJpbmRleCI6IDJ9 stata "`wb_result_commands'"
confirm file "`wb_result_commands'"
do "`wb_result_commands'"
assert scalar(wb_result_valid_2) == 1
scalar wb_number_18 = scalar(wb_result_2_0)
scalar wb_number_19 = scalar(wb_result_2_1)
scalar wb_number_20 = scalar(wb_result_2_2)
scalar wb_number_21 = scalar(wb_result_2_3)
frame copy wb2 wb3
frame change wb3
keep y x1 x2
order y x1 x2
scalar wb_number_22 = _N
unab wb_columns: _all
scalar wb_check_23 = (`"`wb_columns'"' == "y x1 x2")
frame copy wb3 wb_model_data4
frame change wb_model_data4
regress y x1 x2
estimates store wb_model4
generate long wb_sample_row = _n
generate byte wb_sample4 = e(sample)
scalar wb_number_24 = _b[_cons]
scalar wb_number_25 = _b[x1]
scalar wb_number_26 = _b[x2]
scalar wb_number_27 = _se[_cons]
scalar wb_number_28 = _se[x1]
scalar wb_number_29 = _se[x2]
scalar wb_number_30 = e(N)
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(80)) <= 0.0+0.0*abs(80)
assert wb_check_1 == 1
assert !missing(wb_number_2) & abs(wb_number_2-(80)) <= 0.0+0.0*abs(80)
assert !missing(wb_number_3) & abs(wb_number_3-(4.652711573943123)) <= 1e-08+1e-06*abs(4.652711573943123)
assert !missing(wb_number_4) & abs(wb_number_4-(1.475820771771979)) <= 1e-08+1e-06*abs(1.475820771771979)
assert !missing(wb_number_5) & abs(wb_number_5-(-0.40404481777033774)) <= 1e-08+1e-06*abs(-0.40404481777033774)
assert !missing(wb_number_6) & abs(wb_number_6-(1.5955241455226616)) <= 1e-08+1e-05*abs(1.5955241455226616)
assert !missing(wb_number_7) & abs(wb_number_7-(0.17732404110690134)) <= 1e-08+1e-05*abs(0.17732404110690134)
assert !missing(wb_number_8) & abs(wb_number_8-(0.08888234469730581)) <= 1e-08+1e-05*abs(0.08888234469730581)
assert !missing(wb_number_9) & abs(wb_number_9-(2.9161022645752492)) <= 1e-08+1e-05*abs(2.9161022645752492)
assert !missing(wb_number_10) & abs(wb_number_10-(8)) <= 0.0+0.0*abs(8)
assert !missing(wb_number_11) & abs(wb_number_11-(0.019406798019796175)) <= 1e-06+0.0*abs(0.019406798019796175)
assert !missing(wb_number_12) & abs(wb_number_12-(8.322733694537604)) <= 1e-08+1e-05*abs(8.322733694537604)
assert !missing(wb_number_13) & abs(wb_number_13-(8)) <= 0.0+0.0*abs(8)
assert !missing(wb_number_14) & abs(wb_number_14-(3.2813378097179405e-05)) <= 1e-06+0.0*abs(3.2813378097179405e-05)
assert !missing(wb_number_15) & abs(wb_number_15-(-4.545838874371921)) <= 1e-08+1e-05*abs(-4.545838874371921)
assert !missing(wb_number_16) & abs(wb_number_16-(8)) <= 0.0+0.0*abs(8)
assert !missing(wb_number_17) & abs(wb_number_17-(0.0018846599328036571)) <= 1e-06+0.0*abs(0.0018846599328036571)
assert !missing(wb_number_18) & abs(wb_number_18-(88.6728244577567)) <= 1e-08+1e-05*abs(88.6728244577567)
assert !missing(wb_number_19) & abs(wb_number_19-(2)) <= 0.0+0.0*abs(2)
assert !missing(wb_number_20) & abs(wb_number_20-(7.0)) <= 0.0+0.0*abs(7.0)
assert !missing(wb_number_21) & abs(wb_number_21-(1.0669105752740756e-05)) <= 1e-06+0.0*abs(1.0669105752740756e-05)
assert !missing(wb_number_22) & abs(wb_number_22-(80)) <= 0.0+0.0*abs(80)
assert wb_check_23 == 1
assert !missing(wb_number_24) & abs(wb_number_24-(4.596321816357483)) <= 1e-08+1e-06*abs(4.596321816357483)
assert !missing(wb_number_25) & abs(wb_number_25-(1.497109631010229)) <= 1e-08+1e-06*abs(1.497109631010229)
assert !missing(wb_number_26) & abs(wb_number_26-(-0.4181990460548318)) <= 1e-08+1e-06*abs(-0.4181990460548318)
assert !missing(wb_number_27) & abs(wb_number_27-(0.6751924283923509)) <= 1e-08+1e-05*abs(0.6751924283923509)
assert !missing(wb_number_28) & abs(wb_number_28-(0.09246563897577949)) <= 1e-08+1e-05*abs(0.09246563897577949)
assert !missing(wb_number_29) & abs(wb_number_29-(0.08312412958648425)) <= 1e-08+1e-05*abs(0.08312412958648425)
assert !missing(wb_number_30) & abs(wb_number_30-(80)) <= 0.0+0.0*abs(80)
