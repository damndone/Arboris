use std::{ptr, slice};

use super::{
    forecast, normalize, profile, valid_buffers, valid_phi, Checkpoint, Failure, Profile,
    Smoothing, FIT_LENGTH, LOWER_GAIN, MAX_HORIZON, UPPER_GAIN,
};

const AUTO_FIT_LENGTH: usize = 15;
const MAX_ROWS: usize = 2_000;
const MAX_EVALUATIONS: usize = 1_024;
const INTERIOR_GUARD: f64 = 0.001;
const BOUNDARY_GAP: f64 = 1e-7;
const GRADIENT_TOLERANCE: f64 = 1e-7;
const CURVATURE_STEP: f64 = 1e-4;
const MIN_CURVATURE: f64 = 1e-4;
const OBJECTIVE_TIE: f64 = 1e-8;
const AGREEMENT_DISTANCE: f64 = 1e-3;

type Gains = [f64; 2];

enum AutoFailure {
    Fit(Failure),
    Unidentified,
    Unverified,
    Boundary,
    Budget,
}

impl From<Failure> for AutoFailure {
    fn from(error: Failure) -> Self {
        Self::Fit(error)
    }
}

#[derive(Clone, Copy)]
struct Segment {
    start: Gains,
    end: Gains,
}

impl Segment {
    fn direction(self) -> Gains {
        subtract(self.end, self.start)
    }

    fn point(self, t: f64) -> Gains {
        let step = self.direction();
        [
            step[0].mul_add(t, self.start[0]),
            step[1].mul_add(t, self.start[1]),
        ]
    }
}

#[derive(Clone, Copy)]
enum Free {
    One { segment: Segment, index: usize },
    Both,
}

impl Free {
    fn new(alpha_mode: i32, alpha: f64, beta_mode: i32, beta: f64) -> Option<Self> {
        let make = |start, end, index| {
            let segment = Segment { start, end };
            (segment.direction()[index] >= 4.0 * INTERIOR_GUARD)
                .then_some(Self::One { segment, index })
        };
        match (alpha_mode, beta_mode) {
            (1, 0) if alpha == 0.0 && (LOWER_GAIN..=UPPER_GAIN).contains(&beta) => {
                make([beta, beta], [UPPER_GAIN, beta], 0)
            }
            (0, 1) if beta == 0.0 && (LOWER_GAIN..=UPPER_GAIN).contains(&alpha) => {
                make([alpha, LOWER_GAIN], [alpha, alpha], 1)
            }
            (1, 1) if alpha == 0.0 && beta == 0.0 => Some(Self::Both),
            _ => None,
        }
    }

    fn count(self) -> usize {
        match self {
            Self::One { .. } => 1,
            Self::Both => 2,
        }
    }

    fn boundary_distance(self, [alpha, beta]: Gains) -> f64 {
        match self {
            Self::One { segment, index } => {
                let value = [alpha, beta][index];
                (value - segment.start[index]).min(segment.end[index] - value)
            }
            Self::Both => (UPPER_GAIN - alpha)
                .min(beta - LOWER_GAIN)
                .min(alpha - beta),
        }
    }

    fn gradient(self, gradient: Gains) -> f64 {
        match self {
            Self::One { index, .. } => gradient[index].abs(),
            Self::Both => magnitude(gradient),
        }
    }
}

#[derive(Clone, Copy)]
struct Probe {
    gains: Gains,
    profile: Profile,
    value: f64,
}

struct Objective<'a> {
    values: &'a [f64],
    offset: f64,
    scale: f64,
    phi: f64,
    check: Checkpoint,
    evaluations: usize,
}

impl Objective<'_> {
    fn at(&mut self, gains: Gains) -> Result<Probe, AutoFailure> {
        if self.evaluations >= MAX_EVALUATIONS {
            return Err(AutoFailure::Budget);
        }
        self.evaluations += 1;
        let profile = profile::<true>(
            self.values,
            self.offset,
            self.scale,
            self.smoothing(gains),
            self.check,
        )?;
        Ok(Probe {
            gains,
            profile,
            value: 2.0 * profile.relative_deviation.ln(),
        })
    }

    fn smoothing(&self, [alpha, beta]: Gains) -> Smoothing {
        Smoothing {
            alpha,
            beta,
            phi: self.phi,
        }
    }

    fn curvature(&mut self, point: Gains, free: Free) -> Result<f64, AutoFailure> {
        let mut column = |coordinate| {
            let mut left = point;
            let mut right = point;
            left[coordinate] -= CURVATURE_STEP;
            right[coordinate] += CURVATURE_STEP;
            let left = self.at(left)?.profile.gradient;
            let right = self.at(right)?.profile.gradient;
            Ok::<_, AutoFailure>(subtract(right, left).map(|value| value / (2.0 * CURVATURE_STEP)))
        };
        let smallest = match free {
            Free::One { index, .. } => column(index)?[index],
            Free::Both => {
                let [h00, h10] = column(0)?;
                let [h01, h11] = column(1)?;
                let off_diagonal = h01.midpoint(h10);
                let largest = 0.5 * (h00 + h11 + (h00 - h11).hypot(2.0 * off_diagonal));
                if largest <= 0.0 {
                    return Err(AutoFailure::Unidentified);
                }
                h00.mul_add(h11, -off_diagonal.powi(2)) / largest
            }
        };
        if !smallest.is_finite() || smallest <= MIN_CURVATURE {
            return Err(AutoFailure::Unidentified);
        }
        Ok(smallest)
    }
}

fn dot(left: Gains, right: Gains) -> f64 {
    left[0] * right[0] + left[1] * right[1]
}

fn subtract(left: Gains, right: Gains) -> Gains {
    [left[0] - right[0], left[1] - right[1]]
}

fn magnitude(point: Gains) -> f64 {
    point[0].abs().max(point[1].abs())
}

fn minimum(left: Probe, right: Probe) -> Probe {
    if left.value <= right.value {
        left
    } else {
        right
    }
}

struct LineScan {
    best: Probe,
    endpoint: f64,
    roots: Vec<Probe>,
}

fn stationary_minimum(
    objective: &mut Objective,
    segment: Segment,
    mut left: f64,
    mut right: f64,
) -> Result<Probe, AutoFailure> {
    let direction = segment.direction();
    for _ in 0..42 {
        let middle = left.midpoint(right);
        let estimate = objective.at(segment.point(middle))?;
        let slope = dot(estimate.profile.gradient, direction);
        if slope.abs() <= 1e-10 || right - left <= 1e-12 {
            return Ok(estimate);
        }
        if slope < 0.0 {
            left = middle;
        } else {
            right = middle;
        }
    }
    Err(AutoFailure::Unverified)
}

fn scan_line(objective: &mut Objective, segment: Segment) -> Result<LineScan, AutoFailure> {
    let first = objective.at(segment.start)?;
    let last = objective.at(segment.end)?;
    let endpoint = first.value.min(last.value);
    let direction = segment.direction();
    let mut best = minimum(first, last);
    let mut roots = Vec::new();
    let mut previous_t = 0.0;
    let mut previous_slope = dot(first.profile.gradient, direction);
    let knots = [0.001, 0.004, 0.012]
        .into_iter()
        .chain((1..32).map(|step| f64::from(step) / 32.0))
        .chain([0.988, 0.996, 0.999, 1.0]);
    for t in knots {
        let here = if t == 1.0 {
            last
        } else {
            objective.at(segment.point(t))?
        };
        let slope = dot(here.profile.gradient, direction);
        best = minimum(best, here);
        if previous_slope <= 0.0 && slope >= 0.0 && previous_slope < slope {
            let root = stationary_minimum(objective, segment, previous_t, t)?;
            best = minimum(best, root);
            roots.push(root);
        }
        previous_t = t;
        previous_slope = slope;
    }
    Ok(LineScan {
        best,
        endpoint,
        roots,
    })
}

const IDENTITY: [Gains; 2] = [[1.0, 0.0], [0.0, 1.0]];

fn feasible_step([alpha, beta]: Gains, [alpha_step, beta_step]: Gains) -> f64 {
    let mut bound = f64::INFINITY;
    if alpha_step > 0.0 {
        bound = bound.min((UPPER_GAIN - alpha) / alpha_step);
    }
    if beta_step < 0.0 {
        bound = bound.min((beta - LOWER_GAIN) / -beta_step);
    }
    if beta_step > alpha_step {
        bound = bound.min((alpha - beta) / (beta_step - alpha_step));
    }
    (0.97 * bound).min(1.0)
}

fn bfgs_update(matrix: [Gains; 2], step: Gains, gradient_change: Gains) -> [Gains; 2] {
    let gain = dot(step, gradient_change);
    if gain <= 1e-12 * magnitude(step) * magnitude(gradient_change) {
        return IDENTITY;
    }
    let projected = matrix.map(|row| dot(row, gradient_change));
    let factor = (gain + dot(gradient_change, projected)) / gain.powi(2);
    let mut next = matrix;
    for (i, row) in next.iter_mut().enumerate() {
        for (j, value) in row.iter_mut().enumerate() {
            *value += factor * step[i] * step[j]
                - (projected[i] * step[j] + step[i] * projected[j]) / gain;
        }
    }
    next
}

fn search(objective: &mut Objective, mut current: Probe) -> Result<Probe, AutoFailure> {
    let mut inverse_hessian = IDENTITY;
    for _ in 0..48 {
        let gradient = current.profile.gradient;
        if magnitude(gradient) <= GRADIENT_TOLERANCE {
            break;
        }
        let mut direction = inverse_hessian.map(|row| -dot(row, gradient));
        if direction.iter().any(|value| !value.is_finite()) || dot(direction, gradient) >= 0.0 {
            direction = gradient.map(|value| -value);
            inverse_hessian = IDENTITY;
        }
        let limit = (0.35 / magnitude(direction)).min(1.0);
        let direction = direction.map(|value| value * limit);
        let slope = dot(direction, gradient);
        let mut fraction = feasible_step(current.gains, direction);
        let mut accepted = None;
        for _ in 0..20 {
            if fraction <= 1e-12 {
                break;
            }
            let gains = [
                direction[0].mul_add(fraction, current.gains[0]),
                direction[1].mul_add(fraction, current.gains[1]),
            ];
            let trial = objective.at(gains)?;
            if trial.value <= current.value + 1e-4 * fraction * slope + 2e-14 {
                accepted = Some(trial);
                break;
            }
            fraction *= 0.5;
        }
        let Some(next) = accepted else {
            break;
        };
        inverse_hessian = bfgs_update(
            inverse_hessian,
            subtract(next.gains, current.gains),
            subtract(next.profile.gradient, gradient),
        );
        current = next;
    }
    Ok(current)
}

fn search_both(objective: &mut Objective) -> Result<(Vec<Probe>, Probe, f64), AutoFailure> {
    let low = [LOWER_GAIN; 2];
    let high = [UPPER_GAIN; 2];
    let corner = [UPPER_GAIN, LOWER_GAIN];
    let mut boundary = f64::INFINITY;
    for (start, end) in [(low, corner), (corner, high), (low, high)] {
        let edge = scan_line(objective, Segment { start, end })?;
        boundary = boundary.min(edge.best.value);
    }

    let mut grid_best = objective.at([0.5, 0.2])?;
    for i in 1..10 {
        let alpha = LOWER_GAIN + (UPPER_GAIN - LOWER_GAIN) * f64::from(i) / 10.0;
        for j in 1..5 {
            let beta = LOWER_GAIN + (alpha - LOWER_GAIN) * f64::from(j) / 5.0;
            grid_best = minimum(grid_best, objective.at([alpha, beta])?);
        }
    }
    let mut best_seen = grid_best;
    let mut converged = Vec::new();
    let starters = [
        [0.18, 0.04],
        [0.45, 0.08],
        [0.55, 0.3],
        [0.82, 0.15],
        [0.92, 0.61],
        [0.86, 0.78],
    ];
    let diverse = starters
        .into_iter()
        .filter(|gains| magnitude(subtract(*gains, grid_best.gains)) >= 0.05);
    for gains in std::iter::once(grid_best.gains).chain(diverse) {
        let initial = if gains == grid_best.gains {
            grid_best
        } else {
            objective.at(gains)?
        };
        let result = search(objective, initial)?;
        best_seen = minimum(best_seen, result);
        if magnitude(result.profile.gradient) <= GRADIENT_TOLERANCE {
            converged.push(result);
        }
    }
    Ok((converged, best_seen, boundary))
}

struct Accepted {
    candidate: Probe,
    curvature: f64,
    boundary_gap: f64,
    agreements: usize,
}

fn estimate(objective: &mut Objective, free: Free) -> Result<Accepted, AutoFailure> {
    let (candidates, best_seen, boundary) = match free {
        Free::One { segment, .. } => {
            let scan = scan_line(objective, segment)?;
            (scan.roots, scan.best, scan.endpoint)
        }
        Free::Both => search_both(objective)?,
    };
    if boundary <= best_seen.value + BOUNDARY_GAP {
        return Err(AutoFailure::Boundary);
    }
    let Some(candidate) = candidates
        .iter()
        .copied()
        .min_by(|a, b| a.value.total_cmp(&b.value))
    else {
        return Err(AutoFailure::Unverified);
    };
    let boundary_gap = boundary - candidate.value;
    if boundary_gap <= BOUNDARY_GAP || free.boundary_distance(candidate.gains) <= INTERIOR_GUARD {
        return Err(AutoFailure::Boundary);
    }
    if candidate.value - best_seen.value > OBJECTIVE_TIE
        || free.gradient(candidate.profile.gradient) > GRADIENT_TOLERANCE
    {
        return Err(AutoFailure::Unverified);
    }
    let mut agreements = 0;
    for other in &candidates {
        let distance = magnitude(subtract(candidate.gains, other.gains));
        if distance <= AGREEMENT_DISTANCE {
            agreements += 1;
        } else if other.value - candidate.value <= OBJECTIVE_TIE {
            return Err(AutoFailure::Unidentified);
        }
    }
    if agreements < free.count() {
        return Err(AutoFailure::Unverified);
    }
    let curvature = objective.curvature(candidate.gains, free)?;
    Ok(Accepted {
        candidate,
        curvature,
        boundary_gap,
        agreements,
    })
}

/// # Safety
/// Buffers must be valid for their stated lengths. The callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_ets_trend_fit_auto(
    values: *const f64,
    rows: usize,
    alpha_mode: i32,
    alpha: f64,
    beta_mode: i32,
    beta: f64,
    phi: f64,
    horizon: usize,
    estimates: *mut f64,
    estimates_len: usize,
    forecasts: *mut f64,
    forecasts_len: usize,
    error_index: *mut usize,
    check: Checkpoint,
) -> i32 {
    let Some(free) = Free::new(alpha_mode, alpha, beta_mode, beta) else {
        return 6;
    };
    if rows > MAX_ROWS || !valid_phi(phi) {
        return 6;
    }
    if rows < if free.count() == 1 { 24 } else { 40 } {
        return 3;
    }
    if !(1..=MAX_HORIZON).contains(&horizon)
        || estimates_len != AUTO_FIT_LENGTH
        || forecasts_len != 2 * horizon
        || !valid_buffers(
            values,
            rows,
            estimates,
            estimates_len,
            forecasts,
            forecasts_len,
            error_index,
        )
    {
        return 1;
    }
    let values = unsafe { slice::from_raw_parts(values, rows) };
    let result = (|| {
        let (offset, scale) = normalize(values, check)?;
        let mut objective = Objective {
            values,
            offset,
            scale,
            phi,
            check,
            evaluations: 0,
        };
        let accepted = estimate(&mut objective, free)?;
        let candidate = accepted.candidate;
        let result = forecast(
            candidate.profile,
            offset,
            scale,
            objective.smoothing(candidate.gains),
            rows,
            horizon,
            check,
        )?;
        let [alpha, beta] = candidate.gains;
        let diagnostics = [
            alpha,
            beta,
            free.count() as f64,
            objective.evaluations as f64,
            free.gradient(candidate.profile.gradient),
            accepted.curvature,
            accepted.boundary_gap,
            accepted.agreements as f64,
        ];
        Ok::<_, AutoFailure>((result, diagnostics))
    })();
    match result {
        Ok((fit, diagnostics)) => {
            unsafe {
                ptr::copy_nonoverlapping(fit.summary.as_ptr(), estimates, FIT_LENGTH);
                ptr::copy_nonoverlapping(
                    diagnostics.as_ptr(),
                    estimates.add(FIT_LENGTH),
                    diagnostics.len(),
                );
                ptr::copy_nonoverlapping(fit.forecast.as_ptr().cast(), forecasts, forecasts_len);
            }
            0
        }
        Err(AutoFailure::Fit(Failure::NonFinite(row))) => {
            unsafe { error_index.write(row) };
            1
        }
        Err(AutoFailure::Fit(Failure::Numeric)) => 2,
        Err(AutoFailure::Fit(Failure::Degenerate) | AutoFailure::Unidentified) => 4,
        Err(AutoFailure::Unverified) => 5,
        Err(AutoFailure::Budget) => 6,
        Err(AutoFailure::Fit(Failure::Cancelled)) => 7,
        Err(AutoFailure::Boundary) => 8,
    }
}

#[cfg(test)]
#[path = "auto_tests.rs"]
mod tests;
