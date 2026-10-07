# Workbench 1.8.11
# project: review
# run: string-mode
# lineage_hash: 4444444444444444444444444444444444444444444444444444444444444444
# Coverage
# result | data.fill_missing | native | 
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

data['source'] = wb_read('data.csv', '63e535a65fadff855bb41ade0b8986f125a13d6d593613819b184f60b13e12da', 'csv', {})
data['result'] = data['source'].copy()
data['result']['x'] = data['result']['x'].fillna(data['result']['x'].mode(dropna=True).iloc[0])
data['result'] = data['result'].reset_index(drop=True)
checks.append(float(len(data['result'])))
assert list(data['result'].columns) == ['x']
# Closing self-checks
wb_check(checks[0], 4, 0.0, 0.0, 'result:nrows')

data['result'].to_csv('actual.csv',index=False)
