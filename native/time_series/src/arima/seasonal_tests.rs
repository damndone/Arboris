use std::sync::atomic::{AtomicUsize, Ordering};

use super::*;

fn near(actual: f64, expected: f64, tolerance: f64) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "expected {expected:.15}, got {actual:.15}"
    );
}

fn innovations() -> Vec<f64> {
    let mut seed = 173_u64;
    (0..360)
        .map(|_| {
            seed = (16807 * seed) % 2147483647;
            (seed as f64 - 1073741823.0) / 1073741824.0
        })
        .collect()
}

fn monthly_airline() -> Vec<f64> {
    let noise = innovations();
    let e = &noise[60..204];
    let mut values = vec![0.0; e.len()];
    for (time, value) in values[..13].iter_mut().enumerate() {
        *value = 50.0 + 0.2 * time as f64 + 0.1 * (time % 12) as f64;
    }
    for time in 13..values.len() {
        let w = e[time] - 0.38 * e[time - 1] - 0.55 * e[time - 12] + (0.38 * 0.55) * e[time - 13];
        values[time] = w + values[time - 1] + values[time - 12] - values[time - 13];
    }
    for time in [39, 40, 71, 142, 143] {
        values[time] = f64::NAN;
    }
    values
}

fn pure_seasonal_ar() -> Vec<f64> {
    let noise = innovations();
    let mut levels = vec![0.0; noise.len()];
    for time in 4..levels.len() {
        levels[time] = 0.64 * levels[time - 4] + noise[time];
    }
    let mut values: Vec<_> = levels[60..220].iter().map(|value| 4.5 + value).collect();
    for time in [20, 43, 88, 158, 159] {
        values[time] = f64::NAN;
    }
    values
}

const AIRLINE: Order = Order::new([0, 1, 1], [0, 1, 1, 12]);
const SEASONAL_RW: [f64; 13] = [
    10.0,
    20.0,
    30.0,
    40.0,
    12.0,
    17.0,
    31.0,
    38.0,
    13.0,
    20.0,
    f64::NAN,
    39.0,
    f64::NAN,
];

#[test]
fn monthly_airline_matches_dense_exact_likelihood_and_original_level_forecasts() {
    let values = monthly_airline();
    let model = fit_seasonal(&values, AIRLINE, Trend::None, 4, None).unwrap();
    assert_eq!((model.fit.observed, model.fit.effective), (139, 126));
    near(model.fit.ma[0], -0.323918775659795, 2e-5);
    near(model.seasonal_ma, -0.429840801419309, 2e-5);
    near(model.fit.variance, 0.302295551346796, 5e-6);
    near(model.fit.log_likelihood, -105.756950176505, 1e-6);
    for (actual, expected) in model.fit.forecast.iter().zip([
        [101.898570858087, 0.578645576298960],
        [102.915897206223, 0.716820587023493],
        [104.208437610117, 0.854995597747269],
        [104.808118950198, 0.993170679806405],
    ]) {
        near(actual[0], expected[0], 3e-5);
        near(actual[1], expected[1], 6e-5);
    }
}

#[test]
fn seasonal_ar_matches_dense_likelihood_and_same_phase_gap_forecasts() {
    let values = pure_seasonal_ar();
    let order = Order::new([0, 0, 0], [1, 0, 0, 4]);
    let model = fit_seasonal(&values, order, Trend::Mean, 8, None).unwrap();
    assert_eq!((model.fit.observed, model.fit.effective), (155, 155));
    let (mean, phi, variance) = (
        model.fit.deterministic,
        model.seasonal_ar,
        model.fit.variance,
    );
    near(phi, 0.687917307921432, 2e-5);
    near(mean, 4.68738183446282, 2e-5);
    near(variance, 0.315018573209875, 5e-6);
    near(model.fit.log_likelihood, -132.276556991143, 1e-6);
    for (step, row) in model.fit.forecast.iter().enumerate() {
        let target = values.len() + step;
        let last = (0..values.len())
            .rev()
            .find(|&index| index % 4 == target % 4 && values[index].is_finite())
            .unwrap();
        let seasons = ((target - last) / 4) as i32;
        near(
            row[0],
            mean + phi.powi(seasons) * (values[last] - mean),
            1e-12,
        );
        let factor: f64 = (0..seasons).map(|lag| phi.powi(2 * lag)).sum();
        near(row[1], variance * factor, 1e-12);
    }
}

#[test]
fn pure_seasonal_random_walk_retains_uncertainty_through_trailing_gaps() {
    let order = Order::new([0, 0, 0], [0, 1, 0, 4]);
    let model = fit_seasonal(&SEASONAL_RW, order, Trend::None, 5, None).unwrap();
    let fit = model.fit;
    let variance: f64 = 29.0 / 7.0;
    assert_eq!((fit.observed, fit.effective), (11, 7));
    assert_eq!(fit.iterations, 0);
    near(fit.variance, variance, 1e-12);
    near(
        fit.log_likelihood,
        -3.5 * (std::f64::consts::TAU.ln() + variance.ln() + 1.0),
        1e-12,
    );
    for ((row, mean), factor) in fit
        .forecast
        .iter()
        .zip([20.0, 31.0, 39.0, 13.0, 20.0])
        .zip([1.0, 2.0, 1.0, 2.0, 2.0])
    {
        near(row[0], mean, 1e-12);
        near(row[1], variance * factor, 1e-12);
    }
}

#[test]
fn seasonal_products_expand_with_the_ar_and_ma_cross_lag_signs() {
    let ar = expand_factor(&[0.4], 0.3, 4, -1.0);
    let ma = expand_factor(&[0.2], 0.1, 4, 1.0);
    for (index, expected) in [0.4, 0.0, 0.0, 0.3, -0.12].into_iter().enumerate() {
        near(ar[index], expected, 1e-15);
    }
    for (index, expected) in [0.2, 0.0, 0.0, 0.1, 0.02].into_iter().enumerate() {
        near(ma[index], expected, 1e-15);
    }
}

#[test]
fn incomplete_seasonal_anchors_have_row_index_and_do_not_write_fit() {
    for bad in [0, 12] {
        let mut values = monthly_airline();
        values[bad] = f64::NAN;
        let mut fit = [-1.0; 8];
        let mut forecast = [-2.0; 8];
        let mut residuals = [-3.0; 26];
        let mut error = 99;
        let status = unsafe {
            arboris_sarima_fit(
                values.as_ptr(),
                values.len(),
                0,
                1,
                1,
                0,
                1,
                1,
                12,
                0,
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
        assert_eq!(status, 8);
        assert_eq!(error, bad);
        assert_eq!(fit, [-1.0; 8]);
        assert_eq!(forecast, [-2.0; 8]);
        assert_eq!(residuals, [-3.0; 26]);
    }
}

#[test]
fn seasonal_cancel_during_likelihood_does_not_write_result() {
    static POLLS: AtomicUsize = AtomicUsize::new(0);
    extern "C" fn cancel_after_some_work() -> i32 {
        i32::from(POLLS.fetch_add(1, Ordering::Relaxed) >= 8)
    }

    let values = monthly_airline();
    let mut fit = [-1.0; 8];
    let mut forecast = [-2.0; 8];
    let mut residuals = [-3.0; 26];
    let mut error = 99;
    let status = unsafe {
        arboris_sarima_fit(
            values.as_ptr(),
            values.len(),
            0,
            1,
            1,
            0,
            1,
            1,
            12,
            0,
            4,
            fit.as_mut_ptr(),
            fit.len(),
            forecast.as_mut_ptr(),
            forecast.len(),
            residuals.as_mut_ptr(),
            residuals.len(),
            &mut error,
            Some(cancel_after_some_work),
        )
    };
    assert_eq!(status, 7);
    assert_eq!(POLLS.load(Ordering::Relaxed), 9);
    assert_eq!(fit, [-1.0; 8]);
    assert_eq!(forecast, [-2.0; 8]);
    assert_eq!(residuals, [-3.0; 26]);
}
