# Workbench 1.8.11
# project: review
# run: reader
# lineage_hash: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
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

data['source'] = wb_read('reader.csv', '253520e44c4003839663047f39812a4e6b9f84b8d74c97c27f75d4649a43ed1a', 'csv', {'sep': '|', 'encoding': 'latin1', 'header': 0})
data['result'] = data['source'].copy()
data['result'] = data['result'].loc[:, ['city', 'value']]
data['result'] = data['result'].reset_index(drop=True)
checks.append(float(len(data['result'])))
assert list(data['result'].columns) == ['city', 'value']
# Closing self-checks
wb_check(checks[0], 2, 0.0, 0.0, 'result:nrows')

data['result'].to_csv('actual.csv',index=False)
