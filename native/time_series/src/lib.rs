//! Scalar Gaussian local-level filtering with a known prior and fixed variances.
#![deny(unsafe_op_in_unsafe_fn)]

use std::mem::MaybeUninit;
use std::slice;

mod arfima;
mod arima;
mod correlogram;
mod egarch;
mod ets;
mod ets_trend;
mod figarch;
mod igarch;
mod markov;
mod scale_fit;
mod var;
mod volatility;

const ROW_WIDTH: usize = 7;
const MAX_OBSERVATIONS: usize = 100_000;
const INVALID_INPUT: i32 = 1;
const NUMERIC_FAILURE: i32 = 2;

struct Parameters {
    process_variance: f64,
    observation_variance: f64,
    initial_mean: f64,
    initial_variance: f64,
}

enum FilterFailure {
    Observation(usize),
    Numeric(usize),
}

fn assimilate(
    mean: f64,
    variance: f64,
    observed: f64,
    r: f64,
    innovation_variance: f64,
) -> (f64, f64, f64) {
    let innovation = observed - mean;
    let filtered_mean = mean + (variance / innovation_variance) * innovation;
    // P*R/(P+R), using a ratio >= 1/2 so small posteriors survive rounding.
    let filtered_variance = variance.min(r) * (variance.max(r) / innovation_variance);
    (filtered_mean, filtered_variance, innovation)
}

fn filter(
    values: &[f64],
    parameters: Parameters,
    output: &mut [MaybeUninit<f64>],
) -> Result<f64, FilterFailure> {
    let Parameters {
        process_variance: q,
        observation_variance: r,
        initial_mean: mut mean,
        initial_variance: mut variance,
    } = parameters;
    let log_two_pi = std::f64::consts::TAU.ln();
    let mut total = 0.0;
    for (index, (&observed, row)) in values
        .iter()
        .zip(output.chunks_exact_mut(ROW_WIDTH))
        .enumerate()
    {
        if index > 0 {
            variance += q;
        }
        let innovation_variance = variance + r;
        if !innovation_variance.is_finite() {
            return Err(FilterFailure::Numeric(index));
        }
        let (filtered_mean, filtered_variance, innovation, log_likelihood) = if observed.is_nan() {
            (mean, variance, f64::NAN, 0.0)
        } else {
            if !observed.is_finite() {
                return Err(FilterFailure::Observation(index));
            }
            let (filtered_mean, filtered_variance, innovation) =
                assimilate(mean, variance, observed, r, innovation_variance);
            let standardized = innovation / innovation_variance.sqrt();
            let log_likelihood = -0.5 * (log_two_pi + innovation_variance.ln())
                - (0.5 * standardized) * standardized;
            total += log_likelihood;
            if !innovation.is_finite() || !filtered_mean.is_finite() || !total.is_finite() {
                return Err(FilterFailure::Numeric(index));
            }
            (filtered_mean, filtered_variance, innovation, log_likelihood)
        };

        for (slot, value) in row.iter_mut().zip([
            mean,
            variance,
            filtered_mean,
            filtered_variance,
            innovation,
            innovation_variance,
            log_likelihood,
        ]) {
            slot.write(value);
        }
        mean = filtered_mean;
        variance = filtered_variance;
    }
    Ok(total)
}

#[no_mangle]
pub extern "C" fn arboris_time_series_abi() -> i32 {
    1
}

/// Outputs seven row-major f64 values per time step. See the order in `filter`.
/// NaN denotes a missing observation and a missing innovation.
/// A nonzero status invalidates the entire result. `error_index` identifies a row
/// for observation or numeric errors, and is `usize::MAX` for parameter errors.
///
/// # Safety
/// All nonnull pointers must be aligned and refer to the stated number of
/// elements. The input values must be initialized. The output, scalar output
/// pointers and input must occupy separate, valid memory for the whole call.
#[no_mangle]
pub unsafe extern "C" fn arboris_local_level(
    values: *const f64,
    count: usize,
    q: f64,
    r: f64,
    initial_mean: f64,
    initial_variance: f64,
    output: *mut f64,
    output_len: usize,
    total: *mut f64,
    error_index: *mut usize,
) -> i32 {
    if error_index.is_null() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    if count == 0
        || count > MAX_OBSERVATIONS
        || output_len != count * ROW_WIDTH
        || values.is_null()
        || output.is_null()
        || total.is_null()
        || ![q, r, initial_mean, initial_variance]
            .iter()
            .all(|value| value.is_finite())
        || q < 0.0
        || r <= 0.0
        || initial_variance < 0.0
    {
        return INVALID_INPUT;
    }
    let values = unsafe { slice::from_raw_parts(values, count) };
    let output =
        unsafe { slice::from_raw_parts_mut(output.cast::<MaybeUninit<f64>>(), output_len) };
    let parameters = Parameters {
        process_variance: q,
        observation_variance: r,
        initial_mean,
        initial_variance,
    };
    match filter(values, parameters, output) {
        Ok(log_likelihood) => {
            unsafe { total.write(log_likelihood) };
            0
        }
        Err(FilterFailure::Observation(index)) => {
            unsafe { error_index.write(index) };
            INVALID_INPUT
        }
        Err(FilterFailure::Numeric(index)) => {
            unsafe { error_index.write(index) };
            NUMERIC_FAILURE
        }
    }
}
