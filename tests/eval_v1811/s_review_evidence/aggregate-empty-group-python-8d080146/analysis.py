# Workbench 1.8.11
# project: review
# run: aggregate-empty-group
# lineage_hash: 4444444444444444444444444444444444444444444444444444444444444444
# Coverage
# result | data.aggregate | native | 
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

data['source'] = wb_read('data.csv', '1609211b4fec4d01adf93da8d4bfbdaae21706bb8256859bb6c6da400fcc5c14', 'csv', {})
data['result'] = data['source'].copy()
data['result'] = data['result'].groupby(['group'], dropna=False, sort=False).agg(minimum=pd.NamedAgg(column='x', aggfunc='min'), maximum=pd.NamedAgg(column='x', aggfunc='max')).reset_index()
checks.append(float(len(data['result'])))
assert list(data['result'].columns) == ['group', 'minimum', 'maximum']
Path('numeric_actual.tsv').write_text('\n'.join(format(x,'.17g') for x in checks))
# Closing self-checks
wb_check(checks[0], 2, 0.0, 0.0, 'result:nrows')

data['result'].to_csv('actual.csv',index=False)
