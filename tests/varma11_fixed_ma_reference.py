from pathlib import Path
import json
import shutil
import subprocess
from tempfile import TemporaryDirectory

import numpy as np
from scipy.linalg import solve_banded
import statsmodels
from statsmodels.tsa.statespace.kalman_filter import KalmanFilter


ORACLE = Path(__file__).with_name('fixtures') / 'varma11_fixed_ma_oracle.R'
TOLERANCE = {'rtol': 2e-12, 'atol': 2e-12}


def fixture(seed, theta, intercept):
    rng = np.random.default_rng(seed)
    innovation = rng.multivariate_normal([0, 0], [[.90, .37], [.37, .64]], 420)
    ar = np.array([[.55, .15], [-.18, .35]])
    values = np.zeros_like(innovation)
    c = np.array([.4, -.8]) if intercept else np.zeros(2)
    for t in range(1, len(values)):
        values[t] = c + ar @ values[t - 1] + theta * innovation[t - 1] + innovation[t]
    return values[100:]


def estimate(values, training, theta, intercept):
    if (values.ndim != 2 or values.shape[1] != 2 or not 8 <= training <= len(values) <= 20_000
            or not abs(theta) <= .95 or not np.isfinite(values).all()):
        raise ValueError('invalid fixed-MA VARMA input')
    current = values[1:training]
    lagged = values[:training - 1]
    n = len(current)
    design = np.column_stack((np.ones(n), lagged)) if intercept else lagged
    bidiagonal = np.ones((2, n))
    bidiagonal[1] = theta
    whitened = solve_banded((1, 0), bidiagonal, np.column_stack((design, current)))
    x, y = whitened[:, :-2], whitened[:, -2:]
    coefficient, _, rank, _ = np.linalg.lstsq(x, y, rcond=1e-12)
    if rank != x.shape[1]:
        raise ValueError('rank-deficient filtered design')
    residual = y - x @ coefficient
    covariance = residual.T @ residual / n
    scale = np.sqrt(np.diag(covariance))
    relative_floor = 64 * np.finfo(float).eps
    response_scale = np.linalg.norm(y, axis=0) / np.sqrt(n)
    if np.any(scale <= relative_floor * response_scale):
        raise ValueError('singular innovation covariance at response precision')
    if 1 - abs(covariance[0, 1] / scale[0] / scale[1]) <= relative_floor:
        raise ValueError('singular innovation covariance')
    _, logdet = np.linalg.slogdet(covariance)
    return {
        'n_fit': n, 'intercept': coefficient[0] if intercept else np.zeros(2),
        'ar': coefficient[-2:].T, 'innovation_covariance': covariance, 'last_innovation': residual[-1],
        'conditional_log_likelihood': -.5 * n * (2 * (np.log(2 * np.pi) + 1) + logdet),
    }


def impulse_forecast(fit, last_level, theta, horizon):
    if not 1 <= horizon <= 200:
        raise ValueError('invalid forecast horizon')
    ar, intercept, sigma = (fit[name] for name in ('ar', 'intercept', 'innovation_covariance'))
    mean = intercept + ar @ last_level + theta * fit['last_innovation']
    covariance = sigma.copy()
    response = ar + theta * np.eye(2)
    output = np.empty((horizon, 6))
    for h in range(horizon):
        output[h] = np.r_[mean, covariance.ravel()]
        mean = intercept + ar @ mean
        covariance += response @ sigma @ response.T
        response = ar @ response
    return output


def r_reference(values, theta, intercept, horizon):
    rscript = shutil.which('Rscript')
    if rscript is None:
        raise RuntimeError('Rscript is required for the independent oracle')
    with TemporaryDirectory() as folder:
        path = Path(folder) / 'values.csv'
        np.savetxt(path, values, delimiter=',', fmt='%.17g')
        stdout = subprocess.check_output([
            rscript, '--vanilla', str(ORACLE), str(path), str(theta), str(intercept).upper(), str(horizon),
        ], text=True)
    return {name: np.fromstring(wire, sep=' ')
            for name, wire in (line.split('\t', 1) for line in stdout.splitlines())}


def kalman_reference(training, fit, theta, horizon):
    identity, zero = np.eye(2), np.zeros((2, 2))
    ar, intercept, sigma = (fit[name] for name in ('ar', 'intercept', 'innovation_covariance'))
    model = KalmanFilter(k_endog=2, k_states=4, k_posdef=2)
    model.bind(np.vstack((training[1:], np.full((horizon, 2), np.nan))))
    model.design = np.hstack((identity, zero))
    model.transition = np.block([[ar, theta * identity], [zero, zero]])
    selection = np.vstack((identity, identity))
    model.selection = selection
    model.state_cov = sigma
    model.state_intercept = np.r_[intercept, np.zeros(2)]
    first_mean = np.r_[intercept + ar @ training[0], np.zeros(2)]
    model.initialize_known(first_mean, selection @ sigma @ selection.T)
    output = model.filter()
    means = output.forecasts[:, -horizon:].T
    covariance = output.forecasts_error_cov[:, :, -horizon:].transpose(2, 0, 1)
    return {
        'forecast': np.column_stack((means, covariance.reshape(horizon, 4))),
        'conditional_log_likelihood': output.llf,
        'last_innovation': output.forecasts_error[:, len(training) - 2],
    }


def compare(actual, expected):
    errors = {}
    for name, wanted in expected.items():
        obtained, wanted = np.ravel(actual[name]), np.ravel(wanted)
        np.testing.assert_allclose(obtained, wanted, **TOLERANCE, err_msg=name)
        errors[name] = float(np.max(np.abs(obtained - wanted)))
    return errors


def verify():
    cases = []
    for seed, theta, intercept, scales in [
        (719, .55, True, [1, 1]), (858, -.6, False, [.25, 5]), (906, .95, True, [2, .6]), (173, 0, True, [1, 1]),
    ]:
        values = fixture(seed, theta, intercept) * scales
        horizon = 13
        training = len(values) - horizon
        candidate = estimate(values, training, theta, intercept)
        candidate['forecast'] = impulse_forecast(candidate, values[training - 1], theta, horizon)
        r_errors = compare(candidate, r_reference(values[:training], theta, intercept, horizon))
        kalman_errors = compare(candidate, kalman_reference(values[:training], candidate, theta, horizon))
        covariances = candidate['forecast'][:, 2:].reshape(horizon, 2, 2)
        np.testing.assert_allclose(covariances[0], candidate['innovation_covariance'], **TOLERANCE)
        assert covariances[0, 0, 1] != 0 and np.min(np.linalg.eigvalsh(covariances)) > 0

        changed = values.copy()
        changed[training:] *= -700
        held_out_fit = estimate(changed, training, theta, intercept)
        held_out_fit['forecast'] = impulse_forecast(held_out_fit, changed[training - 1], theta, horizon)
        for key, expected in candidate.items():
            np.testing.assert_array_equal(held_out_fit[key], expected)

        nested_var = estimate(values, training, 0, intercept)
        nested_forecast = impulse_forecast(nested_var, values[training - 1], 0, horizon)
        difference_from_var = float(np.max(np.abs(candidate['forecast'][:, :2] - nested_forecast[:, :2])))
        if theta:
            assert difference_from_var > 0.05
        else:
            lagged = np.column_stack((np.ones(training - 1), values[:training - 1]))
            ordinary, *_ = np.linalg.lstsq(lagged, values[1:training], rcond=1e-12)
            np.testing.assert_allclose(candidate['ar'], ordinary[-2:].T, **TOLERANCE)
            assert difference_from_var == 0

        cases.append({
            'seed': seed, 'theta': theta, 'intercept': intercept, 'scales': scales, 'training_rows': training,
            'n_fit': candidate['n_fit'], 'forecast_steps': horizon, 'first_forecast_mean': candidate['forecast'][0, :2].tolist(),
            'innovation_covariance': candidate['innovation_covariance'].tolist(),
            'max_abs_forecast_mean_difference_from_var1': difference_from_var,
            'R_max_abs_error': r_errors, 'statsmodels_max_abs_error': kalman_errors,
        })

    pure_ma = {'ar': np.zeros((2, 2)), 'intercept': np.array([1., -2.]),
               'innovation_covariance': np.array([[1., .25], [.25, 2.]]), 'last_innovation': np.array([.75, -.25])}
    path = impulse_forecast(pure_ma, [4, 5], .5, 3)
    sigma = pure_ma['innovation_covariance'].ravel()
    np.testing.assert_array_equal(path, [[1.375, -2.125, *sigma], [1, -2, *(1.25 * sigma)], [1, -2, *(1.25 * sigma)]])

    duplicate = fixture(719, .55, True)[:, 0]
    with np.testing.assert_raises_regex(ValueError, 'rank-deficient'):
        estimate(np.column_stack((duplicate, 2 * duplicate + 1)), len(duplicate), .55, True)

    alternating = np.tile([-1., 1.], 32)
    singular = np.column_stack((np.arange(len(alternating)), alternating))
    with np.testing.assert_raises_regex(ValueError, 'singular innovation covariance'):
        estimate(singular, len(singular), .55, True)

    same_shock = fixture(719, .55, True)[:, 0]
    singular = np.column_stack((same_shock, np.cumsum(same_shock)))
    with np.testing.assert_raises_regex(ValueError, 'singular innovation covariance'):
        estimate(singular, len(singular), .55, True)

    version = subprocess.check_output([shutil.which('Rscript'), '--vanilla', '-e', 'cat(R.version.string)'], text=True)
    return {
        'scope': 'fixed common scalar MA VARMA(1,1) conditional-likelihood feasibility prototype',
        'R': version, 'statsmodels': statsmodels.__version__, 'tolerance': TOLERANCE, 'cases': cases,
        'heldout_perturbation_preserves_fit_and_forecast': True, 'analytic_pure_ma_fixture': 'exact',
        'degeneracy_checks': ['rank-deficient filtered design', 'innovation residuals at response precision',
                              'perfectly correlated innovations'],
    }


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2, allow_nan=False))
