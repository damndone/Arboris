"""arboris-engine is checked against statsmodels and linearmodels, not against itself."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

BINARY = Path(__file__).parents[1] / 'local/native-engine/target/release/arboris-engine'
pytestmark = pytest.mark.skipif(not BINARY.exists(), reason='build with: cargo build --release in native/engine')
TOLERANCE = 1e-10


def engine(*arguments, check=True):
    done = subprocess.run([str(BINARY), *map(str, arguments)], capture_output=True, text=True)
    if check:
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)
    return done


def close(mine, reference):
    assert np.allclose(mine, np.asarray(reference), rtol=TOLERANCE, atol=1e-300)


def table(tmp_path, rows=400, seed=1):
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(rng.normal(size=(rows, 3)), columns=['a', 'b', 'c'])
    frame['y'] = frame.a * .4 - frame.b * .2 + rng.standard_t(4, rows) * (1 + np.abs(frame.a))
    path = tmp_path / 'data.csv'
    frame.to_csv(path, index=False, float_format='%.17g')
    return path, pd.read_csv(path, float_precision='round_trip')


@pytest.mark.parametrize('flag,cov_type', [('classical', 'nonrobust'), ('hc0', 'HC0'), ('hc1', 'HC1')])
def test_ols_matches_statsmodels(tmp_path, flag, cov_type):
    import statsmodels.api as sm
    path, frame = table(tmp_path)
    fitted = sm.OLS(frame.y, sm.add_constant(frame[['a', 'b', 'c']])).fit(cov_type=cov_type, use_t=True)
    fit = engine('ols', '--csv', path, '--y', 'y', '--x', 'a,b,c', '--cov', flag)
    for mine, reference in (('estimate', fitted.params), ('std_error', fitted.bse), ('statistic', fitted.tvalues), ('p_value', fitted.pvalues),
                            ('ci_lower', fitted.conf_int()[0]), ('ci_upper', fitted.conf_int()[1])):
        close(fit[mine], reference)
    close([fit['r_squared'], fit['r_squared_adj']], [fitted.rsquared, fitted.rsquared_adj])


def test_iv_matches_linearmodels(tmp_path):
    from linearmodels.iv import IV2SLS
    rng = np.random.default_rng(2)
    z1, z2, w, u = rng.normal(size=(4, 600))
    d = .6 * z1 + .4 * z2 + .5 * u + rng.normal(size=600)
    frame = pd.DataFrame({'y': d + .3 * w + u, 'd': d, 'w': w, 'z1': z1, 'z2': z2})
    path = tmp_path / 'iv.csv'
    frame.to_csv(path, index=False, float_format='%.17g')
    frame = pd.read_csv(path, float_precision='round_trip')
    fitted = IV2SLS.from_formula('y ~ 1 + w + [d ~ z1 + z2]', frame).fit(cov_type='robust')
    fit = engine('iv', '--csv', path, '--y', 'y', '--x', 'w', '--endog', 'd', '--instruments', 'z1,z2')
    close(fit['estimate'], fitted.params[fit['terms']])
    close(fit['std_error'], fitted.std_errors[fit['terms']])
    # linearmodels takes 1 - cdf, which reaches zero in the tail; the survival function does not.
    from scipy.stats import norm
    close(fit['p_value'], 2 * norm.sf(np.abs(fit['statistic'])))


@pytest.mark.parametrize('drop', [0, 37])
def test_two_way_effects_match_linearmodels(tmp_path, drop):
    from linearmodels.panel import PanelOLS
    rng = np.random.default_rng(3)
    unit, year = np.repeat(np.arange(60), 8), np.tile(np.arange(2000, 2008), 60)
    x1, x2 = rng.normal(size=(2, 480))
    frame = pd.DataFrame({'unit': unit, 'year': year, 'x1': x1, 'x2': x2,
                          'y': .5 * x1 - .2 * x2 + rng.normal(size=60)[unit] + rng.normal(size=8)[year - 2000] + rng.normal(size=480)})
    if drop:  # Unbalanced, where the alternating projections have to iterate.
        frame = frame.sample(frac=1, random_state=4).iloc[drop:].sort_index()
    path = tmp_path / 'panel.csv'
    frame.to_csv(path, index=False, float_format='%.17g')
    frame = pd.read_csv(path, float_precision='round_trip')
    fitted = PanelOLS.from_formula('y ~ 1 + x1 + x2 + EntityEffects + TimeEffects', frame.set_index(['unit', 'year'])).fit()
    fit = engine('panel', '--csv', path, '--y', 'y', '--x', 'x1,x2', '--entity', 'unit', '--time', 'year')
    assert np.allclose(fit['estimate'], fitted.params[fit['terms']], rtol=1e-8)


def test_results_do_not_depend_on_the_thread_count(tmp_path):
    path, _ = table(tmp_path, rows=200_000)
    fits = [engine('ols', '--csv', path, '--y', 'y', '--x', 'a,b,c', '--threads', count) for count in (1, 2, 7)]
    for fit in fits:
        fit.pop('timing_seconds')
    assert fits[0] == fits[1] == fits[2]


def test_a_row_with_a_missing_cell_is_dropped_and_counted(tmp_path):
    path = tmp_path / 'gaps.csv'
    path.write_text('y,x\n1,2\n2,\n3,4.5\nNA,6\n5,7\n6,9\n')
    fit = engine('ols', '--csv', path, '--y', 'y', '--x', 'x', '--cov', 'classical')
    assert fit['nobs'] == 4 and fit['rows_dropped'] == 2


@pytest.mark.parametrize('body,message', [
    ('y,x\n1,a\n2,b\n3,c\n', 'non-numeric'),
    ('y,x\n1,2\n2,4\n3,6\n4,8\n', None),
    ('y,x\n1,1\n', 'fewer usable rows'),
])
def test_what_it_cannot_identify_is_an_error_not_a_guess(tmp_path, body, message):
    path = tmp_path / 'bad.csv'
    path.write_text(body)
    done = engine('ols', '--csv', path, '--y', 'y', '--x', 'x', check=False)
    if message:
        assert done.returncode == 2 and message in done.stderr
    else:  # A perfect fit is a legitimate answer; a constant column is not.
        assert done.returncode == 0


def test_a_collinear_design_is_refused(tmp_path):
    path = tmp_path / 'collinear.csv'
    path.write_text('y,a,b\n1,1,2\n2,2,4\n4,3,6\n3,4,8\n5,5,10\n')
    done = engine('ols', '--csv', path, '--y', 'y', '--x', 'a,b', check=False)
    assert done.returncode == 2 and 'collinear' in done.stderr
