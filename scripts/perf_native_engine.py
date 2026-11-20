#!/usr/bin/env python3
"""A/B of one fit, same input and same arithmetic: Python libraries against arboris-engine.

Fresh process per run, nothing else in it. Five baseline calibrations, then five alternating
pairs; every observation is kept. The full product does more than this fit, and its time is
reported beside these numbers only as context.

    .venv/bin/python -B scripts/perf_native_engine.py --out local/perf-evidence/<fresh dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

BINARY = 'local/native-engine/target/release/arboris-engine'
PYTHON_FITS = {
    'ols': """
import pandas as pd, statsmodels.formula.api as smf
frame = pd.read_csv({path!r})
fit = smf.ols('wage ~ education + experience + female + hours', data=frame).fit().get_robustcov_results('HC1')
print(fit.params.tolist(), fit.bse.tolist())
""",
    'iv': """
import pandas as pd
from linearmodels.iv import IV2SLS
frame = pd.read_csv({path!r})
fit = IV2SLS.from_formula('y ~ 1 + w + [d ~ z1 + z2]', frame).fit(cov_type='robust')
print(fit.params.tolist(), fit.std_errors.tolist())
""",
    'panel': """
import pandas as pd
from linearmodels.panel import PanelOLS
frame = pd.read_csv({path!r}).set_index(['unit', 'year'])
fit = PanelOLS.from_formula('y ~ 1 + x1 + x2 + EntityEffects + TimeEffects', frame).fit(cov_type='clustered', cluster_entity=True)
print(fit.params.tolist(), fit.std_errors.tolist())
""",
}
ENGINE_ARGS = {
    'ols': ['ols', '--y', 'wage', '--x', 'education,experience,female,hours', '--cov', 'hc1'],
    'iv': ['iv', '--y', 'y', '--x', 'w', '--endog', 'd', '--instruments', 'z1,z2'],
    'panel': ['panel', '--y', 'y', '--x', 'x1,x2', '--entity', 'unit', '--time', 'year'],
}


def measure(command):
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _, status, usage = os.wait4(process.pid, 0)
    elapsed = time.perf_counter()-started
    if status != 0:
        raise SystemExit(f'failed: {command[:3]} {process.stderr.read()[-400:]!r}')
    return {'seconds': elapsed, 'rss_bytes': usage.ru_maxrss, 'cpu_seconds': usage.ru_utime+usage.ru_stime}


def noise(values):
    return statistics.stdev(values)/statistics.median(values)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if shutil.disk_usage('.').free < 5*2**30:
        raise SystemExit('below the 5 GB floor; not starting')
    args.out.mkdir(parents=True, exist_ok=False)
    report = {'binary_bytes': Path(BINARY).stat().st_size,
              'binary_sha256': hashlib.sha256(Path(BINARY).read_bytes()).hexdigest(),
              'cold_start': {}, 'cases': {}, 'python': sys.version.split()[0]}
    start_a = [measure([sys.executable, '-c', 'import pandas, statsmodels.api, linearmodels']) for _ in range(5)]
    report['cold_start']['python_libraries'] = start_a
    for case, arguments in ENGINE_ARGS.items():
        manifest = json.loads(Path(f'local/perf-inputs/{case}/source.json').read_text())
        path = manifest['source']
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == manifest['sha256']
        command_a = [sys.executable, '-c', PYTHON_FITS[case].format(path=path)]
        command_b = [BINARY, arguments[0], '--csv', path, *arguments[1:]]
        calibration = [measure(command_a) for _ in range(5)]
        pairs_a, pairs_b = [], []
        for _ in range(5):
            pairs_a.append(measure(command_a))
            pairs_b.append(measure(command_b))
        row = {'input_sha256': manifest['sha256'], 'calibration_a': calibration, 'a': pairs_a, 'b': pairs_b,
               'noise_a': noise([item['seconds'] for item in calibration+pairs_a]), 'noise_b': noise([item['seconds'] for item in pairs_b])}
        for lane, runs in (('a', pairs_a), ('b', pairs_b)):
            row[f'median_{lane}'] = {key: statistics.median(item[key] for item in runs) for key in ('seconds', 'rss_bytes', 'cpu_seconds')}
        report['cases'][case] = row
        print(case, f"python {row['median_a']['seconds']:.3f}s {row['median_a']['rss_bytes']/2**20:.0f}MiB  engine {row['median_b']['seconds']:.3f}s "
              f"{row['median_b']['rss_bytes']/2**20:.0f}MiB  {row['median_a']['seconds']/row['median_b']['seconds']:.0f}x  noise {row['noise_a']:.3f}/{row['noise_b']:.3f}", flush=True)
    (args.out/'report.json').write_text(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
