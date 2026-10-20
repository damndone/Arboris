"""Explicit AR-only timing on a fixed perf_1m IV source; one path per process.

Usage: PYTHONPATH=backend .venv/bin/python scripts/perf_ar_verified.py
       SOURCE_MANIFEST verified_numpy|exact_fallback OUTPUT_JSON
CSV parsing and digest validation are excluded from algorithm timing. This is
not an alternating version A/B performance acceptance or a coverage experiment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import pandas as pd

from workbench.checks import ar_confidence, ar_verified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('path', choices=['verified_numpy', 'exact_fallback'])
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        raise FileExistsError('Preserve previous evidence; use a fresh output')
    payload = json.loads(args.manifest.read_text())
    with Path(payload['source']).open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != payload['sha256']:
        raise ValueError('source_digest_mismatch')
    frame = pd.read_csv(payload['source'])
    y, x, z = frame.y.to_numpy(), frame[['d']].to_numpy(), frame[['z1', 'z2']].to_numpy()
    w = np.column_stack([np.ones(len(frame)), frame.w])
    if args.path == 'exact_fallback':
        def forced(*_):
            raise ar_verified.VerificationUncertain('timing_forced_exact_original_input')
        ar_verified.verified_set = forced
    started = time.perf_counter()
    result = ar_confidence.robust_set(y, x, z, w)
    elapsed = time.perf_counter()-started
    report = dict(path_requested=args.path, source_sha256=digest, rows=len(frame),
                  seconds=elapsed, ru_maxrss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  result=result)
    args.destination.write_text(json.dumps(report, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != 'result'} |
                     dict(path_actual=result.get('computation'), kind=result['kind'])), flush=True)


if __name__ == '__main__':
    main()
