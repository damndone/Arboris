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

data['source'] = wb_read('data.csv', 'c0b9eab6554440bf829db8d2a7e0bb922352249957519be22969c498c6b0dc93', 'csv', {'sep': ',', 'encoding': 'utf-8', 'header': 0})
data['result'] = data['source'].copy()
data['result']['x'] = data['result']['x'].fillna(data['result']['x'].mode(dropna=True).iloc[0])
data['result'] = data['result'].reset_index(drop=True)
checks.append(float(len(data['result'])))
assert list(data['result'].columns) == ['id', 'x']
Path('numeric_actual.tsv').write_text('\n'.join(format(x,'.17g') for x in checks))
# Closing self-checks
wb_check(checks[0], 4, 0.0, 0.0, 'result:nrows')

data['result'].to_csv('actual.csv',index=False)
