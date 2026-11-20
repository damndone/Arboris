use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

use super::volatility::{
    best_candidate, certify_free_curvature, checkpoint, projected_gradient, region, search_bounded,
    Check, Evaluation, Failure, Matrix, Sample, Vector, GRADIENT_TOLERANCE, MAX_EVALUATIONS, WIDTH,
};

const MIN_TRAIN: usize = 50;
const MAX_ROWS: usize = 20_000;
const MAX_HOLDOUT: usize = 200;
const MAX_HORIZON: usize = 200;
const SUMMARY: usize = 19;
const DIMENSION: usize = 2;
const MIN_LOG_OMEGA: f64 = -18.420_680_743_952_367;
const MAX_LOG_OMEGA: f64 = std::f64::consts::LN_10;

fn project(point: Vector) -> Vector {
    [
        point[0].clamp(MIN_LOG_OMEGA, MAX_LOG_OMEGA),
        point[1].clamp(0.0, 1.0),
        0.0,
        0.0,
    ]
}

fn fixed_axes(point: &Vector, gradient: &Vector) -> [bool; WIDTH] {
    [
        (point[0] == MIN_LOG_OMEGA && gradient[0] >= 0.0)
            || (point[0] == MAX_LOG_OMEGA && gradient[0] <= 0.0),
        (point[1] == 0.0 && gradient[1] >= 0.0) || (point[1] == 1.0 && gradient[1] <= 0.0),
        true,
        true,
    ]
}

fn next_variance(omega: f64, alpha: f64, squared: f64, previous: f64) -> f64 {
    omega + alpha * squared + (1.0 - alpha) * previous
}

fn future_variance(first: f64, omega: f64, offset: usize) -> f64 {
    first + omega * offset as f64
}

fn likelihood(
    sample: &Sample,
    point: &Vector,
    curvature: bool,
    check: Check,
) -> Result<Evaluation, Failure> {
    let omega = point[0].exp();
    let alpha = point[1];
    let beta = 1.0 - alpha;
    let mut variance = omega + sample.backcast;
    let mut first = [omega, 0.0];
    let mut second = [[omega, 0.0], [0.0, 0.0]];
    let mut result = Evaluation {
        value: 0.0,
        gradient: [0.0; WIDTH],
        hessian: [[0.0; WIDTH]; WIDTH],
    };
    let weight = 0.5 / sample.shocks.len() as f64;
    for (row, &shock) in sample.shocks.iter().enumerate() {
        if row % 512 == 0 {
            checkpoint(check)?;
        }
        let squared = shock.abs();
        let ratio = squared / variance;
        result.value += weight * (variance.ln() + ratio);
        let slope = weight * (1.0 - ratio) / variance;
        for i in 0..DIMENSION {
            result.gradient[i] += slope * first[i];
        }
        if curvature {
            let curve = weight * (2.0 * ratio - 1.0) / (variance * variance);
            for i in 0..DIMENSION {
                for j in 0..DIMENSION {
                    result.hessian[i][j] += curve * first[i] * first[j] + slope * second[i][j];
                    second[i][j] *= beta;
                    if i == 1 {
                        second[i][j] -= first[j];
                    }
                    if j == 1 {
                        second[i][j] -= first[i];
                    }
                }
            }
            second[0][0] += omega;
        }
        first = [
            omega + beta * first[0],
            squared - variance + beta * first[1],
        ];
        variance = next_variance(omega, alpha, squared, variance);
    }
    if !result.value.is_finite()
        || !result.gradient.iter().all(|value| value.is_finite())
        || (curvature
            && !result
                .hessian
                .iter()
                .flatten()
                .all(|value| value.is_finite()))
    {
        return Err(Failure::Numeric);
    }
    Ok(result)
}

fn curvature(point: &Vector, hessian: &Matrix) -> Result<(f64, usize), Failure> {
    let mut basis = [[0.0; WIDTH]; WIDTH];
    let mut count = 0;
    let mut boundary = 0;
    for (i, (lower, upper)) in [(MIN_LOG_OMEGA, MAX_LOG_OMEGA), (0.0, 1.0)]
        .into_iter()
        .enumerate()
    {
        if point[i] - lower <= 1e-8 {
            boundary |= 1 << (2 * i);
        } else if upper - point[i] <= 1e-8 {
            boundary |= 1 << (2 * i + 1);
        } else {
            basis[count][i] = 1.0;
            count += 1;
        }
    }
    Ok((certify_free_curvature(hessian, &basis, count)?, boundary))
}

struct Estimate {
    point: Vector,
    loss: f64,
    gradient: f64,
    curvature: f64,
    boundary: usize,
    iterations: usize,
    evaluations: usize,
    converged_starts: usize,
}

fn estimate(sample: &Sample, check: Check) -> Result<Estimate, Failure> {
    let starts = [
        [0.03_f64.ln(), 0.08, 0.0, 0.0],
        [0.15_f64.ln(), 0.25, 0.0, 0.0],
        [0.45_f64.ln(), 0.65, 0.0, 0.0],
    ];
    let mut candidates = Vec::with_capacity(starts.len());
    for start in starts {
        candidates.push(search_bounded(
            DIMENSION,
            start,
            MAX_EVALUATIONS,
            &project,
            &fixed_axes,
            &|point| likelihood(sample, point, false, check),
        )?);
    }
    let best = best_candidate(&candidates)?;
    let evidence = likelihood(sample, &best.point, true, check)?;
    let gradient = projected_gradient(&best.point, &evidence.gradient, &project);
    if gradient > GRADIENT_TOLERANCE {
        return Err(Failure::Convergence);
    }
    let (curvature, boundary) = curvature(&best.point, &evidence.hessian)?;
    Ok(Estimate {
        point: best.point,
        loss: evidence.value,
        gradient,
        curvature,
        boundary,
        iterations: best.iterations,
        evaluations: 1 + candidates
            .iter()
            .map(|candidate| candidate.evaluations)
            .sum::<usize>(),
        converged_starts: candidates
            .iter()
            .filter(|candidate| candidate.converged)
            .count(),
    })
}

fn fit(
    values: &[f64],
    train: usize,
    forecasts: &mut [f64],
    check: Check,
) -> Result<[f64; SUMMARY], Failure> {
    for (row, value) in values.iter().enumerate() {
        if row % 512 == 0 {
            checkpoint(check)?;
        }
        if !value.is_finite() {
            return Err(Failure::Input(row));
        }
    }
    let (training, holdout) = values.split_at(train);
    let sample = Sample::new(training, false, check)?;
    let estimate = estimate(&sample, check)?;
    let omega = estimate.point[0].exp();
    let alpha = estimate.point[1];
    let beta = 1.0 - alpha;
    let raw_scale = sample.rms * sample.rms;
    let raw_omega = omega * raw_scale;
    if !raw_omega.is_finite() || raw_omega <= 0.0 {
        return Err(Failure::Numeric);
    }
    let initial = omega + sample.backcast;
    let mut variance = initial;
    let (mut mean, mut energy) = (0.0, 0.0);
    for (row, &shock) in sample.shocks.iter().enumerate() {
        if row % 512 == 0 {
            checkpoint(check)?;
        }
        let ratio = shock.abs() / variance;
        mean += ratio.sqrt().copysign(shock) / train as f64;
        energy += ratio / train as f64;
        variance = next_variance(omega, alpha, shock.abs(), variance);
    }
    let normal_shift = 0.5 * std::f64::consts::TAU.ln() + sample.rms.ln();
    let (heldout, future) = forecasts.split_at_mut(holdout.len());
    let (mut heldout_loss, mut heldout_mae) = (0.0, 0.0);
    for (&raw, forecast) in holdout.iter().zip(heldout) {
        checkpoint(check)?;
        let squared = (raw / sample.rms).powi(2);
        if !squared.is_finite() {
            return Err(Failure::Numeric);
        }
        *forecast = variance * raw_scale;
        let count = holdout.len() as f64;
        heldout_loss += (0.5 * (variance.ln() + squared / variance) + normal_shift) / count;
        heldout_mae += (squared - variance).abs() / count;
        variance = next_variance(omega, alpha, squared, variance);
    }
    for (offset, forecast) in future.iter_mut().enumerate() {
        *forecast = future_variance(variance, omega, offset) * raw_scale;
    }
    let result = [
        raw_omega,
        alpha,
        beta,
        1.0,
        omega,
        sample.backcast * raw_scale,
        sample.rms,
        -(estimate.loss + normal_shift) * train as f64,
        mean,
        energy.sqrt(),
        estimate.iterations as f64,
        estimate.evaluations as f64,
        estimate.gradient,
        estimate.curvature,
        estimate.boundary as f64,
        estimate.converged_starts as f64,
        heldout_loss,
        heldout_mae * raw_scale,
        initial * raw_scale,
    ];
    if !result.iter().all(|value| value.is_finite())
        || !forecasts
            .iter()
            .all(|&value| value.is_finite() && value > 0.0)
    {
        return Err(Failure::Numeric);
    }
    checkpoint(check)?;
    Ok(result)
}

/// Fits a Gaussian conditional IGARCH with exactly unit persistence.
///
/// # Safety
/// Pointers must reference valid buffers for the given lengths. Inputs remain
/// unchanged for the call, and the optional callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_igarch_fit(
    values: *const f64,
    rows: usize,
    train: usize,
    horizon: usize,
    summary: *mut f64,
    summary_len: usize,
    forecasts: *mut f64,
    forecasts_len: usize,
    error_row: *mut usize,
    check: Check,
) -> i32 {
    if rows > MAX_ROWS {
        return 6;
    }
    if train > rows
        || !(1..=MAX_HORIZON).contains(&horizon)
        || summary_len != SUMMARY
        || forecasts_len != rows - train + horizon
    {
        return 1;
    }
    if train < MIN_TRAIN {
        return 3;
    }
    if rows - train > MAX_HOLDOUT {
        return 6;
    }
    let [Some(input), Some(fit_region), Some(forecast_region), Some(error)] = [
        region(values, rows),
        region(summary, summary_len),
        region(forecasts, forecasts_len),
        region(error_row, 1),
    ] else {
        return 1;
    };
    let mut regions = [input, fit_region, forecast_region, error];
    regions.sort_unstable();
    if regions.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return 1;
    }
    unsafe { error_row.write(usize::MAX) };
    let result = catch_unwind(AssertUnwindSafe(|| {
        let input = unsafe { slice::from_raw_parts(values, rows) };
        let mut output = [0.0; MAX_HOLDOUT + MAX_HORIZON];
        let estimate = fit(input, train, &mut output[..forecasts_len], check)?;
        Ok::<_, Failure>((estimate, output))
    }));
    match result {
        Ok(Ok((estimate, output))) => {
            unsafe { slice::from_raw_parts_mut(summary, SUMMARY) }.copy_from_slice(&estimate);
            unsafe { slice::from_raw_parts_mut(forecasts, forecasts_len) }
                .copy_from_slice(&output[..forecasts_len]);
            0
        }
        Ok(Err(Failure::Input(row))) => {
            unsafe { error_row.write(row) };
            1
        }
        Ok(Err(Failure::Numeric)) => 2,
        Ok(Err(Failure::Degenerate)) => 4,
        Ok(Err(Failure::Convergence)) => 5,
        Ok(Err(Failure::Cancelled)) => 7,
        Err(_) => 8,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_boundary_recursion_and_future_variance() {
        assert_eq!(next_variance(0.125, 0.0, 9.0, 2.0), 2.125);
        assert_eq!(next_variance(0.125, 1.0, 9.0, 2.0), 9.125);
        let first = next_variance(0.125, 0.25, 9.0, 2.0);
        assert_eq!(first, 3.875);
        assert_eq!(future_variance(first, 0.125, 0), first);
        assert_eq!(future_variance(first, 0.125, 7), 4.75);
    }

    #[test]
    fn constrained_likelihood_derivatives_match_central_differences() {
        let values: Vec<_> = [1.0, -2.0, 2.0, -0.5, 0.75, -1.1, 0.1, 0.0]
            .into_iter()
            .cycle()
            .take(96)
            .collect();
        let sample = Sample::new(&values, false, None).unwrap();
        let theta = [0.05_f64.ln(), 0.21, 0.0, 0.0];
        let analytic = likelihood(&sample, &theta, true, None).unwrap();
        let step = 1e-6;
        for j in 0..DIMENSION {
            let mut p = theta;
            p[j] += step;
            let high = likelihood(&sample, &p, false, None).unwrap();
            p[j] -= 2.0 * step;
            let low = likelihood(&sample, &p, false, None).unwrap();
            assert!((analytic.gradient[j] - (high.value - low.value) / (2.0 * step)).abs() < 2e-8);
            for i in 0..DIMENSION {
                assert!(
                    (analytic.hessian[i][j] - (high.gradient[i] - low.gradient[i]) / (2.0 * step))
                        .abs()
                        < 2e-8
                );
            }
        }
    }
}
