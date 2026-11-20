use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

use super::volatility::{
    best_candidate, certify_free_curvature, checkpoint, projected_gradient, region, search_bounded,
    Check, Evaluation, Failure, Matrix, Sample, Vector, GRADIENT_TOLERANCE, MAX_EVALUATIONS, WIDTH,
};

const MIN_TRAIN: usize = 50;
const MAX_ROWS: usize = 20_000;
const MAX_HOLDOUT: usize = 200;
const SUMMARY: usize = 19;
const CENTER: f64 = 0.797_884_560_802_865_4;
const MAX_LOG_VARIANCE: f64 = 40.0;
const LOWER: Vector = [-2.0, -1.0, -1.0, 0.0];
const UPPER: Vector = [2.0, 1.0, 1.0, 0.995];
const STARTS: [Vector; 4] = [
    [0.0, 0.12, -0.12, 0.75],
    [-0.05, 0.25, 0.10, 0.60],
    [0.0, 0.15, 0.0, 0.94],
    [0.0, 0.0, 0.0, 0.0],
];

fn project(point: Vector) -> Vector {
    std::array::from_fn(|i| point[i].clamp(LOWER[i], UPPER[i]))
}

fn fixed_axes(point: &Vector, gradient: &Vector) -> [bool; WIDTH] {
    std::array::from_fn(|i| {
        (point[i] == LOWER[i] && gradient[i] >= 0.0) || (point[i] == UPPER[i] && gradient[i] <= 0.0)
    })
}

fn standardized(observed: f64, log_variance: f64) -> Result<f64, Failure> {
    if !log_variance.is_finite() || log_variance.abs() > MAX_LOG_VARIANCE {
        return Err(Failure::Numeric);
    }
    let value = observed * (-0.5 * log_variance).exp();
    if !value.is_finite() || !(value * value).is_finite() {
        return Err(Failure::Numeric);
    }
    Ok(value)
}

fn next_variance(parameters: &Vector, state: f64, innovation: f64) -> f64 {
    let [omega, alpha, gamma, beta] = *parameters;
    omega + alpha * (innovation.abs() - CENTER) + gamma * innovation + beta * state
}

struct Data {
    normalized: Vec<f64>,
    rms: f64,
    log_backcast: f64,
}

impl Data {
    fn training(values: &[f64], check: Check) -> Result<Self, Failure> {
        let sample = Sample::new(values, true, check)?;
        if sample.backcast <= 0.0 {
            return Err(Failure::Degenerate);
        }
        let mut normalized = sample.shocks;
        for (scaled, raw) in normalized.iter_mut().zip(values) {
            *scaled = raw / sample.rms;
        }
        Ok(Self {
            normalized,
            rms: sample.rms,
            log_backcast: sample.backcast.ln(),
        })
    }

    fn likelihood(
        &self,
        point: &Vector,
        curvature: bool,
        check: Check,
    ) -> Result<Evaluation, Failure> {
        let [omega, alpha, gamma, beta] = *point;
        let mut state = omega + beta * self.log_backcast;
        let mut first = [1.0, 0.0, 0.0, self.log_backcast];
        let mut second = [[0.0; WIDTH]; WIDTH];
        let mut result = Evaluation {
            value: 0.0,
            gradient: [0.0; WIDTH],
            hessian: [[0.0; WIDTH]; WIDTH],
        };
        let weight = 0.5 / self.normalized.len() as f64;
        for (row, &observed) in self.normalized.iter().enumerate() {
            if row % 512 == 0 {
                checkpoint(check)?;
            }
            let z = standardized(observed, state)?;
            let squared = z * z;
            result.value += weight * (state + squared);
            let loss_gradient = weight * (1.0 - squared);
            let absolute = z.abs();
            let response = alpha * absolute + gamma * z;
            let lag_gradient = beta - 0.5 * response;
            let direct = [1.0, absolute - CENTER, z, state];
            for i in 0..WIDTH {
                result.gradient[i] += loss_gradient * first[i];
            }
            if curvature {
                let mixed = [0.0, -0.5 * absolute, -0.5 * z, 1.0];
                for i in 0..WIDTH {
                    for j in 0..WIDTH {
                        result.hessian[i][j] +=
                            weight * squared * first[i] * first[j] + loss_gradient * second[i][j];
                        second[i][j] = lag_gradient * second[i][j]
                            + 0.25 * response * first[i] * first[j]
                            + mixed[i] * first[j]
                            + mixed[j] * first[i];
                    }
                }
            }
            state = next_variance(point, state, z);
            for i in 0..WIDTH {
                first[i] = direct[i] + lag_gradient * first[i];
            }
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
}

fn curvature(point: &Vector, hessian: &Matrix) -> Result<(f64, usize), Failure> {
    let mut basis = [[0.0; WIDTH]; WIDTH];
    let mut count = 0;
    let mut boundary = 0;
    for i in 0..WIDTH {
        if point[i] - LOWER[i] <= 1e-8 {
            boundary |= 1 << (2 * i);
        } else if UPPER[i] - point[i] <= 1e-8 {
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

fn estimate(data: &Data, check: Check) -> Result<Estimate, Failure> {
    let mut candidates = Vec::with_capacity(STARTS.len());
    let mut invalid_starts = 0;
    for start in STARTS {
        match search_bounded(
            WIDTH,
            start,
            MAX_EVALUATIONS,
            &project,
            &fixed_axes,
            &|point| data.likelihood(point, false, check),
        ) {
            Ok(candidate) => candidates.push(candidate),
            Err(Failure::Numeric) => invalid_starts += 1,
            Err(failure) => return Err(failure),
        }
    }
    if candidates.is_empty() {
        return Err(Failure::Numeric);
    }
    let best = best_candidate(&candidates)?;
    let evidence = data.likelihood(&best.point, true, check)?;
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
        evaluations: 1
            + invalid_starts
            + candidates
                .iter()
                .map(|candidate| candidate.evaluations)
                .sum::<usize>(),
        converged_starts: candidates
            .iter()
            .filter(|candidate| candidate.converged)
            .count(),
    })
}

fn raw_forecast(normalized_log: f64, log_scale: f64, output: &mut [f64]) -> Result<(), Failure> {
    if !normalized_log.is_finite() || normalized_log.abs() > MAX_LOG_VARIANCE {
        return Err(Failure::Numeric);
    }
    let raw_log = normalized_log + log_scale;
    let variance = raw_log.exp();
    if !variance.is_finite() || variance <= 0.0 {
        return Err(Failure::Numeric);
    }
    output.copy_from_slice(&[raw_log, variance]);
    Ok(())
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
    let data = Data::training(training, check)?;
    let estimate = estimate(&data, check)?;
    let [omega, alpha, gamma, beta] = estimate.point;
    let log_scale = 2.0 * data.rms.ln();
    let raw_scale = data.rms * data.rms;
    let initial = omega + beta * data.log_backcast;
    let mut state = initial;
    let (mut z_mean, mut z_squared) = (0.0, 0.0);
    for (row, &value) in data.normalized.iter().enumerate() {
        if row % 512 == 0 {
            checkpoint(check)?;
        }
        let z = standardized(value, state)?;
        z_mean += z / train as f64;
        z_squared += z * z / train as f64;
        state = next_variance(&estimate.point, state, z);
    }
    let gaussian_shift = 0.5 * (std::f64::consts::TAU.ln() + log_scale);
    let (mut holdout_loss, mut holdout_mae) = (0.0, 0.0);
    for (&raw, output) in holdout.iter().zip(forecasts.chunks_exact_mut(2)) {
        checkpoint(check)?;
        raw_forecast(state, log_scale, output)?;
        let value = raw / data.rms;
        let z = standardized(value, state)?;
        holdout_loss += (0.5 * (state + z * z) + gaussian_shift) / holdout.len() as f64;
        holdout_mae += (value * value - state.exp()).abs() / holdout.len() as f64;
        state = next_variance(&estimate.point, state, z);
    }
    raw_forecast(state, log_scale, &mut forecasts[2 * holdout.len()..])?;
    let result = [
        omega + (1.0 - beta) * log_scale,
        alpha,
        gamma,
        beta,
        omega,
        data.log_backcast + log_scale,
        data.rms,
        -(estimate.loss + gaussian_shift) * train as f64,
        z_mean,
        z_squared.sqrt(),
        estimate.iterations as f64,
        estimate.evaluations as f64,
        estimate.gradient,
        estimate.curvature,
        estimate.boundary as f64,
        estimate.converged_starts as f64,
        holdout_loss,
        holdout_mae * raw_scale,
        initial + log_scale,
    ];
    if !result.iter().all(|value| value.is_finite()) {
        return Err(Failure::Numeric);
    }
    checkpoint(check)?;
    Ok(result)
}

/// Fits zero-mean Gaussian EGARCH and returns rolling and future one-step variance pairs.
///
/// # Safety
/// Pointers must reference valid buffers for their declared lengths. The input must remain
/// unchanged and the optional callback must not unwind across the C boundary.
#[no_mangle]
pub unsafe extern "C" fn arboris_egarch_fit(
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
        || horizon != 1
        || summary_len != SUMMARY
        || forecasts_len != 2 * (rows - train + horizon)
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
        let mut output = [0.0; 2 * (MAX_HOLDOUT + 1)];
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
    fn signed_news_is_a_log_variance_difference() {
        let parameters = [-0.1, 0.2, -0.15, 0.8];
        let up = next_variance(&parameters, 0.5, 2.0);
        let down = next_variance(&parameters, 0.5, -2.0);
        assert!((down - up - 0.6).abs() < 1e-14);
        assert!((down.exp() / up.exp() - 0.6_f64.exp()).abs() < 1e-14);
        assert!(matches!(standardized(1.0, -41.0), Err(Failure::Numeric)));
    }

    #[test]
    fn log_variance_likelihood_derivatives_match_central_differences() {
        let values: Vec<_> = [1.0, -2.0, 2.0, -0.5, 0.75, -1.1, 0.1, 0.0]
            .into_iter()
            .cycle()
            .take(96)
            .collect();
        let data = Data::training(&values, None).unwrap();
        let theta = [-0.05, 0.21, -0.15, 0.7];
        let analytic = data.likelihood(&theta, true, None).unwrap();
        let step = 1e-6;
        for j in 0..WIDTH {
            let mut p = theta;
            p[j] += step;
            let high = data.likelihood(&p, false, None).unwrap();
            p[j] -= 2.0 * step;
            let low = data.likelihood(&p, false, None).unwrap();
            assert!((analytic.gradient[j] - (high.value - low.value) / (2.0 * step)).abs() < 2e-8);
            for i in 0..WIDTH {
                assert!(
                    (analytic.hessian[i][j] - (high.gradient[i] - low.gradient[i]) / (2.0 * step))
                        .abs()
                        < 2e-8
                );
            }
        }
    }
}
