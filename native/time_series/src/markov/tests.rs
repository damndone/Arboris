use super::*;

fn near(actual: f64, expected: f64, tolerance: f64) {
    assert!(
        (actual - expected).abs() <= tolerance,
        "expected {expected:.15}, got {actual:.15}"
    );
}

const SHORT: [f64; 4] = [-0.85, f64::NAN, 1.2, 0.05];
const PARAMETERS: Parameters = Parameters {
    means: [-1.1, 1.35],
    variance: 0.8,
    stay: [0.83, 0.72],
};

fn brute(
    values: &[f64],
    p: Parameters,
    path_length: usize,
    target: usize,
    observed_count: usize,
) -> ([f64; 2], f64) {
    let start = [1.0 - p.stay[1], 1.0 - p.stay[0]];
    let start_sum = start[0] + start[1];
    let density_scale = (std::f64::consts::TAU * p.variance).sqrt();
    let mut totals = [0.0; 2];
    for bits in 0..1_usize << path_length {
        let mut weight = 1.0;
        for t in 0..path_length {
            let current = (bits >> t) & 1;
            if t == 0 {
                weight *= start[current] / start_sum;
            } else {
                let previous = (bits >> (t - 1)) & 1;
                weight *= if current == previous {
                    p.stay[previous]
                } else {
                    1.0 - p.stay[previous]
                };
            }
            if t < observed_count && values[t].is_finite() {
                let error = values[t] - p.means[current];
                weight *= (-0.5 * error * error / p.variance).exp() / density_scale;
            }
        }
        totals[(bits >> target) & 1] += weight;
    }
    let evidence = totals[0] + totals[1];
    (totals.map(|value| value / evidence), evidence)
}

#[test]
fn short_gap_filter_smoother_and_future_agree_with_all_state_paths() {
    let mut filtered = [[0.0; 2]; 4];
    let mut trace = [[0.0; 6]; 4];
    let evaluation = expectation(&SHORT, PARAMETERS, &mut filtered, &mut trace, None).unwrap();
    near(evaluation.log_likelihood, -5.0995532165774975, 1e-13);
    for (t, row) in trace.iter().enumerate() {
        let (predicted, preceding) = brute(&SHORT, PARAMETERS, t + 1, t, t);
        let (filtered, evidence) = brute(&SHORT, PARAMETERS, t + 1, t, t + 1);
        let (smoothed, _) = brute(&SHORT, PARAMETERS, SHORT.len(), t, SHORT.len());
        near(row[0], predicted[0], 1e-13);
        near(row[1], filtered[0], 1e-13);
        near(row[2], smoothed[0], 1e-13);
        near(row[3], predicted[0] * -1.1 + predicted[1] * 1.35, 1e-13);
        near(
            row[4],
            0.8 + predicted[0] * predicted[1] * (1.35_f64 + 1.1).powi(2),
            1e-13,
        );
        near(row[5], (evidence / preceding).ln(), 1e-13);
    }
    assert_eq!(trace[1][0], trace[1][1]);
    assert_eq!(trace[1][5], 0.0);
    assert!((trace[0][1] - trace[0][2]).abs() > 0.02);
    let future = forecast(PARAMETERS, evaluation.last_filtered, 4);
    for (step, row) in future.iter().enumerate() {
        let t = SHORT.len() + step;
        let (weights, _) = brute(&SHORT, PARAMETERS, t + 1, t, SHORT.len());
        near(row[0], weights[0], 1e-13);
        near(row[1], weights[1], 1e-13);
        near(row[2], weights[0] * -1.1 + weights[1] * 1.35, 1e-13);
        near(
            row[3],
            0.8 + weights[0] * weights[1] * (1.35_f64 + 1.1).powi(2),
            1e-13,
        );
    }
    assert!((future[0][0] - evaluation.last_filtered[0]).abs() > 0.1);
}

#[test]
fn exact_score_includes_the_stationary_initial_law() {
    let point = PARAMETERS.point();
    let mut filtered = [[0.0; 2]; 4];
    let e = expectation(&SHORT, PARAMETERS, &mut filtered, &mut [], None).unwrap();
    let (_, gradient) = e.objective(PARAMETERS, 3).unwrap();
    for coordinate in 0..5 {
        let delta = 1e-5;
        let mut right = point;
        let mut left = point;
        right[coordinate] += delta;
        left[coordinate] -= delta;
        let value = |x| -brute(&SHORT, Parameters::from_point(x), 4, 3, 4).1.ln() / 3.0;
        near(
            gradient[coordinate],
            (value(right) - value(left)) / (2.0 * delta),
            2e-9,
        );
    }
}

fn gapped_fixture() -> Vec<f64> {
    let mut seed = 173_u64;
    let mut uniform = || {
        seed = (16807 * seed) % 2147483647;
        seed as f64 / 2147483647.0
    };
    let mut state = 0;
    let mut values = Vec::with_capacity(360);
    for _ in 0..360 {
        if uniform() > [0.86, 0.79][state] {
            state = 1 - state;
        }
        let noise = (0..12).map(|_| uniform()).sum::<f64>() - 6.0;
        values.push([-2.2, 2.9][state] + 0.72 * noise);
    }
    for index in [0, 39, 40, 71, 181, 358, 359] {
        values[index] = f64::NAN;
    }
    values
}

#[test]
fn gapped_fit_and_true_future_distribution_match_aligned_statsmodels() {
    let y = gapped_fixture();
    let result = fit(&y, 4, 5, None).unwrap();
    let head = result.header;
    assert!(head[0] < head[1]);
    assert_eq!(head[6], 353.0);
    near(head[0], -2.203280077255969, 2e-5);
    near(head[1], 2.868641473873381, 2e-5);
    near(head[2], 0.49835460551088145, 5e-6);
    near(head[3], 0.8327944801118383, 2e-5);
    near(head[4], 0.7728657002685493, 2e-5);
    near(head[5], -550.3659727296305, 1e-6);
    near(head[8], 204.9999112460634, 2e-5);
    near(head[9], 148.00008875393644, 2e-5);
    near(head[10], 0.3647005010414598, 2e-5);
    near(head[11], 0.6352994989585402, 2e-5);
    assert_eq!(result.trace.len(), 5);
    for (row, expected) in result.trace.iter().zip([
        [
            0.227134300329507,
            0.999996806351377,
            0.999985238328685,
            1.71663412103147,
            5.01412458444742,
            -3.43164232218920,
        ],
        [
            0.832792545846037,
            2.85749954595586e-15,
            6.18205342219783e-16,
            -1.35521698702301,
            4.08045306456530,
            -3.19432555271747,
        ],
        [
            0.227134299731453,
            9.92534066205655e-10,
            9.92534066205655e-10,
            1.71663412406475,
            5.01412457605157,
            -1.21320247582546,
        ],
        [
            0.227134300332589,
            0.227134300332589,
            0.227134300332589,
            1.71663412101584,
            5.01412458449069,
            0.0,
        ],
        [
            0.364700501041460,
            0.364700501041460,
            0.364700501041460,
            1.01890914293353,
            6.45854218250127,
            0.0,
        ],
    ]) {
        for (a, b) in row.iter().zip(expected) {
            near(*a, b, 6e-5);
        }
    }
    for (row, expected) in result.forecast.iter().zip([
        [
            0.448018870977039,
            0.551981129022961,
            0.596324906852297,
            6.85994339201489,
        ],
        [
            0.498481489941222,
            0.501518510058778,
            0.340382462201430,
            6.92939234354641,
        ],
        [
            0.529044688845535,
            0.470955311154465,
            0.185368315007189,
            6.90775072243949,
        ],
        [
            0.547555601406924,
            0.452444398593077,
            0.091482418656012,
            6.87127505060605,
        ],
    ]) {
        for (a, b) in row.iter().zip(expected) {
            near(*a, b, 6e-5);
        }
    }
}

#[test]
fn extreme_emission_log_weights_remain_finite() {
    let values = [-100.0, 100.0, f64::NAN, 200.0];
    let parameters = Parameters {
        variance: 1e-8,
        ..PARAMETERS
    };
    let mut filtered = [[0.0; 2]; 4];
    let mut trace = [[0.0; 6]; 4];
    let e = expectation(&values, parameters, &mut filtered, &mut trace, None).unwrap();
    assert!(e.log_likelihood.is_finite());
    for row in trace {
        assert!(row.iter().all(|v| v.is_finite()));
        assert!(row[..3].iter().all(|p| (0.0..=1.0).contains(p)));
    }
}

#[test]
fn short_or_collapsed_fits_are_refused() {
    assert!(matches!(
        fit(&[0.0; 23], 1, 0, None),
        Err(Failure::Insufficient)
    ));
    assert!(matches!(
        fit(&[0.0; 25], 1, 0, None),
        Err(Failure::Degenerate)
    ));
    let two_levels: Vec<f64> = (0..25).map(|t| (t % 2) as f64).collect();
    assert!(matches!(
        fit(&two_levels, 1, 0, None),
        Err(Failure::Degenerate)
    ));
}

#[test]
fn statistically_equal_but_materially_distinct_candidates_fail_closed() {
    let mut starts = [[0.0; DIMENSIONS]; STARTS];
    for (index, start) in starts.iter_mut().enumerate() {
        start[0] = if index % 2 == 0 { -1.0 } else { 1.0 };
    }
    let result = optimizer::minimize(starts, 32, |point| {
        let well = point[0] * point[0] - 1.0;
        let value = well * well + point[1..].iter().map(|value| value * value).sum::<f64>();
        let mut gradient = point.map(|value| 2.0 * value);
        gradient[0] = 4.0 * point[0] * well;
        Ok((value, gradient))
    });
    assert!(matches!(result, Err(Failure::Degenerate)));
}

#[test]
fn affine_scaling_preserves_regime_probabilities_and_rescales_the_density() {
    let original = gapped_fixture();
    let baseline = fit(&original, 3, 4, None).unwrap();
    for scale in [1e-100_f64, 1e100_f64] {
        let values: Vec<_> = original
            .iter()
            .map(|&value| scale * (value + 9.0))
            .collect();
        let changed = fit(&values, 3, 4, None).unwrap();
        near(changed.header[0] / scale - 9.0, baseline.header[0], 2e-6);
        near(changed.header[1] / scale - 9.0, baseline.header[1], 2e-6);
        near(changed.header[2] / scale / scale, baseline.header[2], 2e-6);
        near(changed.header[3], baseline.header[3], 2e-6);
        near(changed.header[4], baseline.header[4], 2e-6);
        near(
            changed.header[5] + baseline.header[6] * scale.ln(),
            baseline.header[5],
            1e-6,
        );
        for (value, reference) in changed.forecast.iter().zip(&baseline.forecast) {
            near(value[0], reference[0], 2e-6);
            near(value[1], reference[1], 2e-6);
            near(value[2] / scale - 9.0, reference[2], 2e-6);
            near(value[3] / scale / scale, reference[3], 2e-6);
        }
    }
}

#[test]
fn ffi_checks_aliases_and_preserves_outputs_on_cancel() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static POLLS: AtomicUsize = AtomicUsize::new(0);
    extern "C" fn cancel() -> i32 {
        i32::from(POLLS.fetch_add(1, Ordering::Relaxed) >= 8)
    }
    let mut y = gapped_fixture();
    let mut summary = [-1.0; 12];
    let mut trace = [-2.0; 18];
    let mut future = [-3.0; 8];
    let mut error = 99;
    let y_before = y.iter().map(|v| v.to_bits()).collect::<Vec<_>>();
    let status = unsafe {
        arboris_markov_switching_fit(
            y.as_ptr(),
            y.len(),
            2,
            3,
            y.as_mut_ptr(),
            12,
            trace.as_mut_ptr(),
            trace.len(),
            future.as_mut_ptr(),
            future.len(),
            &mut error,
            None,
        )
    };
    assert_eq!(status, 1);
    assert_eq!(error, 99);
    assert_eq!(y.iter().map(|v| v.to_bits()).collect::<Vec<_>>(), y_before);
    let status = unsafe {
        arboris_markov_switching_fit(
            y.as_ptr(),
            y.len(),
            2,
            3,
            summary.as_mut_ptr(),
            summary.len(),
            trace.as_mut_ptr(),
            trace.len(),
            future.as_mut_ptr(),
            future.len(),
            &mut error,
            Some(cancel),
        )
    };
    assert_eq!(status, 7);
    assert_eq!(POLLS.load(Ordering::Relaxed), 9);
    assert_eq!(summary, [-1.0; 12]);
    assert_eq!(trace, [-2.0; 18]);
    assert_eq!(future, [-3.0; 8]);
}
