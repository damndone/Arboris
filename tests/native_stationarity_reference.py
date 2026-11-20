from pathlib import Path
import csv
import shutil
import subprocess
from tempfile import TemporaryDirectory

import numpy as np


HERE = Path(__file__).resolve().parent / 'fixtures'
REGISTERED = HERE / 'agent_completion/time_series/input.csv'
STATA_APP = Path('/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp')
TOLERANCE = {'rtol': 2e-12, 'atol': 2e-12}
STATA_ADDON_TOLERANCE = {'rtol': 1e-7, 'atol': 1e-9}


def cases():
    registered = np.genfromtxt(REGISTERED, delimiter=',', names=True)['y']
    rng = np.random.default_rng(14712)
    stable = np.zeros(256)
    innovations = rng.standard_normal(len(stable))
    for i in range(1, len(stable)):
        stable[i] = 1.7 + .45 * stable[i - 1] + innovations[i]
    walk = np.cumsum(rng.standard_normal(403) + .03)
    return {
        'registered_gate': (registered, 4, 4),
        'stable_zero_lags': (stable, 0, 0),
        'random_walk': (walk, 12, 8),
        'maximum_lags': (stable, 20, 20),
        'minimum_residual_df': (stable[:20], 6, 3),
    }


def executable(name):
    if name == 'R':
        return shutil.which('Rscript')
    return (shutil.which('stata-mp') or shutil.which('stata-se') or shutil.which('stata')
            or (str(STATA_APP) if STATA_APP.is_file() else None))


def csv_result(text):
    row = next(csv.DictReader(text.splitlines()))
    return {key: None if value.strip() == '.' else float(value) for key, value in row.items()}


def reference(runtime, values, adf_lag, kpss_lag):
    binary = executable(runtime)
    if binary is None:
        raise RuntimeError(f'{runtime} is required for this independent oracle')
    with TemporaryDirectory() as folder:
        path = Path(folder) / 'input.csv'
        np.savetxt(path, np.column_stack((np.arange(len(values)), values)),
                   delimiter=',', header='time,y', comments='', fmt=('%d', '%.17g'))
        lags = [str(adf_lag), str(kpss_lag)]
        if runtime == 'R':
            output = subprocess.check_output([binary, '--vanilla', str(HERE / 'stationarity.R'), str(path), *lags],
                                             text=True, cwd=folder, timeout=30)
        else:
            result = Path(folder) / 'output.csv'
            subprocess.run([binary, '-bq', 'do', str(HERE / 'stationarity.do'), path.name, *lags, result.name],
                           check=True, cwd=folder, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if not result.is_file():
                raise RuntimeError('Stata did not produce the expected stationarity reference CSV')
            output = result.read_text()
    return csv_result(output)
