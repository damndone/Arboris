use std::slice;

use super::{
    append_result, checkpoint, fit, initialize, output_length, publish_result, validate_values,
    CancellationCheck, Failure, Smoothing, State, CHECK_EVERY, FORECAST_WIDTH, INVALID_INPUT,
    MAX_HORIZON, SUMMARY_WIDTH, TRACE_WIDTH,
};

const MAX_PERIOD: usize = 24;
const MAX_ROWS: usize = 2_000;
const MAX_EVALUATIONS: usize = 1_536;
const MAX_LOCAL_EVALUATIONS: usize = 96;
const PREFIX: usize = 8;
const LOWER: f64 = 0.0001;
const UPPER: f64 = 0.9999;
const BOUNDARY_MARGIN: f64 = 0.001;
const BOUNDARY_GAP: f64 = 1e-7;
const UNRESOLVED_BOUNDARY_GAP: f64 = 1e-4;
const GRADIENT_TOLERANCE: f64 = 1e-7;
const OBJECTIVE_TIE: f64 = 1e-8;
const AGREEMENT: f64 = 1e-3;
const CURVATURE_STEP: f64 = 1e-4;
const MIN_CURVATURE: f64 = 1e-4;
const UNIDENTIFIED: i32 = 6;
const BOUNDARY: i32 = 7;
const WORK_LIMIT: i32 = 8;

type Point = [f64; 3];
type Matrix = [Point; 3];

const IDENTITY: Matrix = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]];

enum JointFailure {
    Kernel(Failure),
    Unidentified,
    Boundary,
    Budget,
}

impl From<Failure> for JointFailure {
    fn from(error: Failure) -> Self {
        Self::Kernel(error)
    }
}

fn dot(left: Point, right: Point) -> f64 {
    left.iter().zip(right).map(|(a, b)| a * b).sum()
}

fn subtract(left: Point, right: Point) -> Point {
    [left[0] - right[0], left[1] - right[1], left[2] - right[2]]
}

fn magnitude(values: Point) -> f64 {
    values.into_iter().map(f64::abs).fold(0.0, f64::max)
}

fn smoothing([alpha, beta, gamma]: Point) -> Smoothing {
    Smoothing { alpha, beta, gamma }
}

#[derive(Clone, Copy)]
struct Probe {
    point: Point,
    value: f64,
    gradient: Point,
}

fn better(left: Probe, right: Probe) -> Probe {
    if left.value <= right.value {
        left
    } else {
        right
    }
}

struct Objective<'a> {
    observations: &'a [f64],
    initial: &'a State,
    check: CancellationCheck,
    evaluations: usize,
}

impl Objective<'_> {
    fn at(&mut self, point: Point) -> Result<Probe, JointFailure> {
        if self.evaluations >= MAX_EVALUATIONS {
            return Err(JointFailure::Budget);
        }
        self.evaluations += 1;
        let weights = smoothing(point);
        let gains = weights.gains();
        let gain_derivatives = [
            [1.0, 0.0, 0.0],
            [weights.beta, weights.alpha, 0.0],
            [-weights.gamma, 0.0, 1.0 - weights.alpha],
        ];
        let mut state = self.initial.clone();
        let period = state.seasonal.len();
        let warmup = 2 * period;
        let mut level_gradient = [0.0; 3];
        let mut trend_gradient = [0.0; 3];
        let mut season_gradients = [[0.0; 3]; MAX_PERIOD];
        let mut gradient = [0.0; 3];
        let mut squared = 0.0;
        for (index, &value) in self.observations.iter().enumerate().skip(warmup) {
            if (index - warmup) % CHECK_EVERY == 0 {
                checkpoint(self.check)?;
            }
            let phase = index % period;
            let (_, error) = state.step(phase, value, gains);
            squared = error.mul_add(error, squared);
            for i in 0..3 {
                let base = level_gradient[i] + trend_gradient[i];
                let innovation = -base - season_gradients[phase][i];
                gradient[i] = error.mul_add(innovation, gradient[i]);
                level_gradient[i] = base + gains[0] * innovation + gain_derivatives[0][i] * error;
                trend_gradient[i] += gains[1] * innovation + gain_derivatives[1][i] * error;
                season_gradients[phase][i] +=
                    gains[2] * innovation + gain_derivatives[2][i] * error;
            }
        }
        let variance = squared / (self.observations.len() - warmup) as f64;
        if !variance.is_finite() {
            return Err(Failure::Fit(self.observations.len() - 1).into());
        }
        if variance.sqrt() <= 128.0 * f64::EPSILON {
            return Err(JointFailure::Unidentified);
        }
        let gradient = gradient.map(|value| 2.0 * value / squared);
        if gradient.iter().any(|value| !value.is_finite()) {
            return Err(Failure::Fit(self.observations.len() - 1).into());
        }
        Ok(Probe {
            point,
            value: variance.ln(),
            gradient,
        })
    }

    fn curvature(&mut self, point: Point) -> Result<f64, JointFailure> {
        let mut hessian = [[0.0; 3]; 3];
        for (i, column) in hessian.iter_mut().enumerate() {
            let mut low = point;
            let mut high = point;
            low[i] -= CURVATURE_STEP;
            high[i] += CURVATURE_STEP;
            let low = self.at(low)?.gradient;
            let high = self.at(high)?.gradient;
            *column = subtract(high, low).map(|v| v / (2.0 * CURVATURE_STEP));
        }
        let curvature = smallest_eigenvalue(hessian);
        if !curvature.is_finite() || curvature <= MIN_CURVATURE {
            return Err(JointFailure::Unidentified);
        }
        Ok(curvature)
    }
}

fn smallest_eigenvalue(h: Matrix) -> f64 {
    let center = (h[0][0] + h[1][1] + h[2][2]) / 3.0;
    let diagonal = [h[0][0] - center, h[1][1] - center, h[2][2] - center];
    let off = [
        h[0][1].midpoint(h[1][0]),
        h[0][2].midpoint(h[2][0]),
        h[1][2].midpoint(h[2][1]),
    ];
    let scale = ((dot(diagonal, diagonal) + 2.0 * dot(off, off)) / 6.0).sqrt();
    if scale == 0.0 {
        return center;
    }
    let [a, b, c] = diagonal.map(|v| v / scale);
    let [d, e, f] = off.map(|v| v / scale);
    let determinant = a * b * c + 2.0 * d * e * f - a * f * f - b * e * e - c * d * d;
    let angle = (0.5 * determinant).clamp(-1.0, 1.0).acos() / 3.0;
    center + 2.0 * scale * (angle + std::f64::consts::TAU / 3.0).cos()
}

fn projected(probe: Probe, fixed: Option<usize>) -> Point {
    let mut gradient = probe.gradient;
    for (i, value) in gradient.iter_mut().enumerate() {
        if fixed == Some(i)
            || (probe.point[i] == LOWER && *value > 0.0)
            || (probe.point[i] == UPPER && *value < 0.0)
        {
            *value = 0.0;
        }
    }
    gradient
}

fn inverse_update(matrix: Matrix, delta: Point, difference: Point) -> Matrix {
    let secant = dot(delta, difference);
    if secant <= 1e-12 * magnitude(delta) * magnitude(difference) {
        return IDENTITY;
    }
    let transformed = matrix.map(|row| dot(row, difference));
    let factor = (secant + dot(difference, transformed)) / secant.powi(2);
    let mut updated = matrix;
    for (i, row) in updated.iter_mut().enumerate() {
        for (j, value) in row.iter_mut().enumerate() {
            *value += factor * delta[i] * delta[j]
                - (transformed[i] * delta[j] + delta[i] * transformed[j]) / secant;
        }
    }
    updated
}

fn line_step(
    objective: &mut Objective,
    current: Probe,
    direction: Point,
    fixed: Option<usize>,
    limit: usize,
) -> Result<Option<Probe>, JointFailure> {
    let mut fraction = (0.35 / magnitude(direction)).min(1.0);
    for _ in 0..16 {
        if objective.evaluations >= limit {
            break;
        }
        let mut trial = current.point;
        for (i, value) in trial.iter_mut().enumerate() {
            if fixed != Some(i) {
                *value = direction[i].mul_add(fraction, *value).clamp(LOWER, UPPER);
            }
        }
        let slope = dot(current.gradient, subtract(trial, current.point));
        if slope < 0.0 {
            let next = objective.at(trial)?;
            if next.value <= current.value + 1e-4 * slope + 2e-14 {
                return Ok(Some(next));
            }
        }
        fraction *= 0.5;
    }
    Ok(None)
}

fn minimize(
    objective: &mut Objective,
    mut current: Probe,
    fixed: Option<usize>,
) -> Result<Probe, JointFailure> {
    let limit = objective.evaluations + MAX_LOCAL_EVALUATIONS;
    let mut matrix = IDENTITY;
    for _ in 0..48 {
        let gradient = projected(current, fixed);
        if magnitude(gradient) <= GRADIENT_TOLERANCE || objective.evaluations >= limit {
            break;
        }
        let mut direction = matrix.map(|row| -dot(row, gradient));
        for (i, step) in direction.iter_mut().enumerate() {
            if fixed == Some(i)
                || (current.point[i] == LOWER && *step < 0.0)
                || (current.point[i] == UPPER && *step > 0.0)
            {
                *step = 0.0;
            }
        }
        let candidate =
            if direction.iter().all(|v| v.is_finite()) && dot(direction, current.gradient) < 0.0 {
                line_step(objective, current, direction, fixed, limit)?
            } else {
                None
            };
        let next = match candidate {
            Some(next) => next,
            None => {
                let Some(next) = line_step(
                    objective,
                    current,
                    gradient.map(|value| -value),
                    fixed,
                    limit,
                )?
                else {
                    break;
                };
                matrix = IDENTITY;
                next
            }
        };
        matrix = inverse_update(
            matrix,
            subtract(next.point, current.point),
            subtract(next.gradient, current.gradient),
        );
        current = next;
    }
    Ok(current)
}

fn best_boundary(objective: &mut Objective) -> Result<(f64, f64), JointFailure> {
    let mut best = f64::INFINITY;
    let mut unresolved = f64::INFINITY;
    for fixed in 0..3 {
        let axes = [(fixed + 1) % 3, (fixed + 2) % 3];
        for edge in [LOWER, UPPER] {
            let mut point = [0.5; 3];
            point[fixed] = edge;
            let mut candidate = objective.at(point)?;
            for a in [LOWER, 0.25, 0.5, 0.75, UPPER] {
                for b in [LOWER, 0.25, 0.5, 0.75, UPPER] {
                    point[axes[0]] = a;
                    point[axes[1]] = b;
                    candidate = better(candidate, objective.at(point)?);
                }
            }
            let result = minimize(objective, candidate, Some(fixed))?;
            best = best.min(result.value);
            if magnitude(projected(result, Some(fixed))) > GRADIENT_TOLERANCE {
                unresolved = unresolved.min(result.value);
            }
        }
    }
    Ok((best, unresolved))
}

struct Accepted {
    best: Probe,
    curvature: f64,
    gap: f64,
    agreeing: usize,
}

fn select(objective: &mut Objective) -> Result<Accepted, JointFailure> {
    let mut grid = objective.at([0.3, 0.1, 0.1])?;
    for alpha in [0.15, 0.45, 0.75] {
        for beta in [0.05, 0.25, 0.65] {
            for gamma in [0.1, 0.45, 0.8] {
                grid = better(grid, objective.at([alpha, beta, gamma])?);
            }
        }
    }
    let starts = [
        [0.18, 0.05, 0.2],
        [0.25, 0.35, 0.8],
        [0.45, 0.08, 0.7],
        [0.6, 0.3, 0.3],
        [0.8, 0.08, 0.15],
        [0.8, 0.6, 0.65],
    ];
    let mut best_seen = grid;
    let mut explored_boundary = f64::INFINITY;
    let mut candidates = Vec::with_capacity(starts.len() + 1);
    for point in std::iter::once(grid.point).chain(starts) {
        let initial = if point == grid.point {
            grid
        } else {
            objective.at(point)?
        };
        let candidate = minimize(objective, initial, None)?;
        best_seen = better(best_seen, candidate);
        if candidate
            .point
            .iter()
            .any(|&value| value == LOWER || value == UPPER)
        {
            explored_boundary = explored_boundary.min(candidate.value);
        }
        if magnitude(candidate.gradient) <= GRADIENT_TOLERANCE {
            candidates.push(candidate);
        }
    }
    let (boundary, unresolved_boundary) = best_boundary(objective)?;
    let boundary = boundary.min(explored_boundary);
    if boundary <= best_seen.value + BOUNDARY_GAP {
        return Err(JointFailure::Boundary);
    }
    let Some(best) = candidates
        .iter()
        .copied()
        .min_by(|a, b| a.value.total_cmp(&b.value))
    else {
        return Err(JointFailure::Unidentified);
    };
    let gap = boundary - best.value;
    if gap <= BOUNDARY_GAP
        || best
            .point
            .iter()
            .any(|value| (*value - LOWER).min(UPPER - *value) <= BOUNDARY_MARGIN)
    {
        return Err(JointFailure::Boundary);
    }
    if best.value > best_seen.value + OBJECTIVE_TIE
        || unresolved_boundary <= best.value + UNRESOLVED_BOUNDARY_GAP
    {
        return Err(JointFailure::Unidentified);
    }
    let mut agreeing = 0;
    for alternative in candidates {
        let distance = magnitude(subtract(best.point, alternative.point));
        if distance <= AGREEMENT {
            agreeing += 1;
        } else if alternative.value - best.value <= OBJECTIVE_TIE {
            return Err(JointFailure::Unidentified);
        }
    }
    if agreeing < 2 {
        return Err(JointFailure::Unidentified);
    }
    let curvature = objective.curvature(best.point)?;
    Ok(Accepted {
        best,
        curvature,
        gap,
        agreeing,
    })
}

fn scale_output(
    output: &mut [f64],
    offset: f64,
    scale: f64,
    period: usize,
    rows: usize,
    horizon: usize,
) -> Result<(), Failure> {
    let (fit, future) = output.split_at_mut(output.len() - FORECAST_WIDTH * horizon);
    fit[0] = scale.mul_add(fit[0], offset);
    fit[1] *= scale;
    fit[2] = scale.mul_add(fit[2], offset);
    fit[3] *= scale;
    for value in &mut fit[4..6] {
        *value = (value.sqrt() * scale).powi(2);
        if !value.is_normal() {
            return Err(Failure::Fit(rows - 1));
        }
    }
    let (seasons, trace) = fit[SUMMARY_WIDTH..].split_at_mut(2 * period);
    for value in seasons {
        *value *= scale;
    }
    for row in trace.chunks_exact_mut(TRACE_WIDTH) {
        row[0] = scale.mul_add(row[0], offset);
        row[1] *= scale;
        row[2] = scale.mul_add(row[2], offset);
        row[3] *= scale;
        row[4] *= scale;
    }
    if fit.iter().any(|value| !value.is_finite()) {
        return Err(Failure::Fit(rows - 1));
    }
    for (step, row) in future.chunks_exact_mut(FORECAST_WIDTH).enumerate() {
        row[0] = scale.mul_add(row[0], offset);
        row[1] = (row[1].sqrt() * scale).powi(2);
        if !row[0].is_finite() || !row[1].is_normal() {
            return Err(Failure::Forecast(step + 1));
        }
    }
    Ok(())
}

fn compute(
    values: &[f64],
    period: usize,
    horizon: usize,
    check: CancellationCheck,
) -> Result<Vec<f64>, JointFailure> {
    validate_values(values, check)?;
    let (low, high) = values
        .iter()
        .fold((f64::INFINITY, f64::NEG_INFINITY), |(low, high), &value| {
            (low.min(value), high.max(value))
        });
    if low == high {
        return Err(JointFailure::Unidentified);
    }
    let offset = low.midpoint(high);
    let scale = (high - offset).max(offset - low);
    let normalized: Vec<_> = values
        .iter()
        .map(|value| (value - offset) / scale)
        .collect();
    let initial = initialize(&normalized, period)?;
    let mut objective = Objective {
        observations: &normalized,
        initial: &initial,
        check,
        evaluations: 0,
    };
    let accepted = select(&mut objective)?;
    let weights = smoothing(accepted.best.point);
    let estimates = fit(&normalized, &initial, weights, check)?;
    if !estimates.residual_variance.is_normal() {
        return Err(JointFailure::Unidentified);
    }
    let mut output = Vec::with_capacity(PREFIX + output_length(values.len(), period, horizon));
    output.extend(accepted.best.point);
    output.extend([
        objective.evaluations as f64,
        magnitude(accepted.best.gradient),
        accepted.curvature,
        accepted.gap,
        accepted.agreeing as f64,
    ]);
    append_result(
        &mut output,
        initial,
        &estimates,
        values.len(),
        horizon,
        weights,
        check,
    )?;
    scale_output(
        &mut output[PREFIX..],
        offset,
        scale,
        period,
        values.len(),
        horizon,
    )?;
    checkpoint(check)?;
    Ok(output)
}

fn region<T>(pointer: *const T, length: usize) -> Option<(usize, usize)> {
    let start = pointer as usize;
    let bytes = length.checked_mul(size_of::<T>())?;
    if pointer.is_null() || !pointer.is_aligned() || bytes > isize::MAX as usize {
        return None;
    }
    Some((start, start.checked_add(bytes)?))
}

/// # Safety
/// The initialized input and separate output buffers must be valid for their stated lengths.
/// The optional callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_holt_winters_fit_joint(
    values: *const f64,
    count: usize,
    period: usize,
    horizon: usize,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if count > MAX_ROWS {
        return WORK_LIMIT;
    }
    if !(2..=MAX_PERIOD).contains(&period)
        || count < 2 * period + (2 * period).max(24)
        || !(1..=MAX_HORIZON).contains(&horizon)
        || output_len != PREFIX + output_length(count, period, horizon)
    {
        return INVALID_INPUT;
    }
    let [Some(input), Some(result), Some(error)] = [
        region(values, count),
        region(output, output_len),
        region(error_index, 1),
    ] else {
        return INVALID_INPUT;
    };
    let mut buffers = [input, result, error];
    buffers.sort_unstable();
    if buffers.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    let values = unsafe { slice::from_raw_parts(values, count) };
    match compute(values, period, horizon, check) {
        Ok(values) => unsafe { publish_result(Ok(values), output, output_len, error_index) },
        Err(JointFailure::Kernel(failure)) => unsafe {
            publish_result(Err(failure), output, output_len, error_index)
        },
        Err(JointFailure::Unidentified) => UNIDENTIFIED,
        Err(JointFailure::Boundary) => BOUNDARY,
        Err(JointFailure::Budget) => WORK_LIMIT,
    }
}

#[cfg(test)]
#[path = "joint_tests.rs"]
mod tests;
