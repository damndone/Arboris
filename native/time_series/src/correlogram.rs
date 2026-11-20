use std::mem::{swap, MaybeUninit};
use std::slice;

use super::{INVALID_INPUT, MAX_OBSERVATIONS, NUMERIC_FAILURE};

const MAX_LAG: usize = 200;
const NON_FINITE_OBSERVATION: i32 = 3;
const CONSTANT_SERIES: i32 = 4;
const CANCELLED: i32 = 5;

type CancellationCheck = Option<extern "C" fn() -> i32>;

enum Failure {
    Observation(usize),
    Constant,
    Numeric(usize),
    Cancelled,
}

fn check_cancellation(check: CancellationCheck) -> Result<(), Failure> {
    if check.is_some_and(|poll| poll() != 0) {
        return Err(Failure::Cancelled);
    }
    Ok(())
}

fn compute(
    values: &[f64],
    max_lag: usize,
    check: CancellationCheck,
) -> Result<(Vec<f64>, Vec<f64>), Failure> {
    check_cancellation(check)?;
    let mut minimum = f64::INFINITY;
    let mut maximum = f64::NEG_INFINITY;
    for (index, &value) in values.iter().enumerate() {
        if !value.is_finite() {
            return Err(Failure::Observation(index));
        }
        minimum = minimum.min(value);
        maximum = maximum.max(value);
    }
    if minimum == maximum {
        return Err(Failure::Constant);
    }

    let offset = minimum.midpoint(maximum);
    let scale = (maximum - offset).max(offset - minimum);
    let mut centered: Vec<_> = values
        .iter()
        .map(|value| (value - offset) / scale)
        .collect();
    let mean = centered.iter().sum::<f64>() / values.len() as f64;
    centered.iter_mut().for_each(|value| *value -= mean);
    let sum_squares = centered.iter().map(|value| value * value).sum::<f64>();
    if sum_squares <= 0.0 || !sum_squares.is_finite() {
        return Err(Failure::Numeric(0));
    }

    let mut acf = vec![1.0; max_lag + 1];
    for (lag, estimate) in acf.iter_mut().enumerate().skip(1) {
        check_cancellation(check)?;
        let cross_products = centered
            .iter()
            .zip(&centered[lag..])
            .map(|(left, right)| left * right)
            .sum::<f64>();
        *estimate = cross_products / sum_squares;
    }

    let mut pacf = Vec::with_capacity(max_lag);
    let mut coefficients = vec![0.0; max_lag];
    let mut updated = vec![0.0; max_lag];
    let mut variance = 1.0;
    for lag in 1..=max_lag {
        check_cancellation(check)?;
        let previous = &coefficients[..lag - 1];
        let predicted = previous
            .iter()
            .zip(acf[1..lag].iter().rev())
            .map(|(coefficient, correlation)| coefficient * correlation)
            .sum::<f64>();
        let reflection = (acf[lag] - predicted) / variance;
        variance *= 1.0 - reflection * reflection;
        if !variance.is_finite() || variance <= f64::EPSILON {
            return Err(Failure::Numeric(lag));
        }
        for (slot, (forward, backward)) in updated
            .iter_mut()
            .zip(previous.iter().zip(previous.iter().rev()))
        {
            *slot = forward - reflection * backward;
        }
        updated[lag - 1] = reflection;
        swap(&mut updated, &mut coefficients);
        pacf.push(reflection);
    }
    Ok((acf, pacf))
}

/// Writes ACF lags 0 through `max_lag` followed by PACF lags 1 through `max_lag`.
/// A nonzero status invalidates the result. `error_index` is an observation or
/// lag index when relevant and `usize::MAX` otherwise.
///
/// # Safety
/// Nonnull pointers must refer to valid, separate memory of the stated lengths
/// for the whole call. The input must be initialized. The optional callback
/// must stay valid and must not unwind across the C ABI.
#[no_mangle]
pub unsafe extern "C" fn arboris_correlogram(
    values: *const f64,
    count: usize,
    max_lag: usize,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    if error_index.is_null() || !error_index.is_aligned() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    if !(2..=MAX_OBSERVATIONS).contains(&count)
        || !(1..=MAX_LAG).contains(&max_lag)
        || max_lag >= count
        || output_len != 2 * max_lag + 1
        || values.is_null()
        || !values.is_aligned()
        || output.is_null()
        || !output.is_aligned()
    {
        return INVALID_INPUT;
    }

    let values = unsafe { slice::from_raw_parts(values, count) };
    match compute(values, max_lag, check) {
        Ok((acf, pacf)) => {
            let output =
                unsafe { slice::from_raw_parts_mut(output.cast::<MaybeUninit<f64>>(), output_len) };
            for (slot, value) in output.iter_mut().zip(acf.into_iter().chain(pacf)) {
                slot.write(value);
            }
            0
        }
        Err(Failure::Observation(index)) => {
            unsafe { error_index.write(index) };
            NON_FINITE_OBSERVATION
        }
        Err(Failure::Constant) => CONSTANT_SERIES,
        Err(Failure::Numeric(lag)) => {
            unsafe { error_index.write(lag) };
            NUMERIC_FAILURE
        }
        Err(Failure::Cancelled) => CANCELLED,
    }
}
