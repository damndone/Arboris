use super::*;

fn near(actual: f64, expected: f64, tolerance: f64) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "expected {expected:.15}, got {actual:.15}"
    );
}

fn noise() -> Vec<f64> {
    let mut seed = 173_u64;
    (0..360)
        .map(|_| {
            seed = (16807 * seed) % 2147483647;
            (seed as f64 - 1073741823.0) / 1073741824.0
        })
        .collect()
}

fn covariates(time: usize) -> [f64; 2] {
    [
        (((7 * time + 3) % 19) as f64 - 9.0) / 9.0,
        (((time * time + 2 * time + 1) % 23) as f64 - 11.0) / 11.0,
    ]
}

enum ModelCase {
    Ar,
    Integrated,
    Seasonal,
}

fn fixture(case: ModelCase) -> (Vec<f64>, Vec<f64>, Vec<f64>) {
    let e = noise();
    let n = if matches!(case, ModelCase::Seasonal) {
        144
    } else {
        240
    };
    let mut values = vec![0.0; n];
    match case {
        ModelCase::Ar => {
            let mut state = 0.0;
            for (time, &innovation) in e.iter().enumerate().skip(1).take(n + 59) {
                state = 0.61 * state + innovation;
                if time >= 60 {
                    values[time - 60] = 2.7 + state;
                }
            }
        }
        ModelCase::Integrated => {
            let mut level = 0.0;
            for (time, value) in values.iter_mut().enumerate() {
                level += e[60 + time] + 0.42 * e[59 + time];
                *value = 30.0 + 0.18 * time as f64 + level;
            }
        }
        ModelCase::Seasonal => {
            for (time, value) in values[..13].iter_mut().enumerate() {
                *value = 50.0 + 0.2 * time as f64 + 0.1 * (time % 12) as f64;
            }
            for t in 13..n {
                let i = 60 + t;
                let innovation =
                    e[i] - 0.38 * e[i - 1] - 0.55 * e[i - 12] + (0.38 * 0.55) * e[i - 13];
                values[t] = innovation + values[t - 1] + values[t - 12] - values[t - 13];
            }
        }
    }
    let mut train = Vec::with_capacity(2 * n);
    for (time, value) in values.iter_mut().enumerate() {
        let x = covariates(time);
        *value += 1.4 * x[0] - 0.9 * x[1];
        train.extend(x);
    }
    let gaps: &[usize] = if matches!(case, ModelCase::Seasonal) {
        &[39, 40, 71, 142, 143]
    } else {
        &[0, 21, 44, 45, 111, 238, 239]
    };
    for &i in gaps {
        values[i] = f64::NAN;
    }
    let future = (n..n + 4).flat_map(covariates).collect();
    (values, train, future)
}

fn check_forecast(model: &RegressionFit, expected: [[f64; 2]; 4]) {
    for (actual, expected) in model.fit.forecast.iter().zip(expected) {
        near(actual[0], expected[0], 3e-5);
        near(actual[1], expected[1], 6e-5);
    }
    near(model.fit.residuals[1], 1.0, 1e-12);
}

#[test]
fn arimax_gls_matches_dense_and_r_arima_xreg_on_gapped_grid() {
    let (y, x, future) = fixture(ModelCase::Ar);
    let model = fit_arimax(
        &y,
        Regressors::new(&x, &future, 2),
        [1, 0, 0],
        Trend::Mean,
        4,
        None,
    )
    .unwrap();
    assert_eq!((model.fit.observed, model.fit.effective), (233, 233));
    near(model.fit.ar[0], 0.632325469186147, 2e-5);
    near(model.fit.deterministic, 2.86169841283334, 2e-5);
    near(model.slopes[0], 1.38610192419073, 2e-5);
    near(model.slopes[1], -0.90749025055663, 2e-5);
    near(model.fit.variance, 0.327203745056518, 5e-6);
    near(model.fit.log_likelihood, -201.275992092272, 1e-6);
    check_forecast(
        &model,
        [
            [3.85795139998298, 0.510340965513708],
            [4.83465002257114, 0.531256179653382],
            [2.75741032807153, 0.539618824735224],
            [3.46495756420175, 0.542962507104327],
        ],
    );
}

#[test]
fn integrated_arimax_profiles_drift_and_xreg_in_the_same_exact_likelihood() {
    let (y, x, future) = fixture(ModelCase::Integrated);
    let model = fit_arimax(
        &y,
        Regressors::new(&x, &future, 2),
        [0, 1, 1],
        Trend::Drift,
        4,
        None,
    )
    .unwrap();
    assert_eq!((model.fit.observed, model.fit.effective), (233, 232));
    near(model.fit.ma[0], 0.47471769381295, 2e-5);
    near(model.fit.deterministic, 0.275363025107809, 2e-5);
    near(model.slopes[0], 1.39209607662006, 2e-5);
    near(model.slopes[1], -0.909203991368405, 2e-5);
    near(model.fit.variance, 0.32221014644057, 5e-6);
    near(model.fit.log_likelihood, -200.227096240531, 1e-6);
    check_forecast(
        &model,
        [
            [96.391019014518, 1.72369042218277],
            [97.7491234325525, 2.42443056005395],
            [96.0030485388878, 3.12517069792512],
            [97.0305333236974, 3.82591083579630],
        ],
    );
}

#[test]
fn airline_sarimax_profiles_regression_and_matches_exact_contrasts() {
    let (y, x, future) = fixture(ModelCase::Seasonal);
    let order = seasonal::Order::new([0, 1, 1], [0, 1, 1, 12]);
    let model = fit_sarimax(
        &y,
        Regressors::new(&x, &future, 2),
        order,
        Trend::None,
        4,
        None,
    )
    .unwrap();
    assert_eq!((model.fit.observed, model.fit.effective), (139, 126));
    near(model.fit.ma[0], -0.321443769711292, 2e-5);
    near(model.seasonal[1], -0.431200544571683, 2e-5);
    near(model.slopes[0], 1.42324562030134, 2e-5);
    near(model.slopes[1], -0.866760291178448, 2e-5);
    near(model.fit.variance, 0.300924438819534, 5e-6);
    near(model.fit.log_likelihood, -105.479160234638, 1e-6);
    check_forecast(
        &model,
        [
            [101.752270151832, 0.578038872098813],
            [102.696049885609, 0.716596086867753],
            [105.561684024532, 0.855153301635530],
            [104.579176515129, 0.993710590773895],
        ],
    );
}

#[test]
fn known_future_covariates_change_only_original_scale_forecast_means() {
    let (y, x, future) = fixture(ModelCase::Ar);
    let changed: Vec<_> = future
        .iter()
        .enumerate()
        .map(|(index, x)| if index % 2 == 0 { x + 3.5 } else { x - 2.25 })
        .collect();
    let fit = |future| {
        fit_arimax(
            &y,
            Regressors::new(&x, future, 2),
            [1, 0, 0],
            Trend::Mean,
            4,
            None,
        )
        .unwrap()
    };
    let base = fit(&future);
    let scenario = fit(&changed);
    assert_eq!(base.fit.ar, scenario.fit.ar);
    assert_eq!(base.slopes, scenario.slopes);
    assert_eq!(base.fit.log_likelihood, scenario.fit.log_likelihood);
    assert_eq!(base.fit.variance, scenario.fit.variance);
    assert_eq!(
        base.fit.residuals.map(f64::to_bits),
        scenario.fit.residuals.map(f64::to_bits)
    );
    for (base_row, scenario_row) in base.fit.forecast.iter().zip(&scenario.fit.forecast) {
        assert_eq!(base_row[1], scenario_row[1]);
        near(
            scenario_row[0] - base_row[0],
            3.5 * base.slopes[0] - 2.25 * base.slopes[1],
            1e-12,
        );
    }
}

#[test]
fn ordinary_gaussian_regression_matches_analytic_qr_solution_and_known_future_values() {
    let x = [-2.0, -1.0, 0.0, 0.0, 1.0, 2.0];
    let y = [-2.0, -2.0, 1.0, 1.0, 2.0, 6.0];
    let model = fit_arimax(
        &y,
        Regressors::new(&x, &[5.0, -3.0], 1),
        [0, 0, 0],
        Trend::Mean,
        2,
        None,
    )
    .unwrap();
    near(model.fit.deterministic, 1.0, 1e-12);
    near(model.slopes[0], 2.0, 1e-12);
    near(model.fit.variance, 2.0 / 3.0, 1e-12);
    for (row, expected) in model.fit.forecast.iter().zip([11.0, -5.0]) {
        near(row[0], expected, 1e-12);
        near(row[1], 2.0 / 3.0, 1e-12);
    }
}

#[test]
fn exact_collinearity_and_differenced_constant_regressor_fail_closed() {
    let (y, x, future) = fixture(ModelCase::Ar);
    let singular: Vec<_> = x
        .chunks_exact(2)
        .flat_map(|row| [row[0], 3.0 * row[0]])
        .collect();
    assert!(matches!(
        fit_arimax(
            &y,
            Regressors::new(&singular, &future, 2),
            [1, 0, 0],
            Trend::Mean,
            4,
            None
        ),
        Err(Failure::Degenerate),
    ));
    let ones = vec![1.0; y.len()];
    assert!(matches!(
        fit_arimax(
            &y,
            Regressors::new(&ones, &[1.0; 4], 1),
            [0, 1, 0],
            Trend::None,
            4,
            None
        ),
        Err(Failure::Degenerate),
    ));
}

#[test]
fn ffi_rejects_unknown_future_and_invalid_training_covariates_without_writing() {
    let (y, mut train, mut future) = fixture(ModelCase::Ar);
    for (status_expected, row_index, len) in [(1, None, 7), (10, Some(3), 8), (9, Some(12), 8)] {
        if status_expected == 10 {
            future[3] = f64::NAN;
        } else if status_expected == 9 {
            future[3] = 0.0;
            train[12] = f64::INFINITY;
        }
        let mut fit = [-1.0; 9];
        let mut forecast = [-2.0; 8];
        let mut residuals = [-3.0; 26];
        let mut error = 99;
        let status = unsafe {
            arboris_arimax_fit(
                y.as_ptr(),
                y.len(),
                train.as_ptr(),
                train.len(),
                future.as_ptr(),
                len,
                2,
                1,
                0,
                0,
                1,
                4,
                fit.as_mut_ptr(),
                fit.len(),
                forecast.as_mut_ptr(),
                forecast.len(),
                residuals.as_mut_ptr(),
                residuals.len(),
                &mut error,
                None,
            )
        };
        assert_eq!(status, status_expected);
        assert_eq!(error, row_index.unwrap_or(99));
        assert_eq!(fit, [-1.0; 9]);
        assert_eq!(forecast, [-2.0; 8]);
        assert_eq!(residuals, [-3.0; 26]);
    }
}

#[test]
fn twice_diffuse_with_nonadjacent_anchors_matches_independent_gls() {
    let shocks = [
        1.0, -2.0, 0.5, 3.0, -1.0, 2.0, -0.5, 1.25, -0.75, 0.5, -1.5, 0.25, 1.0, -0.25,
    ];
    let mut y = vec![8.0, 9.0];
    for shock in shocks {
        let n = y.len();
        y.push(2.0 * y[n - 1] - y[n - 2] + shock);
    }
    let n = y.len();
    let x: Vec<_> = (0..n + 4)
        .map(|time| (((7 * time) % 11) as f64 - 5.0) / 5.0)
        .collect();
    for (value, covariate) in y.iter_mut().zip(&x) {
        *value += 1.5 * covariate;
    }
    for i in [0, 2, 9, 15] {
        y[i] = f64::NAN;
    }
    let model = fit_arimax(
        &y,
        Regressors::new(&x[..n], &x[n..], 1),
        [0, 2, 0],
        Trend::None,
        4,
        None,
    )
    .unwrap();
    assert_eq!((model.fit.observed, model.fit.effective), (12, 10));
    near(model.slopes[0], 1.24681020733652, 1e-12);
    near(model.fit.variance, 1.66085526315790, 1e-12);
    near(model.fit.log_likelihood, -17.7335002846111, 1e-12);
    for (row, expected) in model.fit.forecast.iter().zip([
        [62.4640350877193, 8.30427631578948],
        [69.3140350877193, 23.2519736842105],
        [73.4210526315790, 49.8256578947369],
        [77.5280701754386, 91.3470394736842],
    ]) {
        near(row[0], expected[0], 1e-12);
        near(row[1], expected[1], 1e-12);
    }
}

#[test]
fn source_unit_slopes_and_mean_are_correct_after_predictor_affine_scaling() {
    let (y, x, future) = fixture(ModelCase::Ar);
    let original = fit_arimax(
        &y,
        Regressors::new(&x, &future, 2),
        [1, 0, 0],
        Trend::Mean,
        4,
        None,
    )
    .unwrap();
    let transform = |raw: &[f64]| -> Vec<f64> {
        raw.chunks_exact(2)
            .flat_map(|row| [1e100 * (row[0] + 13.0), 1e-100 * (row[1] - 5.0)])
            .collect()
    };
    let (scaled, new_future) = (transform(&x), transform(&future));
    let adjusted = fit_arimax(
        &y,
        Regressors::new(&scaled, &new_future, 2),
        [1, 0, 0],
        Trend::Mean,
        4,
        None,
    )
    .unwrap();
    near(adjusted.slopes[0] * 1e100, original.slopes[0], 1e-7);
    near(adjusted.slopes[1] * 1e-100, original.slopes[1], 1e-7);
    let expected =
        original.fit.deterministic - 13.0 * original.slopes[0] + 5.0 * original.slopes[1];
    near(adjusted.fit.deterministic, expected, 1e-7);
    near(
        adjusted.fit.log_likelihood,
        original.fit.log_likelihood,
        1e-7,
    );
    for (row, reference) in adjusted.fit.forecast.iter().zip(&original.fit.forecast) {
        near(row[0], reference[0], 1e-7);
        near(row[1], reference[1], 1e-7);
    }
}

#[test]
fn regression_ffi_validates_input_overlap_and_checks_cancellation_before_writing() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static POLLS: AtomicUsize = AtomicUsize::new(0);
    extern "C" fn cancel_in_optimizer() -> i32 {
        i32::from(POLLS.fetch_add(1, Ordering::Relaxed) >= 7)
    }
    let (y, train, mut future) = fixture(ModelCase::Ar);
    let mut fit = [-1.0; 9];
    let mut residuals = [-3.0; 26];
    let mut error = 99;
    let future_before = future.clone();
    let status = unsafe {
        arboris_arimax_fit(
            y.as_ptr(),
            y.len(),
            train.as_ptr(),
            train.len(),
            future.as_ptr(),
            future.len(),
            2,
            1,
            0,
            0,
            1,
            4,
            fit.as_mut_ptr(),
            fit.len(),
            future.as_mut_ptr(),
            future.len(),
            residuals.as_mut_ptr(),
            residuals.len(),
            &mut error,
            None,
        )
    };
    assert_eq!(status, 1);
    assert_eq!(error, 99);
    assert_eq!(future, future_before);
    let mut forecast = [-2.0; 8];
    let status = unsafe {
        arboris_arimax_fit(
            y.as_ptr(),
            y.len(),
            train.as_ptr(),
            train.len(),
            future.as_ptr(),
            future.len(),
            2,
            1,
            0,
            0,
            1,
            4,
            fit.as_mut_ptr(),
            fit.len(),
            forecast.as_mut_ptr(),
            forecast.len(),
            residuals.as_mut_ptr(),
            residuals.len(),
            &mut error,
            Some(cancel_in_optimizer),
        )
    };
    assert_eq!(status, 7);
    assert_eq!(POLLS.load(Ordering::Relaxed), 8);
    assert_eq!(fit, [-1.0; 9]);
    assert_eq!(forecast, [-2.0; 8]);
    assert_eq!(residuals, [-3.0; 26]);
}
