# Workbench 1.8.11
# project: snapshot
# run: 20261005_091814_542545_c0b3eebc
# lineage_hash: f7f9bba0dce2c1d99252e3b4b8bb19f639bb62ea8d99ef16d7ca32fb003c185e
# Coverage
# step_6485f17b68a0f4bdeb945eed | data.cleaning | native | 
# step_ba8d0be27e6993bae63a245d | model.negative_binomial | snapshot | Only estimated-dispersion NB2 is validated; NB1 and fixed-alpha inference require Workbench. Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.
import hashlib
import math
from pathlib import Path
import numpy as np
import pandas as pd

data = {}
results = {}
checks = []
base = Path(__file__).resolve().parent

def wb_read(name, digest, fmt, options=None):
    path = base / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise AssertionError('SHA256 mismatch: ' + name)
    readers = {'csv': pd.read_csv, 'dta': pd.read_stata, 'sav': pd.read_spss,
               'xlsx': pd.read_excel, 'parquet': pd.read_parquet}
    return readers[fmt](path, **(options or {}))

def wb_check(actual, expected, absolute, relative, label):
    if not math.isfinite(float(actual)) or abs(actual-expected) > absolute + relative*abs(expected):
        raise AssertionError(f'{label}: {actual!r} != {expected!r}')

data['source_462a6947c68c9e6cd1a5b9c6'] = wb_read('source_c2e8eadde188587d9f35b7a9.csv', 'c2e8eadde188587d9f35b7a9b05600ec8998a525e03774138b88e4553091909f', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
data['step_6485f17b68a0f4bdeb945eed'] = data['source_462a6947c68c9e6cd1a5b9c6'].copy()
checks.append(float(len(data['step_6485f17b68a0f4bdeb945eed'])))
assert list(data['step_6485f17b68a0f4bdeb945eed'].columns) == ['y', 'x1', 'x2']
# Workbench completed this step: negative_binomial (primary)
data['step_ba8d0be27e6993bae63a245d'] = wb_read('step_ba8d0be27e6993bae63a245d.csv', '150a72b0bfecc03f769f08980be7f04400bfc24a208b704d5f2b0bb30c2391ee', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
checks.append(float(len(data['step_ba8d0be27e6993bae63a245d'])))
assert list(data['step_ba8d0be27e6993bae63a245d'].columns) == ['y', 'x1', 'x2']
from workbench.script_export.result_snapshot import ResultSnapshotRef, read_result_snapshot
wb_result_values2 = read_result_snapshot(base,ResultSnapshotRef(**{'filename': 'step_ba8d0be27e6993bae63a245d.json', 'sha256': '97cbcf8209b7b9a79b112e39d024f01992c4922442505462ac271133a583b0e5', 'schema_version': 1}),expected_binding={'project_id': 'snapshot', 'run_id': '20261005_091814_542545_c0b3eebc', 'lineage_hash': 'f7f9bba0dce2c1d99252e3b4b8bb19f639bb62ea8d99ef16d7ca32fb003c185e', 'step_id': 'step_ba8d0be27e6993bae63a245d', 'kind': 'model', 'operation': 'model.negative_binomial', 'parameters_sha256': 'cdfb019c2455d3d9cedaeb7640640f9bdf1a785b3e4f458e35721f76e1e587e1', 'inputs': ['step_6485f17b68a0f4bdeb945eed'], 'models': []})
assert wb_result_values2["statistics"]['Intercept']["distribution"] == 'z'
assert wb_result_values2["statistics"]['x1']["distribution"] == 'z'
assert wb_result_values2["statistics"]['x2']["distribution"] == 'z'
checks.append(float(wb_result_values2['nobs']))
checks.append(float(wb_result_values2['coefficients']['Intercept']))
checks.append(float(wb_result_values2['coefficients']['x1']))
checks.append(float(wb_result_values2['coefficients']['x2']))
checks.append(float(wb_result_values2['std_errors']['Intercept']))
checks.append(float(wb_result_values2['std_errors']['x1']))
checks.append(float(wb_result_values2['std_errors']['x2']))
checks.append(float(wb_result_values2['statistics']['Intercept']['value']))
checks.append(float(wb_result_values2['statistics']['Intercept']['p_value']))
checks.append(float(wb_result_values2['statistics']['x1']['value']))
checks.append(float(wb_result_values2['statistics']['x1']['p_value']))
checks.append(float(wb_result_values2['statistics']['x2']['value']))
checks.append(float(wb_result_values2['statistics']['x2']['p_value']))
with open("numeric_actual.tsv","w") as wb_fh:
    wb_fh.write("\n".join(format(x,".17g") for x in checks))
# Closing self-checks
wb_check(checks[0], 1000, 0.0, 0.0, 'step_6485f17b68a0f4bdeb945eed:nrows')
wb_check(checks[1], 1000, 0.0, 0.0, 'step_ba8d0be27e6993bae63a245d:nrows')
wb_check(checks[2], 1000, 0.0, 0.0, 'step_ba8d0be27e6993bae63a245d:nobs')
wb_check(checks[3], 0.41794987220602414, 1e-08, 1e-06, 'step_ba8d0be27e6993bae63a245d:coefficients')
wb_check(checks[4], 0.2972288232352733, 1e-08, 1e-06, 'step_ba8d0be27e6993bae63a245d:coefficients')
wb_check(checks[5], -0.2544118335916357, 1e-08, 1e-06, 'step_ba8d0be27e6993bae63a245d:coefficients')
wb_check(checks[6], 0.033988692547635736, 1e-08, 1e-05, 'step_ba8d0be27e6993bae63a245d:std_errors')
wb_check(checks[7], 0.031235162030611035, 1e-08, 1e-05, 'step_ba8d0be27e6993bae63a245d:std_errors')
wb_check(checks[8], 0.03237676639037322, 1e-08, 1e-05, 'step_ba8d0be27e6993bae63a245d:std_errors')
wb_check(checks[9], 12.296732850793251, 1e-08, 1e-05, 'step_ba8d0be27e6993bae63a245d:statistics.value')
wb_check(checks[10], 9.431229712147405e-35, 1e-06, 0.0, 'step_ba8d0be27e6993bae63a245d:statistics.p_value')
wb_check(checks[11], 9.515840607581403, 1e-08, 1e-05, 'step_ba8d0be27e6993bae63a245d:statistics.value')
wb_check(checks[12], 1.8024962829839534e-21, 1e-06, 0.0, 'step_ba8d0be27e6993bae63a245d:statistics.p_value')
wb_check(checks[13], -7.857851847344506, 1e-08, 1e-05, 'step_ba8d0be27e6993bae63a245d:statistics.value')
wb_check(checks[14], 3.907771102641985e-15, 1e-06, 0.0, 'step_ba8d0be27e6993bae63a245d:statistics.p_value')
