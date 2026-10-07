# Workbench 1.8.11
# project: review
# run: selected-sheet
# lineage_hash: 6666666666666666666666666666666666666666666666666666666666666666
# Coverage
# result | data.subset | native | 
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

data['source'] = wb_read('data.xlsx', '556c1e00b493dbb8c32c5cee748dba23ee37f3ad860eaef9610c3c04715af8fc', 'xlsx', {'sheet_name': 'Chosen'})
data['result'] = data['source'].copy()
data['result'] = data['result'].loc[:, ['x']]
data['result'] = data['result'].reset_index(drop=True)
checks.append(float(len(data['result'])))
assert list(data['result'].columns) == ['x']
# Closing self-checks
wb_check(checks[0], 3, 0.0, 0.0, 'result:nrows')
