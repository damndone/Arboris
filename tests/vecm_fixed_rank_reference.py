from pathlib import Path
import json
import shutil
import subprocess

import numpy as np
from scipy.linalg import qr, solve_triangular


ROOT = Path(__file__).resolve().parent
ORACLE = ROOT / 'fixtures' / 'vecm_fixed_rank_oracle.R'
TOLERANCE = {'rtol': 2e-12, 'atol': 2e-12}


def fixture(seed):
    rng = np.random.default_rng(seed)
    innovations = rng.multivariate_normal(np.zeros(2), [[.8, .32], [.32, 1.2]], 370)
    values = np.zeros_like(innovations)
    for time in range(2, len(values)):
        error_correction = values[time - 1] @ np.array([1, -.65]) - 1.2
        difference = values[time - 1] - values[time - 2]
        values[time] = (values[time - 1] + np.array([-.24, .17]) * error_correction
                        + np.array([[.25, .08], [-.1, .28]]) @ difference + innovations[time])
    return values[50:]


def paired_matrices(training, lag_differences):
    delta = np.diff(training, axis=0)
    n_fit = len(delta) - lag_differences
    current = delta[lag_differences:]
    level = np.column_stack((training[lag_differences:-1], np.ones(n_fit)))
    lagged = np.concatenate([delta[lag_differences - lag:len(delta) - lag]
                             for lag in range(1, lag_differences + 1)], axis=1)
    return current, level, lagged


def factor(matrix):
    orthogonal, triangular, permutation = qr(matrix, mode='economic', pivoting=True)
    diagonal = np.abs(np.diag(triangular))
    if diagonal.min() <= np.finfo(float).eps * max(matrix.shape) * diagonal.max():
        raise ValueError('rank-deficient Johansen regression block')
    return orthogonal, triangular, permutation


def unpivoted_solve(triangular, permutation, target):
    solution = np.empty_like(target)
    solution[permutation] = solve_triangular(triangular, target)
    return solution


def estimate(training, lag_differences):
    scales = np.max(np.abs(training), axis=0)
    if np.any(scales == 0):
        raise ValueError('zero-scale levels')
    current, level, lagged = paired_matrices(training / scales, lag_differences)
    controls, _, _ = factor(lagged)
    error = current - controls @ (controls.T @ current)
    lagged_level_error = level - controls @ (controls.T @ level)
    response_basis, _, _ = factor(error)
    level_basis, level_factor, level_permutation = factor(lagged_level_error)
    canonical_left, correlations, _ = np.linalg.svd(level_basis.T @ response_basis, full_matrices=False)
    eigenvalues = correlations**2
    if not 0 < eigenvalues[0] < 1 or eigenvalues[0] - eigenvalues[1] <= 64 * np.finfo(float).eps:
        raise ValueError('rank-one canonical direction is numerically unresolved')
    direction = unpivoted_solve(level_factor, level_permutation, canonical_left[:, 0])
    direction /= np.r_[scales, 1.0]
    if abs(direction[0]) <= 64 * np.finfo(float).eps * np.max(np.abs(direction)):
        raise ValueError('first level cannot normalize the cointegrating direction')
    beta = direction / direction[0]

    current, level, lagged = paired_matrices(training, lag_differences)
    design = np.column_stack((level @ beta, lagged))
    regressors, regression_factor, permutation = factor(design)
    coefficients = unpivoted_solve(regression_factor, permutation, regressors.T @ current)
    residuals = current - design @ coefficients
    alpha = coefficients[0]
    gamma = coefficients[1:].reshape(lag_differences, 2, 2).transpose(0, 2, 1)
    return {'n_fit': np.array([len(current)]), 'lambda': eigenvalues, 'beta': beta, 'alpha': alpha,
            'gamma': gamma, 'pi_levels': np.outer(alpha, beta[:2]), 'restricted_drift': alpha * beta[2],
            'innovation_covariance': residuals.T @ residuals / len(residuals)}


def forecast_differences(model, training, lag_differences, horizon):
    dimension = 2 * (1 + lag_differences)
    transition = np.zeros((dimension, dimension))
    short_run = np.concatenate(model['gamma'], axis=1)
    transition[:2, :2] = np.eye(2) + model['pi_levels']
    transition[2:4, :2] = model['pi_levels']
    transition[:2, 2:] = short_run
    transition[2:4, 2:] = short_run
    if lag_differences > 1:
        transition[4:, 2:-2] = np.eye(dimension - 4)
    drift = np.r_[model['restricted_drift'], model['restricted_drift'], np.zeros(dimension - 4)]
    shock = np.zeros((dimension, 2))
    shock[:2] = shock[2:4] = np.eye(2)
    innovation = shock @ model['innovation_covariance'] @ shock.T
    differences = np.diff(training[-(lag_differences + 1):], axis=0)[::-1]
    state = np.r_[training[-1], differences.ravel()]
    covariance = np.zeros_like(transition)
    forecasts = []
    for _ in range(horizon):
        state = transition @ state + drift
        covariance = transition @ covariance @ transition.T + innovation
        forecasts.append(np.r_[state[:2], covariance[:2, :2].ravel()])
    return np.asarray(forecasts)


def reference(training, lag_differences, horizon):
    result = subprocess.run(
        [shutil.which('Rscript'), '--vanilla', str(ORACLE), str(lag_differences), str(horizon)],
        input='\n'.join(format(value, '.17g') for value in training.ravel()), text=True,
        capture_output=True, check=True, timeout=20,
    )
    return {name: np.fromstring(wire, sep='\t')
            for name, wire in (line.split('\t', 1) for line in result.stdout.splitlines())}


def verify():
    cases = []
    for seed, lag_differences, scale in [(749, 1, [1, 1]), (912, 2, [.25, 7]), (842, 4, [2, .6])]:
        horizon = 13
        all_values = fixture(seed) * scale
        training = all_values[:-horizon]
        candidate = estimate(training, lag_differences)
        candidate['forecast'] = forecast_differences(candidate, training, lag_differences, horizon)
        expected = reference(training, lag_differences, horizon)
        errors = {}
        for key, value in candidate.items():
            np.testing.assert_allclose(np.ravel(value), expected[key], **TOLERANCE, err_msg=key)
            errors[key] = float(np.max(np.abs(np.ravel(value) - expected[key])))
        cases.append({'seed': seed, 'lag_differences': lag_differences, 'input_scale': scale, 'horizon': horizon,
                      'n_fit': int(candidate['n_fit'][0]), 'beta': candidate['beta'].tolist(),
                      'canonical_eigenvalues': candidate['lambda'].tolist(), 'max_abs_error': errors})

    duplicate = fixture(749)[:, 0]
    try:
        estimate(np.column_stack((duplicate, 2 * duplicate + 1)), 1)
    except ValueError as error:
        assert 'rank-deficient' in str(error)
    else:
        raise AssertionError('rank-deficient differences were admitted')

    versions = subprocess.check_output([shutil.which('Rscript'), '--vanilla', '-e',
                                       'cat(R.version.string,"; urca ",as.character(packageVersion("urca")))'], text=True)
    return {'scope': 'independent R Johansen/cajorls reference and QR-canonical-correlation feasibility prototype',
            'reference': versions, 'relative_and_absolute_tolerance': TOLERANCE,
            'degenerate_prototype': 'rank-deficient duplicate differences rejected', 'cases': cases}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
