use super::*;
use std::sync::atomic::{AtomicUsize, Ordering};

const SHORT: [f64; 6] = [10.0, 12.0, 11.0, 15.0, 14.0, 19.0];

fn run(
    y: &[f64],
    alpha: f64,
    beta: f64,
    phi: f64,
    horizon: usize,
) -> (i32, [f64; 7], Vec<f64>, usize) {
    let mut fit = [-99.0; 7];
    let mut forecast = vec![-99.0; 2 * horizon];
    let mut error = usize::MAX;
    let status = unsafe {
        arboris_ets_trend_fit(
            y.as_ptr(),
            y.len(),
            alpha,
            beta,
            phi,
            horizon,
            fit.as_mut_ptr(),
            fit.len(),
            forecast.as_mut_ptr(),
            forecast.len(),
            &mut error,
            None,
        )
    };
    (status, fit, forecast, error)
}

fn close(actual: &[f64], expected: &[f64], tolerance: f64) {
    assert_eq!(actual.len(), expected.len());
    for (index, (&actual, &expected)) in actual.iter().zip(expected).enumerate() {
        assert!(
            (actual - expected).abs() <= tolerance,
            "position {index}: {actual:.16e} versus {expected:.16e}"
        );
    }
}

#[test]
fn damped_exact_rational_short_fit() {
    let (status, fit, forecast, _) = run(&SHORT, 0.4, 0.12, 0.8, 3);
    assert_eq!(status, 0);
    close(
        &fit,
        &[
            6.853_048_449_012_986,
            3.144_173_690_265_027,
            16.849_467_688_645_007,
            1.132_859_838_815_565_5,
            3.824_632_117_819_26,
            -12.538_018_052_143_515,
            6.0,
        ],
        2e-13,
    );
    close(
        &forecast,
        &[
            17.755_755_559_697_46,
            3.824_632_117_819_26,
            18.480_785_856_539_42,
            4.765_552_812_916_683,
            19.060_810_094_012_99,
            6.020_413_998_832_043,
        ],
        2e-13,
    );
}

#[test]
fn undamped_exact_rational_short_fit() {
    let (status, fit, forecast, _) = run(&SHORT, 0.4, 0.12, 1.0, 3);
    assert_eq!(status, 0);
    close(
        &fit,
        &[
            8.071_316_714_107_12,
            1.515_952_824_236_698_4,
            17.427_670_196_527_82,
            1.634_830_804_065_549_3,
            2.876_973_793_962_296_4,
            -11.683_848_126_390_85,
            6.0,
        ],
        2e-13,
    );
    close(
        &forecast,
        &[
            19.062_501_000_593_37,
            2.876_973_793_962_296_4,
            20.697_331_804_658_92,
            3.654_907_507_849_701,
            22.332_162_608_724_467,
            4.833_315_973_856_658,
        ],
        2e-13,
    );
}

#[test]
fn forecast_variance_accumulates_shocks_and_damped_mean_levels() {
    let (alpha, beta) = (0.4, 0.12);
    for phi in [0.8, 1.0] {
        let (status, fit, forecast, _) = run(&SHORT, alpha, beta, phi, 200);
        assert_eq!(status, 0);
        let [level, slope, variance] = [fit[2], fit[3], fit[4]];
        let sum_powers = |h: usize| {
            if phi == 1.0 {
                h as f64
            } else {
                phi * (1.0 - phi.powi(h as i32)) / (1.0 - phi)
            }
        };
        for (index, row) in forecast.chunks_exact(2).enumerate() {
            let independent_variance = variance
                * (1.0
                    + (1..=index)
                        .map(|lag| (alpha + beta * sum_powers(lag)).powi(2))
                        .sum::<f64>());
            let independent_mean = level + slope * sum_powers(index + 1);
            close(&[row[0]], &[independent_mean], 3e-13);
            assert!((row[1] / independent_variance - 1.0).abs() < 1e-14);
        }
    }
}

#[test]
fn forecast_obeys_affine_change_and_likelihood_jacobian() {
    let shift = 1e9;
    let scale = 1024.0;
    let shifted = SHORT.map(|value| shift + scale * value);
    for phi in [0.8, 1.0] {
        let (status, fit, forecast, _) = run(&SHORT, 0.4, 0.12, phi, 3);
        assert_eq!(status, 0);
        let (status, changed, changed_forecast, _) = run(&shifted, 0.4, 0.12, phi, 3);
        assert_eq!(status, 0);
        for index in [0, 2] {
            close(&[(changed[index] - shift) / scale], &[fit[index]], 1e-10);
        }
        for index in [1, 3] {
            close(&[changed[index] / scale], &[fit[index]], 1e-14);
        }
        close(
            &[changed[4] / scale.powi(2), changed[5] + fit[6] * scale.ln()],
            &fit[4..6],
            3e-14,
        );
        for (before, after) in forecast
            .chunks_exact(2)
            .zip(changed_forecast.chunks_exact(2))
        {
            close(&[(after[0] - shift) / scale], &[before[0]], 1e-10);
            close(&[after[1] / scale.powi(2)], &[before[1]], 1e-14);
        }
    }
}

#[test]
fn input_refusals_leave_forecast_and_fit_untouched() {
    let constant = [3.0; 6];
    let linear = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0];
    let huge = [f64::MAX, 0.0, -f64::MAX, f64::MAX];
    let mut gap = SHORT;
    gap[4] = f64::NAN;
    for (series, alpha, beta, phi, expected, expected_index) in [
        (&SHORT[..3], 0.4, 0.12, 1.0, 3, usize::MAX),
        (&SHORT[..], 0.4, 0.41, 1.0, 6, usize::MAX),
        (&SHORT[..], 0.4, 0.12, 0.99, 6, usize::MAX),
        (&constant[..], 0.4, 0.12, 1.0, 4, usize::MAX),
        (&linear[..], 0.4, 0.12, 1.0, 4, usize::MAX),
        (&gap[..], 0.4, 0.12, 1.0, 1, 4),
        (&huge[..], 0.4, 0.12, 1.0, 2, usize::MAX),
    ] {
        let (status, fit, forecast, index) = run(series, alpha, beta, phi, 3);
        assert_eq!((status, index), (expected, expected_index));
        assert_eq!(fit, [-99.0; 7]);
        assert_eq!(forecast, vec![-99.0; 6]);
    }
}

#[test]
fn long_small_gain_exact_linear_is_degenerate() {
    let linear = (0..100_000).map(|t| t as f64).collect::<Vec<_>>();
    assert_eq!(run(&linear, 0.0001, 0.0001, 1.0, 1).0, 4);
}

#[test]
fn overlap_rejected_before_mutation() {
    let mut shared = [2.0; 8];
    let mut forecast = [-99.0; 2];
    let mut error = 42;
    let ptr = shared.as_mut_ptr();
    let status = unsafe {
        arboris_ets_trend_fit(
            ptr,
            6,
            0.4,
            0.12,
            1.0,
            1,
            ptr.add(1),
            7,
            forecast.as_mut_ptr(),
            2,
            &mut error,
            None,
        )
    };
    assert_eq!(status, 1);
    assert_eq!(shared, [2.0; 8]);
    assert_eq!(forecast, [-99.0; 2]);
    assert_eq!(error, 42);
}

#[test]
fn owner_checkpoint_stops_before_publication() {
    static POLLS: AtomicUsize = AtomicUsize::new(0);
    extern "C" fn stop() -> i32 {
        i32::from(POLLS.fetch_add(1, Ordering::SeqCst) == 5)
    }
    let y = (0..1300).map(|t| f64::from(t % 37)).collect::<Vec<_>>();
    let mut fit = [-99.0; 7];
    let mut forecast = [-99.0; 6];
    let mut error = 42;
    let status = unsafe {
        arboris_ets_trend_fit(
            y.as_ptr(),
            y.len(),
            0.4,
            0.12,
            0.8,
            3,
            fit.as_mut_ptr(),
            7,
            forecast.as_mut_ptr(),
            6,
            &mut error,
            Some(stop),
        )
    };
    assert_eq!(status, 7);
    assert_eq!(POLLS.load(Ordering::SeqCst), 6);
    assert_eq!(fit, [-99.0; 7]);
    assert_eq!(forecast, [-99.0; 6]);
    assert_eq!(error, 42);
}
