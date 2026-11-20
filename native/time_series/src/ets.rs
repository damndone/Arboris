use std::{ptr, slice};

use super::{INVALID_INPUT, MAX_OBSERVATIONS, NUMERIC_FAILURE};

const MAX_PERIOD: usize = 366;
const MAX_HORIZON: usize = 200;
const MAX_TRACE_ROWS: usize = 512;
const TRACE_WIDTH: usize = 5;
const FORECAST_WIDTH: usize = 2;
const SUMMARY_WIDTH: usize = 6;
const ALPHA_GRID_SIZE: usize = 20;
const CHECK_EVERY: usize = 1024;
const NON_FINITE_OBSERVATION: i32 = 3;
const FORECAST_FAILURE: i32 = 4;
const CANCELLED: i32 = 5;
const ALPHA_UNIDENTIFIED: i32 = 6;

type CancellationCheck = Option<extern "C" fn() -> i32>;

#[derive(Clone, Copy)]
struct Smoothing {
    alpha: f64,
    beta: f64,
    gamma: f64,
}

impl Smoothing {
    fn gains(self) -> [f64; 3] {
        [
            self.alpha,
            self.alpha * self.beta,
            (1.0 - self.alpha) * self.gamma,
        ]
    }
}

#[derive(Clone)]
struct State {
    level: f64,
    trend: f64,
    seasonal: Vec<f64>,
}

impl State {
    fn step(&mut self, phase: usize, observed: f64, gains: [f64; 3]) -> (f64, f64) {
        let projection = self.level + self.trend;
        let seasonal = &mut self.seasonal[phase];
        let prediction = projection + *seasonal;
        let error = observed - prediction;
        self.level = projection + gains[0] * error;
        self.trend += gains[1] * error;
        *seasonal += gains[2] * error;
        (prediction, error)
    }
}

struct Fit {
    state: State,
    sse: f64,
    residual_variance: f64,
    trace: Vec<f64>,
}

enum Failure {
    Observation(usize),
    Fit(usize),
    Forecast(usize),
    Cancelled,
    FlatObjective,
}

fn checkpoint(check: CancellationCheck) -> Result<(), Failure> {
    if check.is_some_and(|poll| poll() != 0) {
        return Err(Failure::Cancelled);
    }
    Ok(())
}

fn validate_values(values: &[f64], check: CancellationCheck) -> Result<(), Failure> {
    for (index, value) in values.iter().enumerate() {
        if index % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        if !value.is_finite() {
            return Err(Failure::Observation(index));
        }
    }
    Ok(())
}

fn average(values: &[f64]) -> f64 {
    let sum = values.iter().sum::<f64>();
    if sum.is_finite() {
        return sum / values.len() as f64;
    }
    let scale = values.iter().map(|value| value.abs()).fold(0.0, f64::max);
    (values.iter().map(|value| value / scale).sum::<f64>() / values.len() as f64) * scale
}

fn initialize(values: &[f64], period: usize) -> Result<State, Failure> {
    let first = &values[..period];
    let second = &values[period..2 * period];
    let first_average = average(first);
    let second_average = average(second);
    let change = second_average - first_average;
    let trend = if change.is_finite() {
        change / period as f64
    } else {
        second_average / period as f64 - first_average / period as f64
    };
    let middle_phase = (period - 1) as f64 / 2.0;
    let level = second_average + trend * middle_phase;
    let average_center = first_average.midpoint(second_average);
    let seasonal: Vec<_> = first
        .iter()
        .zip(second)
        .enumerate()
        .map(|(phase, (&left, &right))| {
            left.midpoint(right) - average_center - trend * (phase as f64 - middle_phase)
        })
        .collect();
    if !level.is_finite() || !trend.is_finite() || !seasonal.iter().all(|value| value.is_finite()) {
        return Err(Failure::Fit(2 * period - 1));
    }
    Ok(State {
        level,
        trend,
        seasonal,
    })
}

fn fit(
    values: &[f64],
    initial: &State,
    smoothing: Smoothing,
    check: CancellationCheck,
) -> Result<Fit, Failure> {
    let period = initial.seasonal.len();
    let warmup = 2 * period;
    let first_trace = warmup.max(values.len().saturating_sub(MAX_TRACE_ROWS));
    let mut trace = Vec::with_capacity(TRACE_WIDTH * (values.len() - first_trace));
    let mut state = initial.clone();
    let gains = smoothing.gains();
    let mut sse = 0.0;
    let mut residual_mean = 0.0;
    let mut residual_m2 = 0.0;
    for (index, &observed) in values.iter().enumerate().skip(warmup) {
        let scored = index - warmup;
        if scored % CHECK_EVERY == 0 {
            checkpoint(check)?;
        }
        let phase = index % period;
        let (prediction, error) = state.step(phase, observed, gains);
        let seasonal = state.seasonal[phase];
        let squared_error = error * error;
        sse += squared_error;
        let delta = error - residual_mean;
        residual_mean += delta / (scored + 1) as f64;
        residual_m2 += delta * (error - residual_mean);
        if (squared_error == 0.0 && error != 0.0)
            || ![
                prediction,
                state.level,
                state.trend,
                seasonal,
                sse,
                residual_m2,
            ]
            .iter()
            .all(|value| value.is_finite())
        {
            return Err(Failure::Fit(index));
        }
        if index >= first_trace {
            trace.extend([prediction, error, state.level, state.trend, seasonal]);
        }
    }
    let residual_variance = residual_m2 / (values.len() - warmup - 1) as f64;
    if residual_variance < 0.0 || (residual_variance == 0.0 && residual_m2 > 0.0) {
        return Err(Failure::Fit(values.len() - 1));
    }
    Ok(Fit {
        state,
        sse,
        residual_variance,
        trace,
    })
}

fn forecast(
    output: &mut Vec<f64>,
    fit: &Fit,
    smoothing: Smoothing,
    next_phase: usize,
    horizon: usize,
    check: CancellationCheck,
) -> Result<(), Failure> {
    let period = fit.state.seasonal.len();
    let mut variance_factor = 1.0;
    for step in 1..=horizon {
        checkpoint(check)?;
        let lag = step - 1;
        if lag > 0 {
            let mut impulse = smoothing.alpha * (1.0 + lag as f64 * smoothing.beta);
            if lag % period == 0 {
                impulse += (1.0 - smoothing.alpha) * smoothing.gamma;
            }
            variance_factor += impulse * impulse;
        }
        let mean = fit.state.level
            + step as f64 * fit.state.trend
            + fit.state.seasonal[(next_phase + lag) % period];
        let variance = fit.residual_variance * variance_factor;
        if !mean.is_finite() || !variance.is_finite() {
            return Err(Failure::Forecast(step));
        }
        output.extend([mean, variance]);
    }
    Ok(())
}

fn output_length(count: usize, period: usize, horizon: usize) -> usize {
    SUMMARY_WIDTH
        + 2 * period
        + TRACE_WIDTH * (count - 2 * period).min(MAX_TRACE_ROWS)
        + FORECAST_WIDTH * horizon
}

fn compute(
    values: &[f64],
    period: usize,
    horizon: usize,
    smoothing: Smoothing,
    check: CancellationCheck,
) -> Result<Vec<f64>, Failure> {
    validate_values(values, check)?;
    let initial = initialize(values, period)?;
    let fit = fit(values, &initial, smoothing, check)?;
    let mut output = Vec::with_capacity(output_length(values.len(), period, horizon));
    append_result(
        &mut output,
        initial,
        &fit,
        values.len(),
        horizon,
        smoothing,
        check,
    )?;
    Ok(output)
}

fn append_result(
    output: &mut Vec<f64>,
    initial: State,
    fit: &Fit,
    count: usize,
    horizon: usize,
    smoothing: Smoothing,
    check: CancellationCheck,
) -> Result<(), Failure> {
    let period = initial.seasonal.len();
    let next_phase = count % period;
    output.extend([
        initial.level,
        initial.trend,
        fit.state.level,
        fit.state.trend,
        fit.sse,
        fit.residual_variance,
    ]);
    output.extend(initial.seasonal);
    output.extend((0..period).map(|phase| fit.state.seasonal[(next_phase + phase) % period]));
    output.extend_from_slice(&fit.trace);
    forecast(output, fit, smoothing, next_phase, horizon, check)
}

fn fit_alpha(
    values: &[f64],
    period: usize,
    holdout: usize,
    beta: f64,
    gamma: f64,
    check: CancellationCheck,
) -> Result<Vec<f64>, Failure> {
    validate_values(values, check)?;
    let training = &values[..values.len() - holdout];
    let initial = initialize(training, period)?;
    let mut selected = Smoothing {
        alpha: 1.0 / ALPHA_GRID_SIZE as f64,
        beta,
        gamma,
    };
    let mut best = fit(training, &initial, selected, check)?;
    let mut objectives = [0.0; ALPHA_GRID_SIZE];
    objectives[0] = best.sse;
    let mut maximum = best.sse;
    for (index, objective) in objectives.iter_mut().enumerate().skip(1) {
        let smoothing = Smoothing {
            alpha: (index + 1) as f64 / ALPHA_GRID_SIZE as f64,
            beta,
            gamma,
        };
        let candidate = fit(training, &initial, smoothing, check)?;
        *objective = candidate.sse;
        maximum = maximum.max(candidate.sse);
        if candidate.sse < best.sse {
            selected = smoothing;
            best = candidate;
        }
    }
    if maximum == best.sse {
        return Err(Failure::FlatObjective);
    }

    let mut output =
        Vec::with_capacity(1 + ALPHA_GRID_SIZE + output_length(training.len(), period, holdout));
    output.push(selected.alpha);
    output.extend(objectives);
    append_result(
        &mut output,
        initial,
        &best,
        training.len(),
        holdout,
        selected,
        check,
    )?;
    Ok(output)
}

fn valid_dimensions(count: usize, period: usize, horizon: usize) -> bool {
    (2..=MAX_PERIOD).contains(&period)
        && (3 * period..=MAX_OBSERVATIONS).contains(&count)
        && (1..=MAX_HORIZON).contains(&horizon)
}

fn valid_buffers(values: *const f64, output: *mut f64) -> bool {
    !values.is_null() && values.is_aligned() && !output.is_null() && output.is_aligned()
}

unsafe fn publish_result(
    result: Result<Vec<f64>, Failure>,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
) -> i32 {
    match result {
        Ok(values) if values.len() == output_len => {
            unsafe { ptr::copy_nonoverlapping(values.as_ptr(), output, output_len) };
            0
        }
        Ok(_) => INVALID_INPUT,
        Err(Failure::Observation(index)) => {
            unsafe { error_index.write(index) };
            NON_FINITE_OBSERVATION
        }
        Err(Failure::Fit(index)) => {
            unsafe { error_index.write(index) };
            NUMERIC_FAILURE
        }
        Err(Failure::Forecast(step)) => {
            unsafe { error_index.write(step) };
            FORECAST_FAILURE
        }
        Err(Failure::Cancelled) => CANCELLED,
        Err(Failure::FlatObjective) => ALPHA_UNIDENTIFIED,
    }
}

/// Writes a six-value fit summary, two seasonal vectors, a bounded fit trace,
/// and forecast means and variances. A nonzero status invalidates the output.
///
/// # Safety
/// Nonnull pointers must refer to valid, separate buffers of the given lengths.
/// The input must be initialized and stay unchanged for the call. The optional
/// callback must stay valid and may not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_holt_winters_additive(
    values: *const f64,
    count: usize,
    period: usize,
    horizon: usize,
    alpha: f64,
    beta: f64,
    gamma: f64,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if error_index.is_null() || !error_index.is_aligned() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    if !valid_dimensions(count, period, horizon)
        || !(0.0 < alpha && alpha <= 1.0)
        || !(0.0..=1.0).contains(&beta)
        || !(0.0..=1.0).contains(&gamma)
        || output_len != output_length(count, period, horizon)
        || !valid_buffers(values, output)
    {
        return INVALID_INPUT;
    }
    let values = unsafe { slice::from_raw_parts(values, count) };
    let smoothing = Smoothing { alpha, beta, gamma };
    let result = compute(values, period, horizon, smoothing, check);
    unsafe { publish_result(result, output, output_len, error_index) }
}

/// Prepends the selected alpha and 20 training SSEs to the fixed forecast
/// layout. The fit consumes only the training prefix and predicts the suffix.
///
/// # Safety
/// Nonnull pointers must refer to valid, separate buffers of the given lengths.
/// The input must be initialized and stay unchanged for the call. The optional
/// callback must stay valid and may not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_holt_winters_fit_alpha(
    values: *const f64,
    count: usize,
    period: usize,
    holdout: usize,
    beta: f64,
    gamma: f64,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if error_index.is_null() || !error_index.is_aligned() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    let training_count = count.saturating_sub(holdout);
    if count > MAX_OBSERVATIONS
        || !valid_dimensions(training_count, period, holdout)
        || !(0.0..=1.0).contains(&beta)
        || !(0.0..=1.0).contains(&gamma)
        || output_len != 1 + ALPHA_GRID_SIZE + output_length(training_count, period, holdout)
        || !valid_buffers(values, output)
    {
        return INVALID_INPUT;
    }
    let values = unsafe { slice::from_raw_parts(values, count) };
    let result = fit_alpha(values, period, holdout, beta, gamma, check);
    unsafe { publish_result(result, output, output_len, error_index) }
}

mod joint;
