use std::mem::{align_of, size_of};
use std::{ptr, slice};

#[path = "markov/optimizer.rs"]
mod optimizer;

#[cfg(test)]
#[path = "markov/tests.rs"]
mod tests;

const MAX_ROWS: usize = 10_000;
const MIN_OBSERVED: usize = 24;
const MAX_HORIZON: usize = 200;
const MAX_TRACE: usize = 512;
const CHECK_EVERY: usize = 512;
const FIT_LENGTH: usize = 12;
const TRACE_WIDTH: usize = 6;
const FORECAST_WIDTH: usize = 4;
const DIMENSIONS: usize = 5;
const STARTS: usize = 6;
const MAX_ROW_VISITS: usize = 12_000_000;

type Point = [f64; DIMENSIONS];
type Probability = [f64; 2];
type TraceRow = [f64; TRACE_WIDTH];
type ForecastRow = [f64; FORECAST_WIDTH];
type CancellationCheck = Option<extern "C" fn() -> i32>;

#[derive(Debug)]
enum Failure {
    Input(usize),
    Numeric,
    Insufficient,
    Degenerate,
    Convergence,
    WorkLimit,
    Cancelled,
}

fn checkpoint(check: CancellationCheck) -> Result<(), Failure> {
    if check.is_some_and(|poll| poll() != 0) {
        return Err(Failure::Cancelled);
    }
    Ok(())
}

#[derive(Clone, Copy)]
struct Parameters {
    means: [f64; 2],
    variance: f64,
    stay: [f64; 2],
}

impl Parameters {
    fn point(self) -> Point {
        [
            self.means[0].midpoint(self.means[1]),
            (self.means[1] - self.means[0]).ln(),
            self.variance.ln(),
            (self.stay[0] / (1.0 - self.stay[0])).ln(),
            (self.stay[1] / (1.0 - self.stay[1])).ln(),
        ]
    }

    fn from_point([center, log_gap, log_variance, low, high]: Point) -> Self {
        let half_gap = 0.5 * log_gap.exp();
        Self {
            means: [center - half_gap, center + half_gap],
            variance: log_variance.exp(),
            stay: [low, high].map(|value| 1.0 / (1.0 + (-value).exp())),
        }
    }

    fn stationary(self) -> Probability {
        let exits = [1.0 - self.stay[0], 1.0 - self.stay[1]];
        let sum = exits[0] + exits[1];
        [exits[1] / sum, exits[0] / sum]
    }

    fn transition(self) -> [[f64; 2]; 2] {
        [
            [self.stay[0], 1.0 - self.stay[0]],
            [1.0 - self.stay[1], self.stay[1]],
        ]
    }

    fn advance(self, weights: Probability) -> Probability {
        let transition = self.transition();
        let low = weights[0] * transition[0][0] + weights[1] * transition[1][0];
        let high = weights[0] * transition[0][1] + weights[1] * transition[1][1];
        let sum = low + high;
        [low / sum, high / sum]
    }

    fn observation(self, weights: Probability) -> [f64; 2] {
        let gap = self.means[1] - self.means[0];
        [
            weights[0] * self.means[0] + weights[1] * self.means[1],
            self.variance + weights[0] * weights[1] * gap * gap,
        ]
    }
}

#[derive(Clone, Copy, Default)]
struct Moments {
    weight: f64,
    mean: f64,
    centered_energy: f64,
}

impl Moments {
    fn add(&mut self, value: f64, weight: f64) {
        if weight == 0.0 {
            return;
        }
        self.weight += weight;
        let error = value - self.mean;
        self.mean += (weight / self.weight) * error;
        self.centered_energy += weight * error * (value - self.mean);
    }
}

struct Expectation {
    log_likelihood: f64,
    last_filtered: Probability,
    initial_smoothed: Probability,
    expected_transitions: [[f64; 2]; 2],
    moments: [Moments; 2],
}

impl Expectation {
    fn objective(&self, parameters: Parameters, observed: usize) -> Result<(f64, Point), Failure> {
        let initial = parameters.stationary();
        let mut mean_score = [0.0; 2];
        let mut transition_score = [0.0; 2];
        let mut energy = 0.0;
        for regime in 0..2 {
            let m = self.moments[regime];
            let displacement = m.mean - parameters.means[regime];
            mean_score[regime] = m.weight * displacement / parameters.variance;
            energy += m.centered_energy + m.weight * displacement * displacement;
            let counts = self.expected_transitions[regime];
            let stay = parameters.stay[regime];
            transition_score[regime] = counts[regime] - stay * (counts[0] + counts[1])
                + stay * (self.initial_smoothed[regime] - initial[regime]);
        }
        let n = observed as f64;
        let half_gap = 0.5 * (parameters.means[1] - parameters.means[0]);
        let gradient = [
            mean_score[0] + mean_score[1],
            half_gap * (mean_score[1] - mean_score[0]),
            0.5 * (energy / parameters.variance - n),
            transition_score[0],
            transition_score[1],
        ]
        .map(|score| -score / n);
        if !gradient.iter().all(|value| value.is_finite()) {
            return Err(Failure::Numeric);
        }
        Ok((-self.log_likelihood / n, gradient))
    }
}

fn expectation(
    values: &[f64],
    parameters: Parameters,
    filtered: &mut [Probability],
    trace: &mut [TraceRow],
    check: CancellationCheck,
) -> Result<Expectation, Failure> {
    let mut predicted = parameters.stationary();
    let deviation = parameters.variance.sqrt();
    let log_normalizer = -0.5 * (std::f64::consts::TAU.ln() + parameters.variance.ln());
    let trace_start = values.len() - trace.len();
    let mut likelihood = 0.0;
    let mut correction = 0.0;
    for (time, (&value, slot)) in values.iter().zip(filtered.iter_mut()).enumerate() {
        if time % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let (weights, contribution) = if value.is_nan() {
            (predicted, 0.0)
        } else {
            let low = (value - parameters.means[0]) / deviation;
            let high = (value - parameters.means[1]) / deviation;
            let low_log = predicted[0].ln() - (0.5 * low) * low;
            let high_log = predicted[1].ln() - (0.5 * high) * high;
            let tail = (-(low_log - high_log).abs()).exp();
            let denominator = 1.0 + tail;
            let weights = if low_log >= high_log {
                [1.0 / denominator, tail / denominator]
            } else {
                [tail / denominator, 1.0 / denominator]
            };
            (
                weights,
                log_normalizer + low_log.max(high_log) + tail.ln_1p(),
            )
        };
        let addition = contribution - correction;
        let next = likelihood + addition;
        correction = (next - likelihood) - addition;
        likelihood = next;
        if !likelihood.is_finite() || !weights.iter().all(|weight| weight.is_finite()) {
            return Err(Failure::Numeric);
        }
        *slot = weights;
        if time >= trace_start {
            let [mean, variance] = parameters.observation(predicted);
            trace[time - trace_start] =
                [predicted[0], weights[0], 0.0, mean, variance, contribution];
        }
        predicted = parameters.advance(weights);
    }

    let last = filtered[values.len() - 1];
    let mut smoothed = last;
    let mut expected_transitions = [[0.0; 2]; 2];
    let mut moments = [Moments::default(); 2];
    let transition = parameters.transition();
    for (index, (&value, &previous)) in values.iter().zip(filtered.iter()).enumerate().rev() {
        let step = values.len() - 1 - index;
        if step % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        if step > 0 {
            let prediction = parameters.advance(previous);
            let relative = [smoothed[0] / prediction[0], smoothed[1] / prediction[1]];
            let mut joint = [[0.0; 2]; 2];
            let mut total = 0.0;
            for i in 0..2 {
                for j in 0..2 {
                    joint[i][j] = previous[i] * transition[i][j] * relative[j];
                    total += joint[i][j];
                }
            }
            if !total.is_finite() || total <= 0.0 {
                return Err(Failure::Numeric);
            }
            for i in 0..2 {
                smoothed[i] = (joint[i][0] + joint[i][1]) / total;
                for j in 0..2 {
                    let probability = joint[i][j] / total;
                    expected_transitions[i][j] += probability;
                }
            }
        }
        if !value.is_nan() {
            for (moment, probability) in moments.iter_mut().zip(smoothed) {
                moment.add(value, probability);
            }
        }
        if index >= trace_start {
            trace[index - trace_start][2] = smoothed[0];
        }
    }
    Ok(Expectation {
        log_likelihood: likelihood,
        last_filtered: last,
        initial_smoothed: smoothed,
        expected_transitions,
        moments,
    })
}

struct Sample {
    values: Vec<f64>,
    center: f64,
    scale: f64,
    observed: usize,
}

impl Sample {
    fn new(values: &[f64], check: CancellationCheck) -> Result<Self, Failure> {
        let mut minimum = f64::INFINITY;
        let mut maximum = f64::NEG_INFINITY;
        let mut observed = 0;
        let mut distinct = [0.0; 2];
        let mut distinct_count = 0;
        for (index, &value) in values.iter().enumerate() {
            if index % CHECK_EVERY == 0 {
                checkpoint(check)?;
            }
            if value.is_nan() {
                continue;
            }
            if !value.is_finite() {
                return Err(Failure::Input(index));
            }
            observed += 1;
            minimum = minimum.min(value);
            maximum = maximum.max(value);
            if distinct_count <= 2 && !distinct[..distinct_count].contains(&value) {
                if distinct_count < 2 {
                    distinct[distinct_count] = value;
                }
                distinct_count += 1;
            }
        }
        if observed < MIN_OBSERVED {
            return Err(Failure::Insufficient);
        }
        if distinct_count < 3 {
            return Err(Failure::Degenerate);
        }
        let center = minimum.midpoint(maximum);
        let scale = (maximum - center).max(center - minimum);
        if !scale.is_finite() || scale <= 0.0 {
            return Err(Failure::Numeric);
        }
        let mut normalized = Vec::with_capacity(values.len());
        for (index, &value) in values.iter().enumerate() {
            if index % CHECK_EVERY == 0 {
                checkpoint(check)?;
            }
            normalized.push((value - center) / scale);
        }
        Ok(Self {
            values: normalized,
            center,
            scale,
            observed,
        })
    }

    fn starts(&self, check: CancellationCheck) -> Result<[Point; STARTS], Failure> {
        let mut order = Vec::with_capacity(self.observed);
        let mut moments = Moments::default();
        for (index, &value) in self.values.iter().enumerate() {
            if index % CHECK_EVERY == 0 {
                checkpoint(check)?;
            }
            if value.is_finite() {
                order.push(value);
                moments.add(value, 1.0);
            }
        }
        order.sort_unstable_by(f64::total_cmp);
        checkpoint(check)?;
        let variance = moments.centered_energy / self.observed as f64;
        let deviation = variance.sqrt();
        let options = [
            (0.20, 0.80, 0.35, [0.86, 0.86]),
            (0.30, 0.70, 0.60, [0.55, 0.55]),
            (0.20, 0.80, 0.55, [0.25, 0.25]),
            (0.15, 0.70, 0.55, [0.94, 0.72]),
            (0.30, 0.85, 0.55, [0.72, 0.94]),
            (0.10, 0.90, 0.40, [0.94, 0.94]),
        ];
        Ok(options.map(|(lower, upper, ratio, stay)| {
            let quantile =
                |fraction: f64| order[(fraction * (order.len() - 1) as f64).round() as usize];
            let mut means = [quantile(lower), quantile(upper)];
            if means[1] - means[0] < 0.05 * deviation {
                means = [
                    moments.mean - 0.6 * deviation,
                    moments.mean + 0.6 * deviation,
                ];
            }
            Parameters {
                means,
                variance: (variance * ratio).max(1e-8),
                stay,
            }
            .point()
        }))
    }

    fn original_mean(&self, normalized: f64) -> Result<f64, Failure> {
        let mean = self.scale.mul_add(normalized, self.center);
        if !mean.is_finite() {
            return Err(Failure::Numeric);
        }
        Ok(mean)
    }

    fn original_variance(&self, normalized: f64) -> Result<f64, Failure> {
        let deviation = self.scale * normalized.sqrt();
        let variance = deviation * deviation;
        if !variance.is_normal() {
            return Err(Failure::Numeric);
        }
        Ok(variance)
    }
}

fn forecast(parameters: Parameters, mut filtered: Probability, horizon: usize) -> Vec<ForecastRow> {
    let mut future = Vec::with_capacity(horizon);
    for _ in 0..horizon {
        filtered = parameters.advance(filtered);
        let [mean, variance] = parameters.observation(filtered);
        future.push([filtered[0], filtered[1], mean, variance]);
    }
    future
}

struct Fit {
    header: [f64; FIT_LENGTH],
    trace: Vec<TraceRow>,
    forecast: Vec<ForecastRow>,
}

fn fit(
    values: &[f64],
    horizon: usize,
    trace_rows: usize,
    check: CancellationCheck,
) -> Result<Fit, Failure> {
    if values.len() > MAX_ROWS {
        return Err(Failure::WorkLimit);
    }
    if !(1..=MAX_HORIZON).contains(&horizon) || trace_rows > MAX_TRACE.min(values.len()) {
        return Err(Failure::Input(usize::MAX));
    }
    let sample = Sample::new(values, check)?;
    let starts = sample.starts(check)?;
    let mut filtered = vec![[0.0; 2]; values.len()];
    let evaluations = (MAX_ROW_VISITS / (2 * values.len())).saturating_sub(3);
    let (point, iterations) = optimizer::minimize(starts, evaluations, |point| {
        let parameters = Parameters::from_point(point);
        expectation(&sample.values, parameters, &mut filtered, &mut [], check)?
            .objective(parameters, sample.observed)
    })?;
    let parameters = Parameters::from_point(point);
    let mut trace = vec![[0.0; TRACE_WIDTH]; trace_rows];
    let evidence = expectation(&sample.values, parameters, &mut filtered, &mut trace, check)?;
    let regime_counts = evidence.moments.map(|moment| moment.weight);
    if regime_counts
        .iter()
        .any(|&weight| weight < (0.02 * sample.observed as f64).max(3.0))
        || parameters.means[1] - parameters.means[0] <= 0.05 * parameters.variance.sqrt()
    {
        return Err(Failure::Degenerate);
    }
    let means = [
        sample.original_mean(parameters.means[0])?,
        sample.original_mean(parameters.means[1])?,
    ];
    if means[0] >= means[1] {
        return Err(Failure::Degenerate);
    }
    let log_scale = sample.scale.ln();
    let original_likelihood = evidence.log_likelihood - sample.observed as f64 * log_scale;
    if !original_likelihood.is_finite() {
        return Err(Failure::Numeric);
    }
    for (row, &observed) in trace.iter_mut().zip(&values[values.len() - trace_rows..]) {
        row[3] = sample.original_mean(row[3])?;
        row[4] = sample.original_variance(row[4])?;
        if observed.is_finite() {
            row[5] -= log_scale;
        }
    }
    let mut future = forecast(parameters, evidence.last_filtered, horizon);
    for row in &mut future {
        row[2] = sample.original_mean(row[2])?;
        row[3] = sample.original_variance(row[3])?;
    }
    let header = [
        means[0],
        means[1],
        sample.original_variance(parameters.variance)?,
        parameters.stay[0],
        parameters.stay[1],
        original_likelihood,
        sample.observed as f64,
        iterations as f64,
        regime_counts[0],
        regime_counts[1],
        evidence.last_filtered[0],
        evidence.last_filtered[1],
    ];
    checkpoint(check)?;
    Ok(Fit {
        header,
        trace,
        forecast: future,
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

/// Fits two Gaussian means, a shared variance and a stationary two-state chain.
/// Training trace distinguishes predicted, filtered and smoothed probabilities.
/// Future rows give the two mixture weights, predictive mean and variance.
/// Nonzero status leaves all result buffers untouched.
///
/// # Safety
/// Every nonempty buffer must be valid for its declared length and the input
/// must be initialized. The optional callback must remain valid and must not
/// unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_markov_switching_fit(
    values: *const f64,
    rows: usize,
    horizon: usize,
    trace_rows: usize,
    estimates: *mut f64,
    estimates_len: usize,
    trace: *mut f64,
    trace_len: usize,
    forecasts: *mut f64,
    forecast_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if rows > MAX_ROWS {
        return 6;
    }
    if rows == 0
        || !(1..=MAX_HORIZON).contains(&horizon)
        || trace_rows > MAX_TRACE.min(rows)
        || estimates_len != FIT_LENGTH
        || trace_len != TRACE_WIDTH * trace_rows
        || forecast_len != FORECAST_WIDTH * horizon
    {
        return 1;
    }
    let trace_region = if trace_len == 0 {
        Some((0, 0))
    } else {
        region(trace, trace_len)
    };
    let [Some(input), Some(fit_region), Some(trace_region), Some(forecast_region), Some(error_region)] = [
        region(values, rows),
        region(estimates, estimates_len),
        trace_region,
        region(forecasts, forecast_len),
        region(error_index, 1),
    ] else {
        return 1;
    };
    let mut regions = [
        input,
        fit_region,
        trace_region,
        forecast_region,
        error_region,
    ];
    regions.sort_unstable();
    if regions.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return 1;
    }
    unsafe { error_index.write(usize::MAX) };
    let input = unsafe { slice::from_raw_parts(values, rows) };
    match fit(input, horizon, trace_rows, check) {
        Ok(fitted) => {
            unsafe {
                ptr::copy_nonoverlapping(fitted.header.as_ptr(), estimates, estimates_len);
                if trace_len != 0 {
                    ptr::copy_nonoverlapping(fitted.trace.as_ptr().cast(), trace, trace_len);
                }
                ptr::copy_nonoverlapping(fitted.forecast.as_ptr().cast(), forecasts, forecast_len);
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
        Err(Failure::WorkLimit) => 6,
        Err(Failure::Cancelled) => 7,
    }
}
