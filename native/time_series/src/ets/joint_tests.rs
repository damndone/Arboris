use super::*;

fn simulated() -> Vec<f64> {
    let mut seed = 775_u64;
    let mut phases = [-2.0, 0.5, 1.0, 0.5];
    let (mut level, mut trend) = (15.0, 0.4);
    (0..152)
        .map(|index| {
            let innovation = (0..12)
                .map(|_| {
                    seed = seed * 16807 % 2147483647;
                    seed as f64 / 2147483647.0
                })
                .sum::<f64>()
                - 6.0;
            let phase = index % 4;
            let baseline = level + trend;
            let y = baseline + phases[phase] + innovation;
            level = baseline + 0.38 * innovation;
            trend += 0.38 * 0.25 * innovation;
            phases[phase] += (1.0 - 0.38) * 0.53 * innovation;
            y
        })
        .collect()
}

fn run(values: &[f64], check: CancellationCheck) -> (i32, Vec<f64>, usize) {
    let mut output = vec![-99.0; 8 + 6 + 8 + 5 * (values.len() - 8) + 16];
    let mut row = usize::MAX;
    let status = unsafe {
        arboris_holt_winters_fit_joint(
            values.as_ptr(),
            values.len(),
            4,
            8,
            output.as_mut_ptr(),
            output.len(),
            &mut row,
            check,
        )
    };
    (status, output, row)
}

#[test]
fn jointly_estimates_three_gains_with_r_conditional_sse() {
    let (status, out, row) = run(&simulated(), None);
    assert_eq!((status, row), (0, usize::MAX));
    let gains = [0.44066600468412837, 0.2608600697847554, 0.41492285816608288];
    for (actual, expected) in out[..3].iter().zip(gains) {
        assert!((actual - expected).abs() <= 3e-7);
    }
    assert!((out[12] - 145.39748729528628).abs() <= 1e-9);
    assert!((out[13] - 1.0149756485480694).abs() <= 3e-7);
    assert!(out[4] <= 1e-7 && out[5] > 1e-4 && out[6] > 1e-7 && out[7] >= 2.0);
    assert!(out.iter().all(|value| value.is_finite()));
}

#[test]
fn incomplete_and_degenerate_samples_refuse_without_outputs() {
    let mut gap = simulated();
    gap[28] = f64::NAN;
    let deterministic = (0..160)
        .map(|i| 2.0 + i as f64 * 0.25 + [-1.5, -0.5, 0.5, 1.5][i % 4])
        .collect::<Vec<_>>();
    for (values, want, row) in [
        (gap, 3, 28),
        (vec![5.0; 160], 6, usize::MAX),
        (deterministic, 6, usize::MAX),
    ] {
        let (status, out, actual_row) = run(&values, None);
        assert_eq!((status, actual_row), (want, row));
        assert!(out.iter().all(|value| *value == -99.0));
    }
}

#[test]
fn owner_cancels_inside_search_before_any_output() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static POLLS: AtomicUsize = AtomicUsize::new(0);
    extern "C" fn stop() -> i32 {
        i32::from(POLLS.fetch_add(1, Ordering::SeqCst) == 12)
    }
    let (status, out, _) = run(&simulated(), Some(stop));
    assert_eq!(status, 5);
    assert_eq!(POLLS.load(Ordering::SeqCst), 13);
    assert!(out.iter().all(|value| *value == -99.0));
}

#[test]
fn overlapping_native_output_refuses_before_reading_or_writing() {
    let count = 152;
    let len = PREFIX + output_length(count, 4, 8);
    let mut shared = vec![-99.0; count + len];
    let pointer = shared.as_mut_ptr();
    let mut error = 321;
    let status = unsafe {
        arboris_holt_winters_fit_joint(pointer, count, 4, 8, pointer.add(1), len, &mut error, None)
    };
    assert_eq!(status, INVALID_INPUT);
    assert_eq!(error, 321);
    assert!(shared.iter().all(|&value| value == -99.0));
}

#[test]
fn analytic_gradient_matches_richardson_approximation() {
    let observations = simulated();
    let initial = initialize(&observations, 4).ok().unwrap();
    let mut objective = Objective {
        observations: &observations,
        initial: &initial,
        check: None,
        evaluations: 0,
    };
    for point in [[0.12, 0.06, 0.81], [0.44, 0.26, 0.41], [0.8, 0.58, 0.17]] {
        let analytic = objective.at(point).ok().unwrap().gradient;
        for (i, exact) in analytic.into_iter().enumerate() {
            let mut slope = |h| {
                let mut left = point;
                let mut right = point;
                left[i] -= h;
                right[i] += h;
                let a = objective.at(left).ok().unwrap().value;
                let b = objective.at(right).ok().unwrap().value;
                (b - a) / (2.0 * h)
            };
            let observed = (4.0 * slope(1e-5) - slope(2e-5)) / 3.0;
            assert!((observed - exact).abs() <= 1e-7 * exact.abs().max(1.0));
        }
    }
}

#[test]
fn normalized_objective_preserves_affine_fit_and_forecast() {
    let values = simulated();
    let shifted = values.iter().map(|v| 1e6 + 64.0 * v).collect::<Vec<_>>();
    let (status, before, _) = run(&values, None);
    assert_eq!(status, 0);
    let (status, after, _) = run(&shifted, None);
    assert_eq!(status, 0);
    for (&a, &b) in before[..3].iter().zip(&after[..3]) {
        assert!((a - b).abs() <= 2e-7);
    }
    let forecast_offset = before.len() - 16;
    for (a, b) in before[forecast_offset..]
        .chunks_exact(2)
        .zip(after[forecast_offset..].chunks_exact(2))
    {
        assert!((a[0] - (b[0] - 1e6) / 64.0).abs() <= 1e-7);
        assert!((a[1] - b[1] / 4096.0).abs() <= 1e-7);
    }
}
