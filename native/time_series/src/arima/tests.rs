use std::sync::atomic::{AtomicUsize, Ordering};

use super::*;

fn fit(
    values: &[f64],
    p: usize,
    d: usize,
    q: usize,
    trend: Trend,
    horizon: usize,
) -> Result<Fit, Failure> {
    fit_arima(values, p, d, q, trend, horizon, None)
}

fn near(actual: f64, expected: f64, tolerance: f64) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "expected {expected:.15}, got {actual:.15}"
    );
}

fn innovations() -> Vec<f64> {
    let mut state = 173_u64;
    (0..360)
        .map(|_| {
            state = (16807 * state) % 2147483647;
            (state as f64 - 1073741823.0) / 1073741824.0
        })
        .collect()
}

fn ar_two_series() -> Vec<f64> {
    let noise = innovations();
    let mut data = vec![0.0; noise.len()];
    for t in 2..data.len() {
        data[t] = 0.55 * data[t - 1] - 0.26 * data[t - 2] + noise[t];
    }
    data.split_off(60)
}

#[test]
fn ar_two_matches_r_gaussian_likelihood_and_forecast_with_gaps() {
    let mut data: Vec<_> = ar_two_series().into_iter().map(|x| 4.2 + x).collect();
    for t in [0, 21, 22, 23, 179, 297, 298, 299] {
        data[t] = f64::NAN;
    }
    let model = fit(&data, 2, 0, 0, Trend::Mean, 4).unwrap();
    assert_eq!(model.observed, 292);
    assert_eq!(model.effective, 292);
    near(model.ar[0], 0.583074723363020, 4e-6);
    near(model.ar[1], -0.311150042293361, 4e-6);
    near(model.deterministic, 4.30683102490582, 4e-6);
    near(model.variance, 0.323831485239112, 2e-6);
    near(model.log_likelihood, -250.310033142745, 1e-7);
    near(model.residuals[0], 0.00340194286474808, 3e-6);
    near(model.residuals[1], 1.0, 3e-13);
    for (index, (correlation, pairs)) in [
        (0.00429934084109263, 289.0),
        (-0.00898496787477649, 287.0),
        (-0.0200760949668402, 285.0),
        (0.0539781437793119, 284.0),
        (-0.0497389715194815, 283.0),
        (-0.061214601103581, 282.0),
        (0.0478672941180877, 281.0),
        (0.00728085994758944, 280.0),
        (-0.104614721169953, 279.0),
        (0.0139996845538334, 278.0),
        (-0.127174754028388, 277.0),
        (0.0387088440583297, 276.0),
    ]
    .into_iter()
    .enumerate()
    {
        near(model.residuals[2 + 2 * index], correlation, 4e-6);
        assert_eq!(model.residuals[3 + 2 * index], pairs);
    }
    for (actual, expected) in model.forecast.iter().zip([
        [4.24589762561895, 0.442970866753749],
        [4.27745538197117, 0.446537889223367],
        [4.30866225979328, 0.446570110473455],
        [4.31703900422275, 0.446803391685760],
    ]) {
        near(actual[0], expected[0], 6e-6);
        near(actual[1], expected[1], 6e-6);
    }
}

#[test]
fn integrated_ar_two_matches_r_on_original_scale_with_gaps() {
    let mut level = 15.0;
    let mut data: Vec<_> = ar_two_series()
        .into_iter()
        .map(|x| {
            level += x;
            level
        })
        .collect();
    for t in [18, 26, 27, 209, 298, 299] {
        data[t] = f64::NAN;
    }
    let model = fit(&data, 2, 1, 0, Trend::None, 4).unwrap();
    assert_eq!(model.observed, 294);
    assert_eq!(model.effective, 293);
    near(model.ar[0], 0.580488795117486, 5e-6);
    near(model.ar[1], -0.282858828562169, 5e-6);
    near(model.variance, 0.33283623862109, 3e-6);
    near(model.log_likelihood, -257.316834056908, 2e-6);
    for (actual, expected) in model.forecast.iter().zip([
        [46.4593324262139, 2.05355061985954],
        [46.4415056456071, 2.80424070241604],
        [46.4437595476824, 3.46541163957220],
        [46.4501103748619, 4.11159206896651],
    ]) {
        near(actual[0], expected[0], 8e-6);
        near(actual[1], expected[1], 12e-6);
    }
}

#[test]
fn random_walk_drift_weights_gaps_and_forecasts_from_last_grid_row() {
    let data = [f64::NAN, 10.0, 12.0, f64::NAN, 18.0, 19.0, f64::NAN];
    let model = fit(&data, 0, 1, 0, Trend::Drift, 2).unwrap();
    assert_eq!(model.observed, 4);
    assert_eq!(model.effective, 3);
    let variance: f64 = 11.0 / 12.0;
    near(model.deterministic, 2.25, 1e-13);
    near(model.variance, variance, 1e-13);
    near(
        model.log_likelihood,
        -0.5 * (3.0 * (std::f64::consts::TAU.ln() + 1.0 + variance.ln()) + 2.0_f64.ln()),
        1e-13,
    );
    near(model.forecast[0][0], 23.5, 1e-13);
    near(model.forecast[0][1], 2.0 * variance, 1e-13);
    near(model.forecast[1][0], 25.75, 1e-13);
    near(model.forecast[1][1], 3.0 * variance, 1e-13);
}

#[test]
fn twice_integrated_random_walk_retains_diffuse_gap_uncertainty() {
    let data = [f64::NAN, 10.0, f64::NAN, 14.0, 17.0, 19.0, f64::NAN];
    let model = fit(&data, 0, 2, 0, Trend::None, 2).unwrap();
    assert_eq!(model.observed, 4);
    assert_eq!(model.effective, 2);
    near(model.variance, 0.9, 1e-13);
    near(
        model.log_likelihood,
        -0.5 * (2.0 * (std::f64::consts::TAU.ln() + 1.0 + 0.9_f64.ln()) + 1.25_f64.ln()),
        1e-13,
    );
    near(model.forecast[0][0], 23.0, 1e-13);
    near(model.forecast[0][1], 4.5, 1e-13);
    near(model.forecast[1][0], 25.0, 1e-13);
    near(model.forecast[1][1], 12.6, 1e-13);
}

#[test]
fn rescaling_preserves_stationary_fit_and_changes_likelihood_by_jacobian() {
    let data = ar_two_series();
    let baseline = fit(&data, 2, 0, 0, Trend::Mean, 3).unwrap();
    for scale in [1e-145_f64, 1e145_f64] {
        let shifted: Vec<_> = data.iter().map(|x| scale * (14.0 + x)).collect();
        let model = fit(&shifted, 2, 0, 0, Trend::Mean, 3).unwrap();
        near(model.ar[0], baseline.ar[0], 4e-8);
        near(model.ar[1], baseline.ar[1], 4e-8);
        near(model.variance / scale / scale, baseline.variance, 4e-8);
        near(
            model.log_likelihood + 300.0 * scale.ln(),
            baseline.log_likelihood,
            1e-7,
        );
        near(
            model.deterministic / scale - 14.0,
            baseline.deterministic,
            4e-8,
        );
        for (actual, expected) in model.forecast.iter().zip(&baseline.forecast) {
            near(actual[0] / scale - 14.0, expected[0], 4e-8);
            near(actual[1] / scale / scale, expected[1], 4e-8);
        }
    }
}

#[test]
fn rejects_too_short_degenerate_and_unsupported_fits() {
    assert!(matches!(
        fit(&[1.0, 2.0], 2, 0, 0, Trend::None, 1),
        Err(Failure::Insufficient)
    ));
    assert!(matches!(
        fit(&[5.0; 12], 1, 0, 0, Trend::Mean, 1),
        Err(Failure::Degenerate)
    ));
    assert!(matches!(
        fit(&[1.0, 2.0, 3.0, 4.0, 5.0], 0, 1, 0, Trend::Drift, 1),
        Err(Failure::Degenerate)
    ));
    assert!(matches!(
        fit(&[1.0, 0.0, 1.0, 2.0], 0, 2, 0, Trend::Mean, 1),
        Err(Failure::Unsupported)
    ));
    assert!(matches!(
        fit(&[1.0, 2.0, f64::INFINITY, 4.0], 0, 0, 0, Trend::Mean, 1),
        Err(Failure::Input(2))
    ));
}

#[test]
fn ffi_validates_extents_and_overlap_without_partial_writes() {
    let mut data = [1.0, 2.0, 4.0, 5.0, 7.0, 0.0];
    let mut fits = [-1.0; 6];
    let mut forecasts = [-2.0; 4];
    let mut residuals = [-3.0; 26];
    let mut error = 91;
    let status = unsafe {
        arboris_arima_fit(
            data.as_ptr(),
            data.len(),
            0,
            1,
            0,
            0,
            2,
            data.as_mut_ptr(),
            6,
            forecasts.as_mut_ptr(),
            4,
            residuals.as_mut_ptr(),
            26,
            &mut error,
            None,
        )
    };
    assert_eq!(status, 1);
    assert_eq!(data, [1.0, 2.0, 4.0, 5.0, 7.0, 0.0]);
    assert_eq!(forecasts, [-2.0; 4]);
    assert_eq!(residuals, [-3.0; 26]);
    assert_eq!(error, 91);
    let status = unsafe {
        arboris_arima_fit(
            data.as_ptr(),
            data.len(),
            0,
            1,
            0,
            0,
            2,
            fits.as_mut_ptr(),
            6,
            forecasts.as_mut_ptr(),
            3,
            residuals.as_mut_ptr(),
            26,
            &mut error,
            None,
        )
    };
    assert_eq!(status, 1);
    assert_eq!(fits, [-1.0; 6]);
    assert_eq!(forecasts, [-2.0; 4]);
    assert_eq!(residuals, [-3.0; 26]);

    data[4] = f64::INFINITY;
    let status = unsafe {
        arboris_arima_fit(
            data.as_ptr(),
            data.len(),
            0,
            1,
            0,
            0,
            2,
            fits.as_mut_ptr(),
            6,
            forecasts.as_mut_ptr(),
            4,
            residuals.as_mut_ptr(),
            26,
            &mut error,
            None,
        )
    };
    assert_eq!(status, 1);
    assert_eq!(error, 4);
    assert_eq!(fits, [-1.0; 6]);
    assert_eq!(forecasts, [-2.0; 4]);
    assert_eq!(residuals, [-3.0; 26]);
}

#[test]
fn ffi_cancels_during_likelihood_without_writing_any_results() {
    static POLLS: AtomicUsize = AtomicUsize::new(0);
    extern "C" fn cancel_during_likelihood() -> i32 {
        i32::from(POLLS.fetch_add(1, Ordering::Relaxed) >= 9)
    }

    let data = ar_two_series().repeat(5);
    let mut fits = [-1.0; 8];
    let mut forecasts = [-2.0; 4];
    let mut residuals = [-3.0; 26];
    let mut error = 91;
    let status = unsafe {
        arboris_arima_fit(
            data.as_ptr(),
            data.len(),
            2,
            0,
            0,
            1,
            2,
            fits.as_mut_ptr(),
            8,
            forecasts.as_mut_ptr(),
            4,
            residuals.as_mut_ptr(),
            26,
            &mut error,
            Some(cancel_during_likelihood),
        )
    };
    assert_eq!(status, 7);
    assert_eq!(POLLS.load(Ordering::Relaxed), 10);
    assert_eq!(fits, [-1.0; 8]);
    assert_eq!(forecasts, [-2.0; 4]);
    assert_eq!(residuals, [-3.0; 26]);
}

fn mixed_series(ar: &[f64], ma: &[f64], difference: usize, drift: f64, gaps: &[usize]) -> Vec<f64> {
    let noise = innovations();
    let mut data = vec![0.0; noise.len()];
    for t in 4.max(ar.len()).max(ma.len())..data.len() {
        let ar_level: f64 = ar
            .iter()
            .enumerate()
            .map(|(i, a)| a * data[t - 1 - i])
            .sum();
        let ma_level: f64 = ma
            .iter()
            .enumerate()
            .map(|(i, b)| b * noise[t - 1 - i])
            .sum();
        data[t] = ar_level + ma_level + noise[t];
    }
    let mut result = data.split_off(60);
    for _ in 0..difference {
        let mut level = 0.0;
        for value in &mut result {
            level += *value;
            *value = level;
        }
    }
    for (time, value) in result.iter_mut().enumerate() {
        *value = 7.0 + *value + drift * time as f64;
    }
    for &time in gaps {
        result[time] = f64::NAN;
    }
    result
}

fn assert_reference_fit(
    fit: &Fit,
    ar: &[f64],
    ma: &[f64],
    deterministic: f64,
    variance: f64,
    log_likelihood: f64,
    forecast: [[f64; 2]; 4],
) {
    for (&actual, &expected) in fit.ar.iter().zip(ar).chain(fit.ma.iter().zip(ma)) {
        near(actual, expected, 2e-5);
    }
    near(fit.deterministic, deterministic, 1e-5);
    near(fit.variance, variance, 5e-6);
    near(fit.log_likelihood, log_likelihood, 1e-6);
    for (actual, expected) in fit.forecast.iter().zip(forecast) {
        near(actual[0], expected[0], 3e-5);
        near(actual[1], expected[1], 6e-5);
    }
}

#[test]
fn ma_two_matches_r_finite_history_prediction() {
    let series = mixed_series(&[], &[0.45, -0.3], 0, 0.0, &[11, 24, 25, 26, 182, 296]);
    let model = fit(&series, 0, 0, 2, Trend::Mean, 4).unwrap();
    assert_reference_fit(
        &model,
        &[],
        &[0.483294575941371, -0.263591621473686],
        7.08743548518164,
        0.318401776709112,
        -250.513790772235,
        [
            [7.11787261195999, 0.337183832185626],
            [7.07053805361572, 0.394622725184117],
            [7.08743548518164, 0.414894769258733],
            [7.08743548518164, 0.414894769258733],
        ],
    );
}

#[test]
fn arma_matches_r_forecast_when_the_last_grid_rows_are_missing() {
    let series = mixed_series(&[0.6], &[0.28], 0, 0.0, &[0, 35, 84, 85, 86, 298, 299]);
    let model = fit(&series, 1, 0, 1, Trend::Mean, 4).unwrap();
    assert_reference_fit(
        &model,
        &[0.566193884457671],
        &[0.341240509944452],
        7.23575902257555,
        0.325739247828699,
        -252.609333621009,
        [
            [7.25043029071312, 0.67995168190648],
            [7.24406580487228, 0.707516888925052],
            [7.24046227191148, 0.716353619355524],
            [7.23842197358663, 0.719186458762397],
        ],
    );
}

#[test]
fn integrated_arma_with_drift_matches_dense_r_likelihood_and_forecast() {
    let series = mixed_series(
        &[0.53, -0.29],
        &[0.5, 0.15],
        1,
        0.15,
        &[0, 39, 81, 82, 83, 299],
    );
    let model = fit(&series, 2, 1, 2, Trend::Drift, 4).unwrap();
    assert_reference_fit(
        &model,
        &[0.234389545702075, -0.221913399829474],
        &[0.834275597092673, 0.395355564528444],
        0.317437183623065,
        0.322250480048243,
        -253.658545420793,
        [
            [101.481950566592, 1.70128128053369],
            [101.753443305229, 3.70342709448741],
            [102.045467840221, 5.49033880055627],
            [102.367144252666, 7.09060713825949],
        ],
    );
}

#[test]
fn twice_integrated_ma_matches_dense_r_likelihood_and_forecast() {
    let series = mixed_series(&[], &[-0.35], 2, 0.0, &[]);
    let model = fit(&series, 0, 2, 1, Trend::None, 4).unwrap();
    assert_reference_fit(
        &model,
        &[],
        &[-0.311501582237506],
        0.0,
        0.328407379664677,
        -256.983153578697,
        [
            [2316.00845076088, 0.328407379664677],
            [2330.68396163895, 1.26470565547590],
            [2345.35947251702, 3.12024477460414],
            [2360.03498339509, 6.20637468421987],
        ],
    );
}

#[test]
fn even_grid_subsampling_cannot_identify_signed_arma_coefficients() {
    let mut series = mixed_series(&[0.75], &[0.2], 0, 0.0, &[]);
    for time in (1..series.len()).step_by(2) {
        series[time] = f64::NAN;
    }
    assert!(matches!(
        fit(&series, 1, 0, 1, Trend::Mean, 4),
        Err(Failure::Degenerate)
    ));
}

#[test]
fn order_limits_include_full_ar_ma_and_mixed_models() {
    let gaps = [5, 6, 7, 69, 124, 125, 299];
    let ar = mixed_series(&[0.32, -0.22, 0.18, 0.1, -0.16], &[], 0, 0.0, &gaps);
    assert_reference_fit(
        &fit(&ar, 5, 0, 0, Trend::Mean, 4).unwrap(),
        &[
            0.364738637732429,
            -0.263104056625523,
            0.192745912185760,
            0.119353191607697,
            -0.234209811581116,
        ],
        &[],
        7.09715180859341,
        0.315744886490867,
        -247.776150942567,
        [
            [7.40602608141430, 0.357749778188580],
            [7.20101229431572, 0.363091597031615],
            [6.94107922693814, 0.363860264528755],
            [7.02633933513488, 0.382332182483813],
        ],
    );
    let ma = mixed_series(&[], &[0.32, -0.22, 0.13, -0.18, 0.1], 0, 0.0, &gaps);
    assert_reference_fit(
        &fit(&ma, 0, 0, 5, Trend::Mean, 4).unwrap(),
        &[],
        &[
            0.354385083166679,
            -0.230273092131759,
            0.0685732689670598,
            -0.138228400948105,
            0.075044683234874,
        ],
        7.09141813969855,
        0.325500525600432,
        -253.097854793669,
        [
            [6.83783025060690, 0.366379741838168],
            [7.18614726757810, 0.383639634066120],
            [7.04291886347073, 0.385170232979154],
            [7.11263037197749, 0.391389601086023],
        ],
    );
    let mixed = mixed_series(&[0.22, -0.3, 0.33], &[-0.37, 0.24, 0.27], 0, 0.0, &gaps);
    assert_reference_fit(
        &fit(&mixed, 3, 0, 3, Trend::Mean, 4).unwrap(),
        &[0.303446123792771, -0.447341643555232, 0.418171156438419],
        &[-0.398384577330571, 0.344230323582965, 0.163066982248876],
        7.10835179670849,
        0.316830777136811,
        -249.231134751963,
        [
            [7.49889198400495, 0.319686471136060],
            [6.98269802649114, 0.325200243306692],
            [7.02258900261112, 0.433137948547552],
            [7.30185021511938, 0.445362466554052],
        ],
    );
    assert!(matches!(
        fit(&mixed, 3, 0, 4, Trend::Mean, 4),
        Err(Failure::Unsupported)
    ));
}
