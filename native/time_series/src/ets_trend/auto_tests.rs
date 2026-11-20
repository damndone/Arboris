use super::*;

const SENTINEL: f64 = -99.0;

fn simulated(phi: f64) -> Vec<f64> {
    let mut seed = 570_u64;
    let (mut level, mut slope) = (9.0, 0.8);
    (0..180)
        .map(|_| {
            let shock = (0..12)
                .map(|_| {
                    seed = seed * 16807 % 2147483647;
                    seed as f64 / 2147483647.0
                })
                .sum::<f64>()
                - 6.0;
            let projection = level + phi * slope;
            level = projection + 0.68 * shock;
            slope = phi * slope + 0.16 * shock;
            projection + shock
        })
        .collect()
}

fn run(
    y: &[f64],
    alpha: Option<f64>,
    beta: Option<f64>,
    phi: f64,
    check: super::super::Checkpoint,
) -> (i32, [f64; 15], [f64; 6], usize) {
    let mut fit = [SENTINEL; 15];
    let mut forecast = [SENTINEL; 6];
    let mut row = usize::MAX;
    let status = unsafe {
        arboris_ets_trend_fit_auto(
            y.as_ptr(),
            y.len(),
            i32::from(alpha.is_none()),
            alpha.unwrap_or_default(),
            i32::from(beta.is_none()),
            beta.unwrap_or_default(),
            phi,
            3,
            fit.as_mut_ptr(),
            fit.len(),
            forecast.as_mut_ptr(),
            forecast.len(),
            &mut row,
            check,
        )
    };
    (status, fit, forecast, row)
}

#[test]
fn one_or_two_free_gains_yield_a_verified_fit() {
    let values = simulated(1.0);
    for (alpha, beta, expected_dof) in [
        (None, None, 2.0),
        (None, Some(0.12), 1.0),
        (Some(0.4), None, 1.0),
    ] {
        let (status, fit, forecast, row) = run(&values, alpha, beta, 1.0, None);
        assert_eq!((status, row), (0, usize::MAX));
        assert_eq!(fit[9], expected_dof);
        assert_eq!(fit[6], 180.0);
        assert!(fit[11] <= 1e-7);
        assert!(fit[12] > 1e-4);
        assert!(fit[13] > 1e-7);
        assert!(fit[14] >= expected_dof);
        assert!(forecast.iter().all(|v| v.is_finite()));
        assert!(forecast[1] < forecast[3] && forecast[3] < forecast[5]);
        if let Some(alpha) = alpha {
            assert_eq!(fit[7], alpha);
        }
        if let Some(beta) = beta {
            assert_eq!(fit[8], beta);
        }
    }
}

#[test]
fn damped_and_undamped_use_the_supplied_phi() {
    let values = simulated(0.86);
    let (status, damped, damped_forecast, _) = run(&values, None, None, 0.86, None);
    assert_eq!(status, 0);
    let (status, undamped, undamped_forecast, _) = run(&values, None, None, 1.0, None);
    assert_eq!(status, 0);
    assert_ne!(damped_forecast, undamped_forecast);
    assert!((damped_forecast[0] - damped[2] - 0.86 * damped[3]).abs() < 1e-12);
    assert!((undamped_forecast[0] - undamped[2] - undamped[3]).abs() < 1e-12);
}

#[test]
fn layout_domain_minimum_and_boundary_are_distinct_failures() {
    let boundary = (0..50)
        .map(|i| if i % 2 == 0 { 2.0 } else { 9.0 })
        .collect::<Vec<_>>();
    let mut invalid = boundary.clone();
    invalid[15] = f64::NAN;
    for (y, alpha, beta, phi, status, row) in [
        (&boundary[..39], None, None, 1.0, 3, usize::MAX),
        (&boundary[..23], None, Some(0.12), 1.0, 3, usize::MAX),
        (&boundary[..], Some(0.4), Some(0.12), 1.0, 6, usize::MAX),
        (&boundary[..], Some(0.001), None, 1.0, 6, usize::MAX),
        (&boundary[..], None, Some(0.12), 0.99, 6, usize::MAX),
        (&boundary[..], None, None, 1.0, 8, usize::MAX),
        (&invalid[..], None, None, 1.0, 1, 15),
    ] {
        assert_eq!(
            run(y, alpha, beta, phi, None),
            (status, [SENTINEL; 15], [SENTINEL; 6], row)
        );
    }
}

#[test]
fn cancellation_interrupts_parameter_evaluations_without_publishing() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static POLLS: AtomicUsize = AtomicUsize::new(0);
    extern "C" fn stop() -> i32 {
        i32::from(POLLS.fetch_add(1, Ordering::SeqCst) == 19)
    }
    let result = run(&simulated(1.0), None, None, 1.0, Some(stop));
    assert_eq!(result, (7, [SENTINEL; 15], [SENTINEL; 6], usize::MAX));
    assert_eq!(POLLS.load(Ordering::SeqCst), 20);
}

#[test]
fn profiled_gradient_matches_richardson_at_distinct_gains() {
    for phi in [1.0, 0.86] {
        let values = simulated(phi);
        let (offset, scale) = normalize(&values, None).ok().unwrap();
        let mut objective = Objective {
            values: &values,
            offset,
            scale,
            phi,
            check: None,
            evaluations: 0,
        };
        for gains in [[0.03, 0.008], [0.52, 0.16], [0.94, 0.83]] {
            let analytic = objective.at(gains).ok().unwrap().profile.gradient;
            for (i, expected) in analytic.into_iter().enumerate() {
                let mut estimate = |h| {
                    let mut left = gains;
                    let mut right = gains;
                    left[i] -= h;
                    right[i] += h;
                    let left = objective.at(left).ok().unwrap().value;
                    let right = objective.at(right).ok().unwrap().value;
                    (right - left) / (2.0 * h)
                };
                let richardson = (4.0 * estimate(2e-5) - estimate(4e-5)) / 3.0;
                assert!((richardson - expected).abs() < 1e-7 * expected.abs().max(1.0));
            }
        }
    }
}

#[test]
fn auto_fit_rejects_overlapping_buffers_and_unbounded_rows() {
    let mut data = [12.0; 41];
    let mut forecast = [SENTINEL; 2];
    let mut row = 101;
    let ptr = data.as_mut_ptr();
    let result = unsafe {
        arboris_ets_trend_fit_auto(
            ptr,
            40,
            1,
            0.0,
            1,
            0.0,
            1.0,
            1,
            ptr.add(1),
            15,
            forecast.as_mut_ptr(),
            2,
            &mut row,
            None,
        )
    };
    assert_eq!(
        (result, data, forecast, row),
        (1, [12.0; 41], [SENTINEL; 2], 101)
    );
    let oversized = [12.0; 2001];
    assert_eq!(run(&oversized, None, None, 1.0, None).0, 6);
}
