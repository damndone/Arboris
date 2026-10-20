"""Global AR inversion: topology proofs are separate from statistical validity."""
from fractions import Fraction

import numpy as np
import pytest

from workbench.checks.iv_checks import anderson_rubin_robust


def test_acceptance_island_outside_any_legacy_search_window():
    from workbench.checks.ar_polynomials import certify_set
    result = certify_set([99999999, -20000, 1], [1])
    assert result['kind'] == 'interval'
    assert result['lower'] == pytest.approx(9999, abs=1e-8)
    assert result['upper'] == pytest.approx(10001, abs=1e-8)
    assert result['global_certification']['distinct_real_roots'] == 2


def test_double_root_is_not_lost_by_sign_change_search():
    from workbench.checks.ar_polynomials import certify_set
    result = certify_set([9, -6, 1], [1])
    assert result['kind'] == 'singleton'
    assert result['components'][0]['lower'] == pytest.approx(3, abs=1e-10)
    assert result['components'][0]['lower_closed']


def test_disconnected_intervals_and_two_infinite_tails_are_fully_enumerated():
    from workbench.checks.ar_polynomials import certify_set, mul
    p = mul(mul([-1, 1], [-2, 1]), mul([-3, 1], [-4, 1]))
    bounded = certify_set(p, [1])
    assert bounded['kind'] == 'disjoint'
    np.testing.assert_allclose([(c['lower'], c['upper']) for c in bounded['components']], [(1, 2), (3, 4)], rtol=1e-12, atol=1e-12)
    unbounded = certify_set([-c for c in p], [1])
    assert len(unbounded['components']) == 3
    assert unbounded['components'][0]['lower'] is None
    assert unbounded['components'][-1]['upper'] is None
    assert unbounded['global_certification']['distinct_real_roots'] == 4


def test_nearly_coincident_roots_are_separated_by_exact_counts():
    from workbench.checks.ar_polynomials import certify_set, mul
    denominator = 2**40
    result = certify_set(mul([-1, 1], [-denominator-1, denominator]), [1])
    assert result['kind'] == 'interval'
    assert result['global_certification']['distinct_real_roots'] == 2
    roots = result['global_certification']['root_brackets']
    assert Fraction(roots[0]['upper_rational']) <= Fraction(roots[1]['lower_rational'])


def test_singular_points_are_not_inferred_by_continuous_extension():
    from workbench.checks.ar_polynomials import certify_set
    result = certify_set([-1], [4, -4, 1])
    assert result['kind'] == 'unavailable'
    assert result['reason'] == 'singular_covariance_on_real_line'
    assert len(result['undefined_points']) == 1
    assert result['global_certification']['status'] == 'certified_on_defined_domain'


@pytest.mark.parametrize('p,kind', [([-1], 'whole_line'), ([1], 'empty'), ([0], 'whole_line'),
                                   ([-1, 0, 1], 'interval'), ([1, 0, -1], 'union_of_rays'),
                                   ([0, 1], 'ray_below'), ([0, -1], 'ray_above')])
def test_topologies_and_infinite_tails(p, kind):
    from workbench.checks.ar_polynomials import certify_set
    result = certify_set(p, [1])
    assert result['kind'] == kind
    assert result['global_certification']['status'] == 'certified'


def test_robust_set_is_independent_of_legacy_centre_and_scale():
    rng = np.random.default_rng(20261020)
    z = rng.integers(-8, 9, (70, 2)).astype(float)
    w = np.ones((70, 1))
    x = z[:, :1] + rng.integers(-3, 4, (70, 1))
    y = 12000 * x[:, 0] + rng.integers(-4, 5, 70)
    narrow = anderson_rubin_robust(y, x, z, w, 0, 1e-6)
    wide = anderson_rubin_robust(y, x, z, w, 12000, 100)
    assert narrow['kind'] == 'interval'
    assert narrow['lower'] > 11000
    assert narrow == wide
    cert = narrow['global_certification']
    assert cert['arithmetic'] == 'exact_binary64_input_rationals'
    assert cert['status'] == 'certified'
    assert cert['distinct_real_roots'] == 2


def test_exact_polynomial_matches_hand_computed_one_instrument():
    from workbench.checks.ar_confidence import robust_polynomials
    # No nuisance; z'z=2, coefficient=(y1-y2)/2=1-b;
    # residuals=(1,1,2), HC0 variance=1/2, hence AR=2(1-b)^2.
    y = np.array([2., 0., 2.])
    x = np.array([[1.], [-1.], [0.]])
    z = x.copy()
    p, d = robust_polynomials(y, x, z, np.empty((3, 0)), 4.)
    for b in [Fraction(-2), Fraction(0), Fraction(1), Fraction(7, 2)]:
        pe = sum(c*b**i for i, c in enumerate(p))
        de = sum(c*b**i for i, c in enumerate(d))
        assert pe / de == 2*(1-b)**2 - 4


def test_singular_covariance_does_not_claim_whole_real_line():
    x = np.array([[1.], [-1.], [0.], [0.]])
    result = anderson_rubin_robust(x[:, 0], x, x.copy(), np.ones((4, 1)), 1, 1)
    assert result['kind'] == 'unavailable'
    assert result['reason'] == 'singular_covariance_on_real_line'


def test_homoskedastic_inversion_also_certifies_global_domain():
    from workbench.checks.iv_checks import anderson_rubin_homoskedastic
    x = np.array([[1.], [-1.], [0.]])
    region = anderson_rubin_homoskedastic(np.array([2., 0., 2.]), x, x.copy(), np.empty((3, 0)))
    assert region['global_certification']['status'] == 'certified'
    assert region['reference_distribution'] == 'F(1,2)'
    assert region['coverage_certified'] is False


@pytest.mark.parametrize('case', ['q1', 'q2', 'q3', 'q4', 'distant'])
def test_native_r_and_stata_point_tests_and_r_local_boundaries(case):
    import json
    from pathlib import Path
    import pandas as pd
    from scipy.stats import chi2
    from workbench.checks.ar_confidence import robust_polynomials
    from workbench.checks.ar_polynomials import evaluate
    from workbench.checks.iv_checks import anderson_rubin_homoskedastic
    root = Path(__file__).parent / 'fixtures/agent_completion/iv_ar'
    reference = json.loads((root / 'reference_r.json').read_text())['cases'][case]
    frame = pd.read_csv(root / f'{case}.csv')
    y, x = frame.y.to_numpy(), frame[['x']].to_numpy()
    z, w = frame.filter(regex='^z').to_numpy(), np.column_stack([np.ones(len(frame)), frame.w])
    critical = chi2.ppf(.95, z.shape[1])
    p, d = robust_polynomials(y, x, z, w, critical)
    stata = pd.read_csv(root / 'reference_stata.csv')
    stata = stata[stata['case'] == case]
    for native, (_, independent) in zip(reference['tests'], stata.iterrows()):
        b = Fraction(native['b'])
        statistic = float(evaluate(p, b)/evaluate(d, b))+critical
        assert statistic == pytest.approx(native['hc0_chi_square'], rel=1e-7, abs=1e-9)
        assert statistic == pytest.approx(independent.hc0_chi_square, rel=1e-7, abs=1e-9)
        assert native['homoskedastic_f'] == pytest.approx(independent.homoskedastic_f, rel=1e-7, abs=1e-9)
    region = anderson_rubin_robust(y, x, z, w, 0, 1)
    assert region['kind'] == 'interval'
    assert region['global_certification']['distinct_real_roots'] == 2
    assert [region['lower'], region['upper']] == pytest.approx(reference['local_boundaries'], abs=1e-7)
    homo = anderson_rubin_homoskedastic(y, x, z, w)
    assert homo['global_certification']['status'] == 'certified'
    from scipy.stats import f
    for test in reference['tests']:
        b = test['b']
        accepted = any((c['lower'] is None or c['lower'] <= b) and
                       (c['upper'] is None or c['upper'] >= b) for c in homo['components'])
        assert accepted == (test['homoskedastic_f'] <= f.ppf(.95, z.shape[1], len(y)-w.shape[1]-z.shape[1]))


def test_actual_data_covariance_singularity_is_retained_as_an_undefined_point():
    # Residual y-bx vanishes at b=2 even though y,x have nonzero residuals
    # individually. Cancellation of a common polynomial factor would hide it.
    x = np.array([[1.], [0.], [2.], [0.]])
    z = np.array([[1.], [-1.], [0.], [0.]])
    result = anderson_rubin_robust(2*x[:, 0], x, z, np.empty((4, 0)), 0, 1)
    assert result['kind'] == 'unavailable'
    undefined = result['undefined_points'][0]
    assert Fraction(undefined['lower_rational']) < 2 < Fraction(undefined['upper_rational'])


@pytest.mark.parametrize('q', [1, 2, 3, 4])
def test_permutation_and_invertible_instrument_scaling_preserve_the_set(q):
    rng = np.random.default_rng(40+q)
    z = rng.integers(-5, 6, (45, q)).astype(float)
    x = z[:, :1]+rng.integers(-2, 3, (45, 1))
    y = 2*x[:, 0]+rng.integers(-4, 5, 45)
    w = np.ones((45, 1))
    left = anderson_rubin_robust(y, x, z, w, 0, 1)
    permutation = rng.permutation(45)
    right = anderson_rubin_robust(y[permutation], x[permutation],
        z[permutation]*np.array([2.**(-10*j) for j in range(q)]), w[permutation], 1000, 1e-10)
    assert left['kind'] == right['kind'] == 'interval'
    assert [left['lower'], left['upper']] == pytest.approx([right['lower'], right['upper']], abs=1e-10)


def test_weak_instrument_simulation_does_not_conflate_topology_with_coverage():
    # Pre-fixed: iid heteroskedastic null, n=180, 200 replicates, q=2,
    # gamma=.02, beta=1, alpha=.05. Nominal MCSE=.0154, acceptance [.005,.11].
    # Check the true beta's native test, then certify a fixed subset globally.
    # No failed inversion or fit is discarded.
    from scipy.stats import chi2
    rng = np.random.default_rng(20261021)
    rejected = 0
    for run in range(200):
        z = rng.normal(size=(180, 2))
        u = rng.normal(size=180)*(1+abs(z[:, 0]))
        x = (.02*z.sum(axis=1)+.7*u+rng.normal(size=180))[:, None]
        y = x[:, 0]+u
        r = np.column_stack([np.ones(180), z])
        from statsmodels.api import OLS
        fitted = OLS(y-x[:, 0], r).fit(cov_type='HC0')
        test = fitted.wald_test(np.eye(3)[1:], use_f=False, scalar=True)
        reject = float(test.statistic) > chi2.ppf(.95, 2)
        rejected += reject
        if run < 6:
            region = anderson_rubin_robust(y, x, z, np.ones((180, 1)), 0, 1)
            assert region['global_certification']['status'] == 'certified'
            components = region['components']
            inside = any((c['lower'] is None or c['lower'] <= 1) and (c['upper'] is None or c['upper'] >= 1) for c in components)
            assert inside != reject
    assert .005 <= rejected/200 <= .11, rejected


def test_near_collinearity_and_high_leverage_keep_exact_instrument_span():
    rng = np.random.default_rng(92)
    z = rng.integers(-5, 6, (35, 2)).astype(float)
    z[0] = [2**20, 2**19]
    x = z[:, :1]+rng.integers(-2, 3, (35, 1))
    y = 2*x[:, 0]+rng.integers(-4, 5, 35)
    w = np.ones((35, 1))
    original = anderson_rubin_robust(y, x, z, w, 0, 1)
    near = np.column_stack([z[:, 0], z[:, 0]+2.**-30*z[:, 1]])
    transformed = anderson_rubin_robust(y, x, near, w, 0, 1)
    assert transformed['kind'] == original['kind']
    assert transformed['components'] == original['components']
    assert transformed['global_certification']['status'] == 'certified'


def test_ar_check_cannot_be_used_as_outcome_blind_design_evidence():
    from workbench.checks.iv_checks import FIRST_STAGE_STRENGTH
    assert FIRST_STAGE_STRENGTH.blinding == 'post_fit'


def test_native_whole_line_and_union_of_rays_do_not_depend_on_search_edges():
    z = np.array([[1.], [-1.], [1.], [-1.]])
    x = np.array([[1.], [1.], [-1.], [-1.]])
    w = np.empty((4, 0))
    whole = anderson_rubin_robust(np.ones(4), x, z, w, 10, .001)
    assert whole['kind'] == 'whole_line'
    assert whole['global_certification']['distinct_real_roots'] == 0
    y = z[:, 0]+.25*np.array([1., -1., -1., 1.])
    rays = anderson_rubin_robust(y, x, z, w, 1e6, 1e-5)
    assert rays['kind'] == 'union_of_rays'
    from scipy.stats import chi2
    root = (4/chi2.ppf(.95, 1)-1/16)**.5
    assert [rays['lower'], rays['upper']] == pytest.approx([-root, root], abs=1e-10)


def test_raw_inputs_native_references_and_versions_are_content_bound():
    import hashlib
    import json
    from pathlib import Path
    manifest = json.loads((Path(__file__).parent / 'fixtures/agent_completion/iv_ar/manifest.json').read_text())
    for path, digest in manifest['repository_files'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
    assert manifest['comparisons'] == {'rtol': 1e-7, 'atol': 1e-9, 'boundary_atol': 1e-7}


def test_uncalibrated_designs_and_exact_rank_failure_are_explicitly_unavailable():
    rng = np.random.default_rng(3)
    z = rng.normal(size=(20, 5))
    x = rng.normal(size=(20, 1))
    y = rng.normal(size=20)
    w = np.ones((20, 1))
    result = anderson_rubin_robust(y, x, z, w, 0, 1)
    assert result['kind'] == 'unavailable' and result['reason'] == 'outside_exact_certification_envelope'
    z[:, 1] = z[:, 0]
    result = anderson_rubin_robust(y, x, z[:, :2], w, 0, 1)
    assert result['kind'] == 'unavailable' and result['reason'] == 'rank_deficient_auxiliary_design'
