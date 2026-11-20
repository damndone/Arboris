#!/usr/bin/env python3
"""Compare arboris-engine's numbers with the product's recorded results, field by field.

    python3 -B scripts/compare_native_engine.py <ab-results root> [--binary path]
"""
import argparse
import json
import subprocess
from pathlib import Path

CASES = {
    'ols': ['ols', '--y', 'wage', '--x', 'education,experience,female,hours', '--cov', 'hc1'],
    'iv': ['iv', '--y', 'y', '--x', 'w', '--endog', 'd', '--instruments', 'z1,z2'],
    'panel': ['panel', '--y', 'y', '--x', 'x1,x2', '--entity', 'unit', '--time', 'year'],
}


def value(item):
    return float.fromhex(item['binary64']) if isinstance(item, dict) else item


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    parser.add_argument('--binary', default='local/native-engine/target/release/arboris-engine')
    args = parser.parse_args()
    report = {}
    for case, arguments in CASES.items():
        recorded = json.loads((args.evidence/case/'ab-results.json').read_text())['cases'][case]['raw']['B'][0]['numeric_signature']
        source = json.loads(Path(f'local/perf-inputs/{case}/source.json').read_text())['source']
        out = subprocess.run([args.binary, arguments[0], '--csv', source, *arguments[1:]], capture_output=True, text=True)
        if out.returncode:
            report[case] = {'error': out.stderr}
            print(case, 'ERROR', out.stderr)
            continue
        fit = json.loads(out.stdout)
        worst = {}
        rows = []
        for field, key in (('estimate', 'estimate'), ('std_error', 'std_error'), ('ci_lower', 'ci_lower'), ('ci_upper', 'ci_upper'), ('p_value', 'p_value')):
            largest = 0.0
            for index, term in enumerate(fit['terms']):
                if term not in recorded['coefficients']:
                    continue
                reference = value(recorded['coefficients'][term][key])
                mine = fit[field][index]
                relative = abs(mine-reference)/abs(reference) if reference else abs(mine)
                largest = max(largest, relative)
                rows.append((term, field, reference, mine))
            worst[field] = largest
        scalar = {name: abs(fit[name]-value(recorded[name]))/abs(value(recorded[name])) for name in ('r_squared', 'nobs') if recorded.get(name) is not None}
        report[case] = {'worst_relative_difference': worst, 'scalars': scalar, 'terms': fit['terms'], 'timing': fit['timing_seconds'], 'covariance': fit['covariance']}
        print(case, {k: f'{v:.2e}' for k, v in worst.items()}, {k: f'{v:.2e}' for k, v in scalar.items()}, fit['timing_seconds'])
    return report


if __name__ == '__main__':
    main()
