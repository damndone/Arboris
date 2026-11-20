use std::sync::atomic::{AtomicUsize, Ordering};

use super::*;

const DAILY: usize = 24;

fn shocks(count: usize, mut seed: u64) -> Vec<f64> {
    (0..count)
        .map(|_| {
            seed = (16807 * seed) % 2147483647;
            (seed as f64 - 1073741823.0) / 1073741824.0
        })
        .collect()
}

fn seasonal_random_walk() -> Vec<f64> {
    let noise = shocks(110, 173);
    let mut values = vec![0.0; noise.len()];
    for (t, y) in values[..DAILY].iter_mut().enumerate() {
        *y = 30.0 + (t % 7) as f64 * 0.75;
    }
    for t in DAILY..values.len() {
        values[t] = values[t - DAILY] + noise[t];
    }
    for row in [35, 61, 62, 108, 109] {
        values[row] = f64::NAN;
    }
    values
}

fn seasonal_ar() -> Vec<f64> {
    let mut levels = shocks(480, 617);
    for t in DAILY..levels.len() {
        levels[t] += 0.56 * levels[t - DAILY];
    }
    let mut values: Vec<_> = levels[120..384].iter().map(|y| 4.25 + y).collect();
    for row in [65, 133, 201, 262, 263] {
        values[row] = f64::NAN;
    }
    values
}

fn near(actual: f64, expected: f64, atol: f64) {
    assert!(
        (actual - expected).abs() <= atol,
        "{actual:.16e} versus {expected:.16e}"
    );
}

#[test]
fn daily_difference_preserves_all_phase_anchors_and_gap_uncertainty() {
    let y = seasonal_random_walk();
    let order = Order::new([0, 0, 0], [0, 1, 0, DAILY]);
    let result = fit_seasonal(&y, order, Trend::None, 30, None).unwrap();
    assert_eq!((result.fit.observed, result.fit.effective), (105, 81));
    assert_eq!(result.fit.iterations, 0);
    near(result.fit.variance, 0.311_107_812_025_096_63, 2e-13);
    near(result.fit.log_likelihood, -68.685_303_501_556_95, 3e-11);
    for (step, [mean, variance]) in result.fit.forecast.into_iter().enumerate() {
        let target = y.len() + step;
        let last = (0..y.len())
            .rev()
            .find(|t| t % DAILY == target % DAILY && y[*t].is_finite())
            .unwrap();
        near(mean, y[last], 2e-13);
        near(
            variance,
            result.fit.variance * ((target - last) / DAILY) as f64,
            2e-13,
        );
    }
}

#[test]
fn daily_seasonal_ar_matches_independent_dense_fit_and_phase_forecast() {
    let y = seasonal_ar();
    let order = Order::new([0, 0, 0], [1, 0, 0, DAILY]);
    let result = fit_seasonal(&y, order, Trend::Mean, 30, None).unwrap();
    assert_eq!((result.fit.observed, result.fit.effective), (259, 259));
    near(result.seasonal_ar, 0.494_744_182_013_649_4, 2e-6);
    near(result.fit.deterministic, 4.236_732_572_432_477, 2e-6);
    near(result.fit.variance, 0.315_050_318_411_247_53, 2e-6);
    near(result.fit.log_likelihood, -221.626_865_316_859_4, 1e-8);
    for (step, [mean, variance]) in result.fit.forecast.into_iter().enumerate() {
        let target = y.len() + step;
        let last = (0..y.len())
            .rev()
            .find(|t| t % DAILY == target % DAILY && y[*t].is_finite())
            .unwrap();
        let count = ((target - last) / DAILY) as i32;
        let phi = result.seasonal_ar;
        let level = result.fit.deterministic;
        near(mean, level + phi.powi(count) * (y[last] - level), 2e-13);
        near(
            variance,
            result.fit.variance * (0..count).map(|lag| phi.powi(2 * lag)).sum::<f64>(),
            2e-13,
        );
    }
}

#[test]
fn period_24_retains_state_limit_and_checks_exact_starting_block() {
    let mut y = seasonal_random_walk();
    let maximum = Order::new([2, 2, 1], [0, 1, 0, DAILY]);
    assert_eq!(maximum.width(), MAX_SEASONAL_STATE);
    assert!(maximum.supported(y.len(), Trend::None));
    let system = Factors::new(&[0.4, -0.2, 0.3, 0.0, 0.0, 0.0], maximum).system(maximum);
    assert_eq!(system.width, 28);
    assert_eq!(system.rows[0].len, 7);
    y[25] = f64::NAN;
    assert!(matches!(
        prepare_sample(&y, maximum, Trend::None, None),
        Err(Failure::MissingAnchor(25))
    ));
    assert!(!Order::new([0, 0, 0], [1, 1, 0, DAILY]).supported(y.len(), Trend::None));
    assert!((13..24).all(|p| !Order::new([0, 0, 0], [0, 1, 0, p]).supported(y.len(), Trend::None)));
}

#[test]
fn daily_dynamic_setup_is_charged_to_existing_budget() {
    let y = seasonal_ar();
    let order = Order::new([1, 0, 0], [1, 0, 1, DAILY]);
    assert!(order.supported(y.len(), Trend::None));
    assert!(matches!(
        fit_seasonal(&y, order, Trend::None, 1, None),
        Err(Failure::Unsupported)
    ));
}

#[test]
fn daily_dynamic_cancellation_never_publishes_fit_or_forecasts() {
    static POLLS: AtomicUsize = AtomicUsize::new(0);
    extern "C" fn cancel() -> i32 {
        i32::from(POLLS.fetch_add(1, Ordering::SeqCst) == 6)
    }
    let y = seasonal_ar();
    let mut fit = [-99.0; 7];
    let mut forecast = [-99.0; 2];
    let mut residuals = [-99.0; 26];
    let mut error = 55;
    let status = unsafe {
        arboris_sarima_fit(
            y.as_ptr(),
            y.len(),
            0,
            0,
            0,
            1,
            0,
            0,
            DAILY,
            1,
            1,
            fit.as_mut_ptr(),
            fit.len(),
            forecast.as_mut_ptr(),
            forecast.len(),
            residuals.as_mut_ptr(),
            residuals.len(),
            &mut error,
            Some(cancel),
        )
    };
    assert_eq!(status, 7);
    assert_eq!(POLLS.load(Ordering::SeqCst), 7);
    assert_eq!(fit, [-99.0; 7]);
    assert_eq!(forecast, [-99.0; 2]);
    assert_eq!(residuals, [-99.0; 26]);
}
