use std::mem::{align_of, size_of};
use std::{ptr, slice};

#[cfg(test)]
#[path = "arfima/tests.rs"]
mod tests;

const MAX_ROWS: usize = 1000;
const MIN_FIXED_ROWS: usize = 3;
const MIN_FIT_ROWS: usize = 24;
const MAX_HORIZON: usize = 200;
const MAX_DIFFERENCE: f64 = 0.45;
const GRID_POINTS: usize = 17;
const MAX_EVALUATIONS: usize = 128;
const MAX_LIKELIHOOD_WORK: usize = 100_000_000;
const CHECK_EVERY: usize = 32;
const FIT_LENGTH: usize = 7;
const FORECAST_WIDTH: usize = 2;
const CURVATURE_STEP: f64 = 1e-3;
const OBJECTIVE_TIE: f64 = 1e-10;

type CancellationCheck = Option<extern "C" fn() -> i32>;

#[derive(Clone, Copy)]
enum Difference {
    Fixed(f64),
    Estimate,
}

#[derive(Debug)]
enum Failure {
    Input(usize),
    Numeric,
    Insufficient,
    Degenerate,
    Convergence,
    Unsupported,
    Cancelled,
}

fn checkpoint(check: CancellationCheck) -> Result<(), Failure> {
    if check.is_some_and(|poll| poll() != 0) {
        return Err(Failure::Cancelled);
    }
    Ok(())
}

struct Sample {
    values: Vec<f64>,
    scale: f64,
    offset: f64,
    estimate_mean: bool,
}

impl Sample {
    fn new(values: &[f64], estimate_mean: bool, check: CancellationCheck) -> Result<Self, Failure> {
        let mut minimum = f64::INFINITY;
        let mut maximum = f64::NEG_INFINITY;
        for (row, &value) in values.iter().enumerate() {
            if row % CHECK_EVERY == 0 {
                checkpoint(check)?;
            }
            if !value.is_finite() {
                return Err(Failure::Input(row));
            }
            minimum = minimum.min(value);
            maximum = maximum.max(value);
        }
        let offset = if estimate_mean {
            minimum.midpoint(maximum)
        } else {
            0.0
        };
        let scale = (minimum - offset).abs().max((maximum - offset).abs());
        if scale == 0.0 {
            return Err(Failure::Degenerate);
        }
        if !scale.is_finite() {
            return Err(Failure::Numeric);
        }
        let mut normalized = Vec::with_capacity(values.len());
        for (row, &value) in values.iter().enumerate() {
            if row % CHECK_EVERY == 0 {
                checkpoint(check)?;
            }
            normalized.push((value - offset) / scale);
        }
        Ok(Self {
            values: normalized,
            scale,
            offset,
            estimate_mean,
        })
    }
}

struct Durbin {
    difference: f64,
    coefficients: Vec<f64>,
    variance: f64,
}

impl Durbin {
    fn new(difference: f64, capacity: usize) -> Self {
        Self {
            difference,
            coefficients: Vec::with_capacity(capacity),
            variance: 1.0,
        }
    }

    fn advance(&mut self) {
        let order = self.coefficients.len();
        let reflection = self.difference / ((order + 1) as f64 - self.difference);
        for left in 0..order.div_ceil(2) {
            let right = order - 1 - left;
            let a = self.coefficients[left];
            let b = self.coefficients[right];
            self.coefficients[left] = a - reflection * b;
            self.coefficients[right] = b - reflection * a;
        }
        self.coefficients.push(reflection);
        self.variance *= 1.0 - reflection * reflection;
    }

    fn predict(&self, history: &[f64]) -> f64 {
        self.coefficients
            .iter()
            .zip(history.iter().rev())
            .map(|(coefficient, value)| coefficient * value)
            .sum()
    }
}

#[derive(Default)]
struct Innovations {
    design_norm: f64,
    transformed_response: f64,
    energy: f64,
    log_determinant: f64,
}

impl Innovations {
    fn add(&mut self, response: f64, design: f64, variance: f64) {
        let deviation = variance.sqrt();
        let y = response / deviation;
        let x = design / deviation;
        let mut residual = y;
        if x != 0.0 {
            let norm = self.design_norm.hypot(x);
            let cosine = self.design_norm / norm;
            let sine = x / norm;
            residual = (-sine).mul_add(self.transformed_response, cosine * y);
            self.transformed_response = cosine.mul_add(self.transformed_response, sine * y);
            self.design_norm = norm;
        }
        self.energy += residual * residual;
        self.log_determinant += variance.ln();
    }
}

struct Profile {
    durbin: Durbin,
    mean: f64,
    variance: f64,
    log_determinant: f64,
}

fn profile(
    sample: &Sample,
    d: f64,
    extra: usize,
    check: CancellationCheck,
) -> Result<Profile, Failure> {
    let mut durbin = Durbin::new(d, sample.values.len() + extra);
    let mut innovations = Innovations::default();
    for (time, &value) in sample.values.iter().enumerate() {
        if time % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        if time > 0 {
            durbin.advance();
        }
        let prediction = durbin.predict(&sample.values[..time]);
        let design = if sample.estimate_mean {
            1.0 - durbin.coefficients.iter().sum::<f64>()
        } else {
            0.0
        };
        innovations.add(value - prediction, design, durbin.variance);
    }
    let variance = innovations.energy / sample.values.len() as f64;
    let mean = if sample.estimate_mean {
        innovations.transformed_response / innovations.design_norm
    } else {
        0.0
    };
    if !variance.is_finite() || !mean.is_finite() || !innovations.log_determinant.is_finite() {
        return Err(Failure::Numeric);
    }
    if variance.sqrt() <= 32.0 * f64::EPSILON {
        return Err(Failure::Degenerate);
    }
    Ok(Profile {
        durbin,
        mean,
        variance,
        log_determinant: innovations.log_determinant,
    })
}

struct Objective<'a> {
    sample: &'a Sample,
    used: usize,
    limit: usize,
    check: CancellationCheck,
}

impl Objective<'_> {
    fn evaluate(&mut self, d: f64) -> Result<f64, Failure> {
        if self.used == self.limit {
            return Err(Failure::Unsupported);
        }
        self.used += 1;
        let fit = profile(self.sample, d, 0, self.check)?;
        Ok(0.5 * (fit.variance.ln() + fit.log_determinant / self.sample.values.len() as f64))
    }
}

fn refine(
    objective: &mut Objective<'_>,
    mut left: f64,
    mut right: f64,
) -> Result<(f64, f64), Failure> {
    let ratio = 0.618_033_988_749_894_9;
    let mut lower = right - ratio * (right - left);
    let mut upper = left + ratio * (right - left);
    let mut lower_score = objective.evaluate(lower)?;
    let mut upper_score = objective.evaluate(upper)?;
    for _ in 0..64 {
        if right - left <= 2e-8 {
            break;
        }
        if lower_score <= upper_score {
            right = upper;
            upper = lower;
            upper_score = lower_score;
            lower = right - ratio * (right - left);
            lower_score = objective.evaluate(lower)?;
        } else {
            left = lower;
            lower = upper;
            lower_score = upper_score;
            upper = left + ratio * (right - left);
            upper_score = objective.evaluate(upper)?;
        }
    }
    let d = left.midpoint(right);
    Ok((d, objective.evaluate(d)?))
}

fn estimate_difference(sample: &Sample, check: CancellationCheck) -> Result<(f64, usize), Failure> {
    let rows = sample.values.len();
    let limit = MAX_EVALUATIONS.min(MAX_LIKELIHOOD_WORK / (rows * rows)) - 1;
    let mut objective = Objective {
        sample,
        used: 0,
        limit,
        check,
    };
    let points: [f64; GRID_POINTS] = std::array::from_fn(|i| {
        -MAX_DIFFERENCE + 2.0 * MAX_DIFFERENCE * i as f64 / (GRID_POINTS - 1) as f64
    });
    let mut scores = [0.0; GRID_POINTS];
    for (score, d) in scores.iter_mut().zip(points) {
        *score = objective.evaluate(d)?;
    }
    let mut candidates = Vec::new();
    for i in 0..GRID_POINTS {
        let lower = i.saturating_sub(1);
        let upper = (i + 1).min(GRID_POINTS - 1);
        if scores[i] <= scores[lower]
            && scores[i] <= scores[upper]
            && (scores[i] < scores[lower] || scores[i] < scores[upper])
        {
            candidates.push(refine(&mut objective, points[lower], points[upper])?);
        }
    }
    let Some(&(d, best)) = candidates.iter().min_by(|a, b| a.1.total_cmp(&b.1)) else {
        return Err(Failure::Degenerate);
    };
    if d.abs() >= MAX_DIFFERENCE - CURVATURE_STEP {
        return Err(Failure::Convergence);
    }
    if candidates
        .iter()
        .any(|(other, score)| (score - best).abs() <= OBJECTIVE_TIE && (other - d).abs() > 1e-3)
    {
        return Err(Failure::Degenerate);
    }
    let left = objective.evaluate(d - CURVATURE_STEP)?;
    let right = objective.evaluate(d + CURVATURE_STEP)?;
    let curvature = (left - 2.0 * best + right) / (CURVATURE_STEP * CURVATURE_STEP);
    if !curvature.is_finite() || curvature <= 1e-6 {
        return Err(Failure::Degenerate);
    }
    Ok((d, objective.used))
}

fn log_gamma(x: f64) -> f64 {
    const COEFFICIENTS: [f64; 9] = [
        0.99999999999980993,
        676.5203681218851,
        -1259.1392167224028,
        771.32342877765313,
        -176.61502916214059,
        12.507343278686905,
        -0.13857109526572012,
        9.9843695780195716e-6,
        1.5056327351493116e-7,
    ];
    if x < 0.5 {
        let pi = std::f64::consts::PI;
        return (pi / (pi * x).sin()).ln() - log_gamma(1.0 - x);
    }
    let x = x - 1.0;
    let mut sum = COEFFICIENTS[0];
    for (index, value) in COEFFICIENTS.iter().enumerate().skip(1) {
        sum += value / (x + index as f64);
    }
    let t = x + 7.5;
    0.5 * std::f64::consts::TAU.ln() + (x + 0.5) * t.ln() - t + sum.ln()
}

fn variance_factor(d: f64) -> f64 {
    if d == 0.0 {
        1.0
    } else {
        (log_gamma(1.0 - 2.0 * d) - 2.0 * log_gamma(1.0 - d)).exp()
    }
}

struct Fit {
    header: [f64; FIT_LENGTH],
    forecast: Vec<[f64; FORECAST_WIDTH]>,
}

fn predict(
    sample: &Sample,
    mut durbin: Durbin,
    normalized_mean: f64,
    marginal_variance: f64,
    horizon: usize,
    check: CancellationCheck,
) -> Result<Vec<[f64; FORECAST_WIDTH]>, Failure> {
    let mut history = Vec::with_capacity(sample.values.len() + horizon);
    history.extend(sample.values.iter().map(|value| value - normalized_mean));
    let mut loadings = vec![0.0; horizon * horizon];
    let mut forecast = Vec::with_capacity(horizon);
    for step in 0..horizon {
        checkpoint(check)?;
        durbin.advance();
        let conditional_centered = durbin.predict(&history);
        history.push(conditional_centered);
        let mean = sample
            .scale
            .mul_add(normalized_mean + conditional_centered, sample.offset);
        let (past, remainder) = loadings.split_at_mut(step * horizon);
        let row = &mut remainder[..horizon];
        row[step] = durbin.variance.sqrt();
        for lag in 1..=step {
            let previous = (step - lag) * horizon;
            let coefficient = durbin.coefficients[lag - 1];
            for j in 0..=step - lag {
                row[j] += coefficient * past[previous + j];
            }
        }
        let ratio: f64 = row[..=step].iter().map(|value| value * value).sum();
        let variance = marginal_variance * ratio;
        if !mean.is_finite() || !variance.is_normal() || ratio > 1.0 + 1e-10 {
            return Err(Failure::Numeric);
        }
        forecast.push([mean, variance]);
    }
    Ok(forecast)
}

fn fit(
    values: &[f64],
    horizon: usize,
    difference: Difference,
    estimate_mean: bool,
    check: CancellationCheck,
) -> Result<Fit, Failure> {
    if values.len() > MAX_ROWS {
        return Err(Failure::Unsupported);
    }
    if !(1..=MAX_HORIZON).contains(&horizon) {
        return Err(Failure::Input(usize::MAX));
    }
    let minimum = match difference {
        Difference::Fixed(d) if d.is_finite() && d.abs() <= MAX_DIFFERENCE => MIN_FIXED_ROWS,
        Difference::Fixed(_) => return Err(Failure::Unsupported),
        Difference::Estimate => MIN_FIT_ROWS,
    };
    if values.len() < minimum {
        return Err(Failure::Insufficient);
    }
    let sample = Sample::new(values, estimate_mean, check)?;
    let (d, evaluations) = match difference {
        Difference::Fixed(d) => (d, 0),
        Difference::Estimate => estimate_difference(&sample, check)?,
    };
    let Profile {
        durbin,
        mean,
        variance,
        log_determinant,
    } = profile(&sample, d, horizon, check)?;
    let deviation = sample.scale * variance.sqrt();
    let marginal_variance = deviation * deviation;
    let innovation_variance = marginal_variance / variance_factor(d);
    let level = sample.scale.mul_add(mean, sample.offset);
    if !marginal_variance.is_normal() || !innovation_variance.is_normal() || !level.is_finite() {
        return Err(Failure::Numeric);
    }
    let n = values.len() as f64;
    let log_likelihood =
        -0.5 * (n * (std::f64::consts::TAU.ln() + 1.0 + marginal_variance.ln()) + log_determinant);
    if !log_likelihood.is_finite() {
        return Err(Failure::Numeric);
    }
    let forecast = predict(&sample, durbin, mean, marginal_variance, horizon, check)?;
    checkpoint(check)?;
    Ok(Fit {
        header: [
            d,
            level,
            innovation_variance,
            marginal_variance,
            log_likelihood,
            n,
            (evaluations + 1) as f64,
        ],
        forecast,
    })
}

fn region<T>(pointer: *const T, length: usize) -> Option<(usize, usize)> {
    let start = pointer as usize;
    let bytes = length.checked_mul(size_of::<T>())?;
    if start == 0 || start % align_of::<T>() != 0 || bytes > isize::MAX as usize {
        return None;
    }
    Some((start, start.checked_add(bytes)?))
}

/// Fits Gaussian ARFIMA(0,d,0) on a complete time grid and returns finite-sample forecasts.
/// Difference mode 0 fixes d. Mode 1 estimates d and requires the input d to be zero.
/// Mean mode 0 uses a zero level. Mode 1 estimates a constant level.
///
/// # Safety
/// Pointers must refer to the declared valid buffers for the entire call.
/// The input must be initialized and the optional callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_arfima_fit(
    values: *const f64,
    rows: usize,
    horizon: usize,
    difference_mode: i32,
    difference: f64,
    mean_mode: i32,
    estimates: *mut f64,
    estimates_len: usize,
    forecasts: *mut f64,
    forecasts_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    let difference = match difference_mode {
        0 if difference.is_finite() && difference.abs() <= MAX_DIFFERENCE => {
            Difference::Fixed(difference)
        }
        1 if difference == 0.0 => Difference::Estimate,
        _ => return 6,
    };
    if rows > MAX_ROWS || !matches!(mean_mode, 0 | 1) {
        return 6;
    }
    if rows == 0
        || !(1..=MAX_HORIZON).contains(&horizon)
        || estimates_len != FIT_LENGTH
        || forecasts_len != FORECAST_WIDTH * horizon
    {
        return 1;
    }
    let [Some(input), Some(estimate), Some(forecast), Some(error)] = [
        region(values, rows),
        region(estimates, estimates_len),
        region(forecasts, forecasts_len),
        region(error_index, 1),
    ] else {
        return 1;
    };
    let mut regions = [input, estimate, forecast, error];
    regions.sort_unstable();
    if regions.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return 1;
    }
    unsafe { error_index.write(usize::MAX) };
    let input = unsafe { slice::from_raw_parts(values, rows) };
    match fit(input, horizon, difference, mean_mode == 1, check) {
        Ok(fit) => {
            unsafe {
                ptr::copy_nonoverlapping(fit.header.as_ptr(), estimates, estimates_len);
                ptr::copy_nonoverlapping(fit.forecast.as_ptr().cast(), forecasts, forecasts_len);
            }
            0
        }
        Err(Failure::Input(index)) => {
            unsafe { error_index.write(index) };
            1
        }
        Err(Failure::Numeric) => 2,
        Err(Failure::Insufficient) => 3,
        Err(Failure::Degenerate) => 4,
        Err(Failure::Convergence) => 5,
        Err(Failure::Unsupported) => 6,
        Err(Failure::Cancelled) => 7,
    }
}
