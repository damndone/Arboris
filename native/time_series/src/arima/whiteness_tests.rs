use super::*;
use crate::arima::{arboris_arima_fit, RESIDUAL_LENGTH};

fn fit(
    data: &[f64],
    p: usize,
    d: usize,
    q: usize,
    lag: usize,
    check: CancellationCheck,
) -> (
    i32,
    Vec<f64>,
    [f64; 4],
    [f64; RESIDUAL_LENGTH],
    [f64; OUTPUT_LENGTH],
    usize,
) {
    let mut estimate = vec![-99.0; 6 + p + q];
    let mut forecast = [-99.0; 4];
    let mut residuals = [-99.0; RESIDUAL_LENGTH];
    let mut whiteness = [-99.0; OUTPUT_LENGTH];
    let mut error = usize::MAX;
    let status = unsafe {
        arboris_arima_fit_with_whiteness(
            data.as_ptr(),
            data.len(),
            p,
            d,
            q,
            0,
            2,
            lag,
            estimate.as_mut_ptr(),
            estimate.len(),
            forecast.as_mut_ptr(),
            forecast.len(),
            residuals.as_mut_ptr(),
            residuals.len(),
            whiteness.as_mut_ptr(),
            whiteness.len(),
            &mut error,
            check,
        )
    };
    (status, estimate, forecast, residuals, whiteness, error)
}

#[test]
fn complete_q_matches_r_and_legacy_buffers() {
    let data = [0., -1., 2., 4., -3., 1., 4., -1., 2., 3.].repeat(3);
    let (status, estimate, forecast, residuals, whiteness, _) = fit(&data, 0, 0, 0, 6, None);
    assert_eq!(status, 0);
    assert_eq!(whiteness[..5], [0.0, 30.0, 6.0, 0.0, 6.0]);
    assert!((whiteness[5] - 35.434_052_022_487_9).abs() < 1e-12);
    let mut old_fit = [0.0; 6];
    let mut old_forecast = [0.0; 4];
    let mut old_residuals = [0.0; RESIDUAL_LENGTH];
    let mut error = 0;
    let status = unsafe {
        arboris_arima_fit(
            data.as_ptr(),
            data.len(),
            0,
            0,
            0,
            0,
            2,
            old_fit.as_mut_ptr(),
            6,
            old_forecast.as_mut_ptr(),
            4,
            old_residuals.as_mut_ptr(),
            RESIDUAL_LENGTH,
            &mut error,
            None,
        )
    };
    assert_eq!(status, 0);
    assert_eq!(estimate, old_fit);
    assert_eq!(forecast.map(f64::to_bits), old_forecast.map(f64::to_bits));
    assert_eq!(residuals.map(f64::to_bits), old_residuals.map(f64::to_bits));
}

#[test]
fn gaps_and_short_constant_innovations_are_diagnostic_refusals() {
    let gap = [1.0, f64::NAN, -1.0, f64::NAN].repeat(10);
    let (status, _, _, residuals, whiteness, _) = fit(&gap, 0, 0, 0, 1, None);
    assert_eq!(status, 0);
    assert_eq!(whiteness[..5], [1.0, 20.0, 1.0, 0.0, 1.0]);
    assert!(whiteness[5].is_nan());
    assert!(residuals[2].is_nan());
    assert_eq!(residuals[3], 0.0);
    let short = [0.5, 1., 1.5, 3.].repeat(4);
    let (status, _, _, _, whiteness, _) = fit(&short, 0, 0, 0, 2, None);
    assert_eq!(status, 0);
    assert_eq!(whiteness[..5], [3.0, 16.0, 2.0, 0.0, 2.0]);
    assert!(whiteness[5].is_nan());
    let (status, _, _, _, whiteness, _) = fit(&[3.0; 40], 0, 0, 0, 2, None);
    assert_eq!(status, 0);
    assert_eq!(whiteness[..5], [4.0, 40.0, 2.0, 0.0, 2.0]);
    assert!(whiteness[5].is_nan());
}

#[test]
fn cancellation_and_invalid_lag_preserve_result_buffers() {
    extern "C" fn stop() -> i32 {
        1
    }
    let y = [0., -1., 2., 4., -3., 1., 4., -1., 2., 3.].repeat(3);
    for (expected, lag, check) in [(7, 6, Some(stop as extern "C" fn() -> i32)), (1, 13, None)] {
        let (status, estimate, forecast, residuals, whiteness, _) = fit(&y, 0, 0, 0, lag, check);
        assert_eq!(status, expected);
        assert_eq!(estimate, vec![-99.0; 6]);
        assert_eq!(forecast, [-99.0; 4]);
        assert_eq!(residuals, [-99.0; RESIDUAL_LENGTH]);
        assert_eq!(whiteness, [-99.0; OUTPUT_LENGTH]);
    }
}
