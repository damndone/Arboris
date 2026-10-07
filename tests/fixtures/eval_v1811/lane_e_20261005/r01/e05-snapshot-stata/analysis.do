* Workbench 1.8.11
* project: snapshot
* run: 20261005_091814_542545_c0b3eebc
* lineage_hash: f7f9bba0dce2c1d99252e3b4b8bb19f639bb62ea8d99ef16d7ca32fb003c185e
* Coverage
* step_6485f17b68a0f4bdeb945eed | data.cleaning | native | 
* step_ba8d0be27e6993bae63a245d | model.negative_binomial | snapshot | Only estimated-dispersion NB2 is validated; NB1 and fixed-alpha inference require Workbench. Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.
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

wb_sha "source_c2e8eadde188587d9f35b7a9.csv" "c2e8eadde188587d9f35b7a9b05600ec8998a525e03774138b88e4553091909f"
frame create wb_src0
frame change wb_src0
import delimited using "source_c2e8eadde188587d9f35b7a9.csv", varnames(1) delimiters(",") encoding("UTF-8") bindquotes(strict) maxquotedrows(unlimited) asdouble clear case(preserve)
frame copy wb_src0 wb1
frame change wb1
scalar wb_number_0 = _N
unab wb_columns: _all
scalar wb_check_1 = (`"`wb_columns'"' == "y x1 x2")
* Workbench completed this step: negative_binomial (primary)
wb_sha "step_ba8d0be27e6993bae63a245d.csv" "150a72b0bfecc03f769f08980be7f04400bfc24a208b704d5f2b0bb30c2391ee"
frame create wb2
frame change wb2
import delimited using "step_ba8d0be27e6993bae63a245d.csv", varnames(1) delimiters(",") encoding("UTF-8") bindquotes(strict) maxquotedrows(unlimited) asdouble clear case(preserve)
scalar wb_number_2 = _N
unab wb_columns: _all
scalar wb_check_3 = (`"`wb_columns'"' == "y x1 x2")
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
shell python3 "`wb_result_bridge'" . eyJyZWZlcmVuY2UiOiB7ImZpbGVuYW1lIjogInN0ZXBfYmE4ZDBiZTI3ZTY5OTNiYWU2M2EyNDVkLmpzb24iLCAic2hhMjU2IjogIjk3Y2JjZjgyMDliN2I5YTc5YjExMmUzOWQwMjRmMDE5OTJjNDkyMjQ0MjUwNTQ2MmFjMjcxMTMzYTU4M2IwZTUiLCAic2NoZW1hX3ZlcnNpb24iOiAxfSwgImJpbmRpbmciOiB7InByb2plY3RfaWQiOiAic25hcHNob3QiLCAicnVuX2lkIjogIjIwMjYxMDA1XzA5MTgxNF81NDI1NDVfYzBiM2VlYmMiLCAibGluZWFnZV9oYXNoIjogImY3ZjliYmEwZGNlMmMxZDk5MjUyZTNiNGI4YmIxOWY2MzliYjYyZWE4ZDk5ZWYxNmQ3Y2EzMmZiMDAzYzE4NWUiLCAic3RlcF9pZCI6ICJzdGVwX2JhOGQwYmUyN2U2OTkzYmFlNjNhMjQ1ZCIsICJraW5kIjogIm1vZGVsIiwgIm9wZXJhdGlvbiI6ICJtb2RlbC5uZWdhdGl2ZV9iaW5vbWlhbCIsICJwYXJhbWV0ZXJzX3NoYTI1NiI6ICJjZGZiMDE5YzI0NTVkM2Q5Y2VkYWViNzY0MDY0MGY5YmRmMWE3ODViM2U0ZjQ1OGUzNTcyMWY3NmUxZTU4N2UxIiwgImlucHV0cyI6IFsic3RlcF82NDg1ZjE3YjY4YTBmNGJkZWI5NDVlZWQiXSwgIm1vZGVscyI6IFtdfSwgInF1ZXJpZXMiOiBbWyJub2JzIl0sIFsiY29lZmZpY2llbnRzIiwgIkludGVyY2VwdCJdLCBbImNvZWZmaWNpZW50cyIsICJ4MSJdLCBbImNvZWZmaWNpZW50cyIsICJ4MiJdLCBbInN0ZF9lcnJvcnMiLCAiSW50ZXJjZXB0Il0sIFsic3RkX2Vycm9ycyIsICJ4MSJdLCBbInN0ZF9lcnJvcnMiLCAieDIiXSwgWyJzdGF0aXN0aWNzIiwgIkludGVyY2VwdCIsICJ2YWx1ZSJdLCBbInN0YXRpc3RpY3MiLCAiSW50ZXJjZXB0IiwgInBfdmFsdWUiXSwgWyJzdGF0aXN0aWNzIiwgIngxIiwgInZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ4MSIsICJwX3ZhbHVlIl0sIFsic3RhdGlzdGljcyIsICJ4MiIsICJ2YWx1ZSJdLCBbInN0YXRpc3RpY3MiLCAieDIiLCAicF92YWx1ZSJdXSwgImRpc3RyaWJ1dGlvbnMiOiB7IkludGVyY2VwdCI6ICJ6IiwgIngxIjogInoiLCAieDIiOiAieiJ9LCAiaW5kZXgiOiAyfQ== stata "`wb_result_commands'"
confirm file "`wb_result_commands'"
do "`wb_result_commands'"
assert scalar(wb_result_valid_2) == 1
scalar wb_number_4 = scalar(wb_result_2_0)
scalar wb_number_5 = scalar(wb_result_2_1)
scalar wb_number_6 = scalar(wb_result_2_2)
scalar wb_number_7 = scalar(wb_result_2_3)
scalar wb_number_8 = scalar(wb_result_2_4)
scalar wb_number_9 = scalar(wb_result_2_5)
scalar wb_number_10 = scalar(wb_result_2_6)
scalar wb_number_11 = scalar(wb_result_2_7)
scalar wb_number_12 = scalar(wb_result_2_8)
scalar wb_number_13 = scalar(wb_result_2_9)
scalar wb_number_14 = scalar(wb_result_2_10)
scalar wb_number_15 = scalar(wb_result_2_11)
scalar wb_number_16 = scalar(wb_result_2_12)
file open wb_numbers using "numeric_actual.tsv", write text replace
file write wb_numbers %21.17g (wb_number_0) _n
file write wb_numbers %21.17g (wb_number_2) _n
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
file close wb_numbers
* Closing self-checks
assert !missing(wb_number_0) & abs(wb_number_0-(1000)) <= 0.0+0.0*abs(1000)
assert wb_check_1 == 1
assert !missing(wb_number_2) & abs(wb_number_2-(1000)) <= 0.0+0.0*abs(1000)
assert wb_check_3 == 1
assert !missing(wb_number_4) & abs(wb_number_4-(1000)) <= 0.0+0.0*abs(1000)
assert !missing(wb_number_5) & abs(wb_number_5-(0.41794987220602414)) <= 1e-08+1e-06*abs(0.41794987220602414)
assert !missing(wb_number_6) & abs(wb_number_6-(0.2972288232352733)) <= 1e-08+1e-06*abs(0.2972288232352733)
assert !missing(wb_number_7) & abs(wb_number_7-(-0.2544118335916357)) <= 1e-08+1e-06*abs(-0.2544118335916357)
assert !missing(wb_number_8) & abs(wb_number_8-(0.033988692547635736)) <= 1e-08+1e-05*abs(0.033988692547635736)
assert !missing(wb_number_9) & abs(wb_number_9-(0.031235162030611035)) <= 1e-08+1e-05*abs(0.031235162030611035)
assert !missing(wb_number_10) & abs(wb_number_10-(0.03237676639037322)) <= 1e-08+1e-05*abs(0.03237676639037322)
assert !missing(wb_number_11) & abs(wb_number_11-(12.296732850793251)) <= 1e-08+1e-05*abs(12.296732850793251)
assert !missing(wb_number_12) & abs(wb_number_12-(9.431229712147405e-35)) <= 1e-06+0.0*abs(9.431229712147405e-35)
assert !missing(wb_number_13) & abs(wb_number_13-(9.515840607581403)) <= 1e-08+1e-05*abs(9.515840607581403)
assert !missing(wb_number_14) & abs(wb_number_14-(1.8024962829839534e-21)) <= 1e-06+0.0*abs(1.8024962829839534e-21)
assert !missing(wb_number_15) & abs(wb_number_15-(-7.857851847344506)) <= 1e-08+1e-05*abs(-7.857851847344506)
assert !missing(wb_number_16) & abs(wb_number_16-(3.907771102641985e-15)) <= 1e-06+0.0*abs(3.907771102641985e-15)
