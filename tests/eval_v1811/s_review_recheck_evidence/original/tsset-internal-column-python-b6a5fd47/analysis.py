# Workbench 1.8.11
# project: review
# run: tsset-internal-column
# lineage_hash: 4444444444444444444444444444444444444444444444444444444444444444
# Coverage
# result | data.tsset | native | 
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

data['source'] = wb_read('data.csv', '939eb0dbfb058ae46a294f9560682d2169e55d365d0a4255344bb1aba7a21853', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
data['result'] = data['source'].copy()
wb_time = pd.to_datetime(data['result']['time'], format="mixed", errors="raise")
wb_sort_keys = pd.DataFrame({**{i:data['result'][c] for i,c in enumerate([])}, 0:wb_time})
wb_order = wb_sort_keys.sort_values([0], kind="mergesort").index
data['result'] = data['result'].loc[wb_order].reset_index(drop=True)
checks.append(float(len(data['result'])))
assert list(data['result'].columns) == ['time', '__wb_time']
Path('numeric_actual.tsv').write_text('\n'.join(format(x,'.17g') for x in checks))
# Closing self-checks
wb_check(checks[0], 2, 0.0, 0.0, 'result:nrows')

data['result'].to_csv('actual.csv',index=False)
