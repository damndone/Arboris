use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

const MIN_TRAIN: usize = 50;
const MAX_ROWS: usize = 20_000;
const MAX_HORIZON: usize = 200;
const MAX_HOLDOUT: usize = 200;
const SUMMARY: usize = 19;
pub(super) const WIDTH: usize = 4;
const STARTS: usize = 3;
const MAX_ITERATIONS: usize = 100;
pub(super) const MAX_EVALUATIONS: usize = 256;
const MAX_PERSISTENCE: f64 = 0.999;
const MIN_LOG_OMEGA: f64 = -18.420_680_743_952_367;
const MAX_LOG_OMEGA: f64 = std::f64::consts::LN_10;
pub(super) const GRADIENT_TOLERANCE: f64 = 1e-7;
const OBJECTIVE_TIE: f64 = 1e-9;

pub(super) type Vector = [f64; WIDTH];
pub(super) type Matrix = [Vector; WIDTH];
pub(super) type Check = Option<extern "C" fn() -> i32>;

#[derive(Clone, Copy, Debug, PartialEq)]
pub(super) enum Failure {
    Input(usize),
    Numeric,
    Degenerate,
    Convergence,
    Cancelled,
}

#[derive(Clone, Copy, Debug)]
enum Family {
    Arch = 0,
    Garch = 1,
    Gjr = 2,
}

impl Family {
    fn dimension(self) -> usize {
        self as usize + 2
    }

    fn beta(self, point: &Vector) -> f64 {
        match self {
            Self::Arch => 0.0,
            Self::Garch => point[2],
            Self::Gjr => point[3],
        }
    }

    fn terms(self, shock: f64, variance: f64) -> Vector {
        let squared = shock.abs();
        match self {
            Self::Arch => [0.0, squared, 0.0, 0.0],
            Self::Garch => [0.0, squared, variance, 0.0],
            Self::Gjr if shock < 0.0 => [0.0, 0.0, 2.0 * squared, variance],
            Self::Gjr => [0.0, 2.0 * squared, 0.0, variance],
        }
    }

    fn coefficients(self, point: &Vector) -> (f64, f64, f64) {
        let (alpha, gamma) = match self {
            Self::Gjr => (2.0 * point[1], 2.0 * (point[2] - point[1])),
            _ => (point[1], 0.0),
        };
        (alpha, gamma, self.beta(point))
    }

    fn starts(self) -> [Vector; STARTS] {
        let dynamics = match self {
            Self::Arch => [[0.05, 0.0, 0.0], [0.35, 0.0, 0.0], [0.70, 0.0, 0.0]],
            Self::Garch => [[0.10, 0.70, 0.0], [0.25, 0.30, 0.0], [0.03, 0.94, 0.0]],
            Self::Gjr => [[0.05, 0.10, 0.70], [0.15, 0.05, 0.45], [0.02, 0.04, 0.90]],
        };
        dynamics.map(|[a, b, c]| [(1.0_f64 - a - b - c).ln(), a, b, c])
    }
}

pub(super) fn checkpoint(check: Check) -> Result<(), Failure> {
    if check.is_some_and(|poll| poll() != 0) {
        return Err(Failure::Cancelled);
    }
    Ok(())
}

pub(super) struct Sample {
    pub(super) shocks: Vec<f64>,
    pub(super) rms: f64,
    pub(super) backcast: f64,
}

fn signed_square(value: f64, rms: f64) -> Result<f64, Failure> {
    let scaled = value / rms;
    let squared = scaled * scaled;
    if !squared.is_finite() {
        return Err(Failure::Numeric);
    }
    Ok(squared.copysign(scaled))
}

impl Sample {
    pub(super) fn new(
        training: &[f64],
        require_both_signs: bool,
        check: Check,
    ) -> Result<Self, Failure> {
        let (mut largest, mut smallest) = (0.0_f64, f64::INFINITY);
        for value in training {
            largest = largest.max(value.abs());
            smallest = smallest.min(value.abs());
        }
        if largest == smallest {
            return Err(Failure::Degenerate);
        }
        if require_both_signs {
            let lagged = &training[..training.len() - 1];
            if !lagged.iter().any(|&value| value < 0.0) || !lagged.iter().any(|&value| value > 0.0)
            {
                return Err(Failure::Degenerate);
            }
        }
        let n = training.len() as f64;
        let mean_square = training
            .iter()
            .map(|value| (value / largest).powi(2) / n)
            .sum::<f64>();
        let rms = largest * mean_square.sqrt();
        let raw_variance = rms * rms;
        if !raw_variance.is_finite() || raw_variance == 0.0 {
            return Err(Failure::Numeric);
        }
        let mut shocks = Vec::with_capacity(training.len());
        for (i, &value) in training.iter().enumerate() {
            if i % 512 == 0 {
                checkpoint(check)?;
            }
            shocks.push(signed_square(value, rms)?);
        }
        let (mut weight, mut weights, mut weighted) = (1.0, 0.0, 0.0);
        for shock in shocks.iter().take(75) {
            weights += weight;
            weighted += weight * shock.abs();
            weight *= 0.94;
        }
        Ok(Self {
            shocks,
            rms,
            backcast: weighted / weights,
        })
    }
}

fn dot(left: &Vector, right: &Vector) -> f64 {
    left.iter().zip(right).map(|(a, b)| a * b).sum()
}

fn max_abs(vector: &Vector) -> f64 {
    vector.iter().map(|value| value.abs()).fold(0.0, f64::max)
}

fn persistence(point: &Vector) -> f64 {
    point[1..].iter().sum()
}

fn project(mut point: Vector, dimension: usize) -> Vector {
    point[0] = point[0].clamp(MIN_LOG_OMEGA, MAX_LOG_OMEGA);
    for value in &mut point[1..dimension] {
        *value = value.max(0.0);
    }
    if persistence(&point) <= MAX_PERSISTENCE {
        return point;
    }
    let mut sorted = [0.0; WIDTH - 1];
    let count = dimension - 1;
    sorted[..count].copy_from_slice(&point[1..dimension]);
    sorted[..count].sort_unstable_by(|a, b| b.total_cmp(a));
    let (mut running, mut threshold) = (0.0, 0.0);
    for (i, &value) in sorted[..count].iter().enumerate() {
        running += value;
        let level = (running - MAX_PERSISTENCE) / (i + 1) as f64;
        if value <= level {
            break;
        }
        threshold = level;
    }
    for value in &mut point[1..dimension] {
        *value = (*value - threshold).max(0.0);
    }
    let total = persistence(&point);
    if total > MAX_PERSISTENCE {
        for value in &mut point[1..dimension] {
            *value *= MAX_PERSISTENCE / total;
        }
    }
    point
}

fn bounded_step(
    point: &Vector,
    direction: &Vector,
    project: &impl Fn(Vector) -> Vector,
) -> (Vector, f64) {
    let step = 1.0_f64.min(2.0 / max_abs(direction));
    let next = project(std::array::from_fn(|i| point[i] + step * direction[i]));
    (std::array::from_fn(|i| next[i] - point[i]), step)
}

pub(super) fn projected_gradient(
    point: &Vector,
    gradient: &Vector,
    project: &impl Fn(Vector) -> Vector,
) -> f64 {
    let (movement, step) = bounded_step(point, &gradient.map(|value| -value), project);
    max_abs(&movement) / step
}

fn gradient_norm(point: &Vector, gradient: &Vector, dimension: usize) -> f64 {
    projected_gradient(point, gradient, &|p| project(p, dimension))
}

pub(super) struct Evaluation {
    pub(super) value: f64,
    pub(super) gradient: Vector,
    pub(super) hessian: Matrix,
}

fn evaluate(
    sample: &Sample,
    family: Family,
    point: &Vector,
    curvature: bool,
    check: Check,
) -> Result<Evaluation, Failure> {
    let dimension = family.dimension();
    let omega = point[0].exp();
    let beta = family.beta(point);
    let mut variance = omega + persistence(point) * sample.backcast;
    let mut derivative = [0.0; WIDTH];
    derivative[..dimension].fill(sample.backcast);
    derivative[0] = omega;
    let mut second = [[0.0; WIDTH]; WIDTH];
    second[0][0] = omega;
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
        let ratio = shock.abs() / variance;
        result.value += weight * (variance.ln() + ratio);
        let slope = weight * (1.0 - ratio) / variance;
        for i in 0..dimension {
            result.gradient[i] += slope * derivative[i];
        }
        let mut terms = family.terms(shock, variance);
        if curvature {
            let curve = weight * (2.0 * ratio - 1.0) / (variance * variance);
            let beta_index = if matches!(family, Family::Arch) {
                WIDTH
            } else {
                dimension - 1
            };
            for i in 0..dimension {
                for j in 0..dimension {
                    result.hessian[i][j] +=
                        curve * derivative[i] * derivative[j] + slope * second[i][j];
                    second[i][j] *= beta;
                    if i == beta_index {
                        second[i][j] += derivative[j];
                    }
                    if j == beta_index {
                        second[i][j] += derivative[i];
                    }
                }
            }
            second[0][0] += omega;
        }
        variance = omega + dot(point, &terms);
        terms[0] = omega;
        for i in 0..dimension {
            derivative[i] = terms[i] + beta * derivative[i];
        }
    }
    if !result.value.is_finite() || !result.gradient.iter().all(|value| value.is_finite()) {
        return Err(Failure::Numeric);
    }
    Ok(result)
}

fn identity() -> Matrix {
    std::array::from_fn(|i| std::array::from_fn(|j| if i == j { 1.0 } else { 0.0 }))
}

fn update_inverse(inverse: &mut Matrix, step: &Vector, change: &Vector, dimension: usize) {
    let product = dot(step, change);
    if product <= 1e-12 * dot(step, step) {
        *inverse = identity();
        return;
    }
    let transformed = inverse.map(|row| dot(&row, change));
    let scale = (1.0 + dot(change, &transformed) / product) / product;
    for i in 0..dimension {
        for j in 0..dimension {
            inverse[i][j] += scale * step[i] * step[j]
                - (transformed[i] * step[j] + step[i] * transformed[j]) / product;
        }
    }
    if !inverse.iter().flatten().all(|value| value.is_finite()) {
        *inverse = identity();
    }
}

pub(super) struct Candidate {
    pub(super) point: Vector,
    pub(super) evaluation: Evaluation,
    pub(super) iterations: usize,
    pub(super) evaluations: usize,
    pub(super) converged: bool,
}

fn fixed_axes(point: &Vector, gradient: &Vector, dimension: usize) -> [bool; WIDTH] {
    std::array::from_fn(|i| {
        i >= dimension
            || if i == 0 {
                (point[0] == MIN_LOG_OMEGA && gradient[0] >= 0.0)
                    || (point[0] == MAX_LOG_OMEGA && gradient[0] <= 0.0)
            } else {
                point[i] == 0.0 && gradient[i] >= 0.0
            }
    })
}

fn search(
    sample: &Sample,
    family: Family,
    start: Vector,
    budget: usize,
    check: Check,
) -> Result<Candidate, Failure> {
    let dimension = family.dimension();
    search_bounded(
        dimension,
        start,
        budget,
        &|p| project(p, dimension),
        &|p, g| fixed_axes(p, g, dimension),
        &|p| evaluate(sample, family, p, false, check),
    )
}

pub(super) fn search_bounded(
    dimension: usize,
    start: Vector,
    budget: usize,
    project: &impl Fn(Vector) -> Vector,
    fixed: &impl Fn(&Vector, &Vector) -> [bool; WIDTH],
    evaluate: &impl Fn(&Vector) -> Result<Evaluation, Failure>,
) -> Result<Candidate, Failure> {
    let mut result = Candidate {
        point: start,
        evaluation: evaluate(&start)?,
        iterations: 0,
        evaluations: 1,
        converged: false,
    };
    let mut inverse = identity();
    for _ in 0..=MAX_ITERATIONS {
        let current = &result.evaluation;
        let norm = projected_gradient(&result.point, &current.gradient, project);
        if norm <= GRADIENT_TOLERANCE {
            result.converged = true;
            break;
        }
        if result.iterations == MAX_ITERATIONS || result.evaluations >= budget {
            break;
        }
        let active = fixed(&result.point, &current.gradient);
        let face_gradient =
            std::array::from_fn(|i| if active[i] { 0.0 } else { current.gradient[i] });
        let quasi_newton = std::array::from_fn(|i| {
            if active[i] {
                0.0
            } else {
                -dot(&inverse[i], &face_gradient)
            }
        });
        let steepest = current.gradient.map(|value| -value);
        let mut accepted = None;
        for raw_direction in [quasi_newton, steepest] {
            if !raw_direction.iter().all(|value| value.is_finite()) {
                continue;
            }
            let (direction, _) = bounded_step(&result.point, &raw_direction, project);
            let slope = dot(&direction, &current.gradient);
            if slope >= 0.0 || !slope.is_finite() {
                continue;
            }
            let mut fraction = 1.0;
            let roundoff = 16.0 * f64::EPSILON * (1.0 + current.value.abs());
            for _ in 0..24 {
                if result.evaluations >= budget {
                    break;
                }
                let point = project(std::array::from_fn(|i| {
                    result.point[i] + fraction * direction[i]
                }));
                result.evaluations += 1;
                match evaluate(&point) {
                    Ok(next) => {
                        let decrease = -fraction * slope;
                        let armijo = next.value < current.value
                            && next.value <= current.value - 1e-4 * decrease;
                        let precise = decrease <= roundoff
                            && next.value <= current.value + roundoff
                            && projected_gradient(&point, &next.gradient, project) < norm;
                        if armijo || precise {
                            accepted = Some((point, next));
                            break;
                        }
                    }
                    Err(Failure::Numeric) => {}
                    Err(failure) => return Err(failure),
                }
                fraction *= 0.5;
            }
            if accepted.is_some() {
                break;
            }
            inverse = identity();
        }
        let Some((point, next)) = accepted else { break };
        let step = std::array::from_fn(|i| point[i] - result.point[i]);
        if fixed(&point, &next.gradient) == active {
            let change = std::array::from_fn(|i| {
                if active[i] {
                    0.0
                } else {
                    next.gradient[i] - current.gradient[i]
                }
            });
            update_inverse(&mut inverse, &step, &change, dimension);
        } else {
            inverse = identity();
        }
        result.point = point;
        result.evaluation = next;
        result.iterations += 1;
    }
    Ok(result)
}

fn certify_curvature(
    family: Family,
    point: &Vector,
    hessian: &Matrix,
) -> Result<(f64, usize), Failure> {
    let mut basis = [[0.0; WIDTH]; WIDTH];
    let mut count = 0;
    let mut boundary = 0;
    if point[0] - MIN_LOG_OMEGA <= 1e-8 {
        boundary |= 1;
    } else if MAX_LOG_OMEGA - point[0] <= 1e-8 {
        boundary |= 2;
    } else {
        basis[count][0] = 1.0;
        count += 1;
    }
    let mut last_dynamic = None;
    let persistence_cap = MAX_PERSISTENCE - persistence(point) <= 1e-8;
    if persistence_cap {
        boundary |= 32;
    }
    for i in 1..family.dimension() {
        if point[i] <= 1e-8 {
            let bit = if i == 2 && matches!(family, Family::Garch) {
                4
            } else {
                i + 1
            };
            boundary |= 1 << bit;
        } else if !persistence_cap {
            basis[count][i] = 1.0;
            count += 1;
        } else if let Some(reference) = last_dynamic {
            basis[count][i] = 1.0;
            basis[count][reference] = -1.0;
            count += 1;
        } else {
            last_dynamic = Some(i);
        }
    }
    Ok((certify_free_curvature(hessian, &basis, count)?, boundary))
}

pub(super) fn certify_free_curvature(
    hessian: &Matrix,
    basis: &Matrix,
    count: usize,
) -> Result<f64, Failure> {
    if count == 0 {
        return Err(Failure::Degenerate);
    }
    let mut factor = [[0.0; WIDTH]; WIDTH];
    let mut smallest = f64::INFINITY;
    let mut largest = 0.0_f64;
    for i in 0..count {
        let direction = hessian.map(|row| dot(&row, &basis[i]));
        for j in 0..=i {
            let mut value = dot(&direction, &basis[j]);
            for k in 0..j {
                value -= factor[i][k] * factor[j][k];
            }
            if i == j {
                if !value.is_finite() || value <= 0.0 {
                    return Err(Failure::Degenerate);
                }
                smallest = smallest.min(value);
                largest = largest.max(value);
                factor[i][i] = value.sqrt();
            } else {
                factor[i][j] = value / factor[j][j];
            }
        }
    }
    if smallest <= (1e-8 * largest).max(1e-10) {
        return Err(Failure::Degenerate);
    }
    Ok(smallest)
}

struct Solution {
    point: Vector,
    value: f64,
    iterations: usize,
    evaluations: usize,
    gradient: f64,
    curvature: f64,
    boundary: usize,
    converged_starts: usize,
}

fn estimate(sample: &Sample, family: Family, check: Check) -> Result<Solution, Failure> {
    let mut candidates = Vec::with_capacity(STARTS);
    for start in family.starts() {
        candidates.push(search(sample, family, start, MAX_EVALUATIONS, check)?);
    }
    let best = best_candidate(&candidates)?;
    let evidence = evaluate(sample, family, &best.point, true, check)?;
    let gradient = gradient_norm(&best.point, &evidence.gradient, family.dimension());
    if gradient > GRADIENT_TOLERANCE {
        return Err(Failure::Convergence);
    }
    let (curvature, boundary) = certify_curvature(family, &best.point, &evidence.hessian)?;
    Ok(Solution {
        point: best.point,
        value: evidence.value,
        iterations: best.iterations,
        evaluations: 1 + candidates
            .iter()
            .map(|candidate| candidate.evaluations)
            .sum::<usize>(),
        gradient,
        curvature,
        boundary,
        converged_starts: candidates
            .iter()
            .filter(|candidate| candidate.converged)
            .count(),
    })
}

pub(super) fn best_candidate(candidates: &[Candidate]) -> Result<&Candidate, Failure> {
    let best = candidates
        .iter()
        .filter(|candidate| candidate.converged)
        .min_by(|a, b| a.evaluation.value.total_cmp(&b.evaluation.value))
        .ok_or(Failure::Convergence)?;
    for candidate in candidates {
        let difference = candidate.evaluation.value - best.evaluation.value;
        if difference < -OBJECTIVE_TIE {
            return Err(Failure::Convergence);
        }
        if candidate.converged
            && difference.abs() <= OBJECTIVE_TIE
            && candidate
                .point
                .iter()
                .zip(best.point)
                .any(|(a, b)| (a - b).abs() > 1e-3)
        {
            return Err(Failure::Degenerate);
        }
    }
    Ok(best)
}

fn fit(
    values: &[f64],
    train: usize,
    family: Family,
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
    let sample = Sample::new(training, matches!(family, Family::Gjr), check)?;
    let solution = estimate(&sample, family, check)?;
    let point = &solution.point;
    let omega = point[0].exp();
    let rho = persistence(point);
    let (alpha, gamma, beta) = family.coefficients(point);
    let raw_scale = sample.rms * sample.rms;
    let raw_omega = omega * raw_scale;
    let long_run = raw_omega / (1.0 - rho);
    if !long_run.is_finite() || raw_omega <= 0.0 {
        return Err(Failure::Numeric);
    }
    let mut variance = omega + rho * sample.backcast;
    let (mut z_mean, mut z_energy) = (0.0, 0.0);
    for (i, &shock) in sample.shocks.iter().enumerate() {
        if i % 512 == 0 {
            checkpoint(check)?;
        }
        let ratio = shock.abs() / variance;
        z_mean += ratio.sqrt().copysign(shock) / train as f64;
        z_energy += ratio / train as f64;
        variance = omega + dot(point, &family.terms(shock, variance));
    }
    let normal_shift = 0.5 * std::f64::consts::TAU.ln() + sample.rms.ln();
    let (held_out, future) = forecasts.split_at_mut(holdout.len());
    let (mut holdout_loss, mut holdout_mae) = (0.0, 0.0);
    for (raw, output) in holdout.iter().zip(held_out) {
        checkpoint(check)?;
        let shock = signed_square(*raw, sample.rms)?;
        let size = holdout.len() as f64;
        *output = variance * raw_scale;
        holdout_loss += (0.5 * (variance.ln() + shock.abs() / variance) + normal_shift) / size;
        holdout_mae += (shock.abs() - variance).abs() / size;
        variance = omega + dot(point, &family.terms(shock, variance));
    }
    for output in future {
        *output = variance * raw_scale;
        variance = omega + rho * variance;
    }
    let summary = [
        raw_omega,
        alpha,
        gamma,
        beta,
        rho,
        long_run,
        sample.backcast * raw_scale,
        sample.rms,
        -(solution.value + normal_shift) * train as f64,
        z_mean,
        z_energy.sqrt(),
        solution.iterations as f64,
        solution.evaluations as f64,
        solution.gradient,
        solution.curvature,
        solution.boundary as f64,
        solution.converged_starts as f64,
        holdout_loss,
        holdout_mae * raw_scale,
    ];
    if !summary.iter().all(|value| value.is_finite())
        || !forecasts
            .iter()
            .all(|&value| value.is_finite() && value > 0.0)
    {
        return Err(Failure::Numeric);
    }
    checkpoint(check)?;
    Ok(summary)
}

pub(super) fn region<T>(pointer: *const T, length: usize) -> Option<(usize, usize)> {
    if pointer.is_null() || !pointer.is_aligned() {
        return None;
    }
    let start = pointer as usize;
    let bytes = length.checked_mul(std::mem::size_of::<T>())?;
    Some((start, start.checked_add(bytes)?))
}

/// Fits conditional Gaussian variance on a training prefix and returns a compact fit receipt.
///
/// # Safety
/// Pointers must refer to valid buffers of the declared lengths. Input must be initialized and
/// unchanged, and the optional callback must remain valid and not unwind. Fit and forecast
/// buffers are written only on success.
#[no_mangle]
pub unsafe extern "C" fn arboris_volatility_fit(
    values: *const f64,
    rows: usize,
    train: usize,
    family: usize,
    horizon: usize,
    summary: *mut f64,
    summary_len: usize,
    variances: *mut f64,
    variances_len: usize,
    error_index: *mut usize,
    check: Check,
) -> i32 {
    if rows > MAX_ROWS {
        return 6;
    }
    if train > rows
        || !(1..=MAX_HORIZON).contains(&horizon)
        || summary_len != SUMMARY
        || variances_len != rows - train + horizon
    {
        return 1;
    }
    let family = match family {
        0 => Family::Arch,
        1 => Family::Garch,
        2 => Family::Gjr,
        _ => return 1,
    };
    if train < MIN_TRAIN {
        return 3;
    }
    if rows - train > MAX_HOLDOUT {
        return 6;
    }
    let [Some(input_region), Some(fit_region), Some(forecast_region), Some(error_region)] = [
        region(values, rows),
        region(summary, summary_len),
        region(variances, variances_len),
        region(error_index, 1),
    ] else {
        return 1;
    };
    let mut regions = [input_region, fit_region, forecast_region, error_region];
    regions.sort_unstable();
    if regions.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return 1;
    }
    unsafe { error_index.write(usize::MAX) };
    let result = catch_unwind(AssertUnwindSafe(|| {
        let input = unsafe { slice::from_raw_parts(values, rows) };
        let mut output = [0.0; MAX_HOLDOUT + MAX_HORIZON];
        let fit = fit(input, train, family, &mut output[..variances_len], check)?;
        Ok::<_, Failure>((fit, output))
    }));
    match result {
        Ok(Ok((fit, output))) => {
            unsafe { slice::from_raw_parts_mut(summary, SUMMARY) }.copy_from_slice(&fit);
            unsafe { slice::from_raw_parts_mut(variances, variances_len) }
                .copy_from_slice(&output[..variances_len]);
            0
        }
        Ok(Err(Failure::Input(row))) => {
            unsafe { error_index.write(row) };
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

    fn close(actual: f64, expected: f64, tolerance: f64) {
        assert!(
            (actual - expected).abs() <= tolerance,
            "{actual} vs {expected}"
        );
    }

    #[test]
    fn exact_backcast_and_signed_news_recursion() {
        let family = Family::Gjr;
        let omega = 0.2;
        let point = [0.0, 0.05, 0.2, 0.6];
        let rho = persistence(&point);
        let first = omega + rho * 0.5;
        let second = omega + dot(&point, &family.terms(-4.0, first));
        let third = omega + dot(&point, &family.terms(4.0, second));
        close(first, 0.625, 1e-14);
        close(second, 2.175, 1e-14);
        close(third, 1.905, 1e-14);
        close(omega + rho * third, 1.81925, 1e-14);

        let symmetric = [0.0, 0.05, 0.05, 0.6];
        let garch = [0.0, 0.1, 0.6, 0.0];
        for shock in [-4.0, 4.0] {
            close(
                dot(&symmetric, &family.terms(shock, first)),
                dot(&garch, &Family::Garch.terms(shock, first)),
                1e-14,
            );
        }
        let zero_beta = [0.0, 0.1, 0.0, 0.0];
        assert_eq!(dot(&zero_beta, &Family::Garch.terms(-4.0, first)), 0.4);
        assert_eq!(dot(&zero_beta, &Family::Garch.terms(-4.0, third)), 0.4);
    }

    #[test]
    fn analytic_likelihood_derivatives_match_finite_differences() {
        let values: Vec<_> = [1.0, -2.0, 2.0, -0.5, 0.75, -1.1, 0.1, 0.0]
            .into_iter()
            .cycle()
            .take(96)
            .collect();
        for family in [Family::Arch, Family::Garch, Family::Gjr] {
            let sample = Sample::new(&values, matches!(family, Family::Gjr), None).unwrap();
            let point = family.starts()[0];
            let actual = evaluate(&sample, family, &point, true, None).unwrap();
            let step = 1e-6;
            for j in 0..family.dimension() {
                let mut probe = point;
                probe[j] += step;
                let high = evaluate(&sample, family, &probe, false, None).unwrap();
                probe[j] -= 2.0 * step;
                let low = evaluate(&sample, family, &probe, false, None).unwrap();
                close(
                    actual.gradient[j],
                    (high.value - low.value) / (2.0 * step),
                    2e-8,
                );
                for i in 0..family.dimension() {
                    close(
                        actual.hessian[i][j],
                        (high.gradient[i] - low.gradient[i]) / (2.0 * step),
                        2e-8,
                    );
                }
            }
        }
    }

    #[test]
    fn exhausted_start_cannot_publish_convergence() {
        let values: Vec<_> = [1.0, -2.0].into_iter().cycle().take(64).collect();
        let family = Family::Arch;
        let sample = Sample::new(&values, matches!(family, Family::Gjr), None).unwrap();
        let start = search(&sample, family, family.starts()[0], 1, None).unwrap();
        assert!(!start.converged);
        assert_eq!(start.evaluations, 1);
        assert_eq!(start.iterations, 0);
    }
}
