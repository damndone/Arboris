//! Concentrated Gaussian likelihood with fixed Q/R and P0/R ratios.

use std::ptr;
use std::slice;

use super::{assimilate, INVALID_INPUT, MAX_OBSERVATIONS, NUMERIC_FAILURE};

const OUTPUT_LENGTH: usize = 4;
const INSUFFICIENT: i32 = 3;
const ZERO_ENERGY: i32 = 4;
const SCALE_RANGE: i32 = 5;
const VARIANCE_RANGE: i32 = 6;

enum Failure {
    Observation(usize),
    Numeric(usize),
    Insufficient,
    ZeroEnergy,
    ScaleRange,
    VarianceRange,
}

fn fit_scale(
    values: &[f64],
    ratio: f64,
    initial_mean: f64,
    prior_ratio: f64,
) -> Result<[f64; OUTPUT_LENGTH], Failure> {
    let mut count = 0;
    let mut mean = initial_mean;
    let mut variance = prior_ratio;
    let mut log_determinant = 0.0;
    let mut nonzero_innovation = false;
    let mut largest_error = 0.0_f64;
    let mut scaled_energy = 0.0;
    for (index, &value) in values.iter().enumerate() {
        if index > 0 {
            variance += ratio;
        }
        let innovation_variance = variance + 1.0;
        if !innovation_variance.is_finite() {
            return Err(Failure::Numeric(index));
        }
        if value.is_nan() {
            continue;
        }
        if !value.is_finite() {
            return Err(Failure::Observation(index));
        }
        count += 1;
        let innovation;
        (mean, variance, innovation) = assimilate(mean, variance, value, 1.0, innovation_variance);
        nonzero_innovation |= innovation != 0.0;
        let absolute_error = (innovation / innovation_variance.sqrt()).abs();
        if !absolute_error.is_finite() || !mean.is_finite() {
            return Err(Failure::Numeric(index));
        }
        // Keep the energy in scaled form so an individual square may exceed
        // float64 even when the mean square is representable.
        if absolute_error > largest_error {
            let previous_ratio = largest_error / absolute_error;
            scaled_energy = 1.0 + scaled_energy * previous_ratio * previous_ratio;
            largest_error = absolute_error;
        } else if absolute_error != 0.0 {
            let relative_error = absolute_error / largest_error;
            scaled_energy += relative_error * relative_error;
        }
        log_determinant += innovation_variance.ln();
    }
    if count < 2 {
        return Err(Failure::Insufficient);
    }
    if !nonzero_innovation {
        return Err(Failure::ZeroEnergy);
    }
    let n = count as f64;
    let rms = largest_error * (scaled_energy / n).sqrt();
    let r = rms * rms;
    if !r.is_normal() {
        return Err(Failure::ScaleRange);
    }
    let q = ratio * r;
    let prior_variance = prior_ratio * r;
    if !q.is_finite()
        || !prior_variance.is_finite()
        || (ratio > 0.0 && q == 0.0)
        || (prior_ratio > 0.0 && prior_variance == 0.0)
    {
        return Err(Failure::VarianceRange);
    }
    let relative_error = largest_error / r.sqrt();
    let quadratic = relative_error * relative_error * scaled_energy;
    let log_likelihood =
        -0.5 * (n * (std::f64::consts::TAU.ln() + r.ln()) + log_determinant + quadratic);
    Ok([q, r, prior_variance, log_likelihood])
}

/// Fit a common scale to the caller-provided training prefix. A successful
/// output is Q, R, P0, and the training log likelihood, in that order. A
/// nonzero status leaves the output untouched. `error_index` is `usize::MAX`
/// unless the error occurred at a particular time step.
///
/// # Safety
/// All nonnull pointers must be aligned and refer to the stated number of
/// elements for the whole call. The input values must be initialized. The
/// input, output and error pointer must occupy separate memory.
#[no_mangle]
pub unsafe extern "C" fn arboris_local_level_fit_scale(
    values: *const f64,
    count: usize,
    ratio: f64,
    initial_mean: f64,
    prior_ratio: f64,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
) -> i32 {
    if error_index.is_null() {
        return INVALID_INPUT;
    }
    unsafe { error_index.write(usize::MAX) };
    if count == 0
        || count > MAX_OBSERVATIONS
        || output_len != OUTPUT_LENGTH
        || values.is_null()
        || output.is_null()
        || ![ratio, initial_mean, prior_ratio]
            .iter()
            .all(|value| value.is_finite())
        || ratio < 0.0
        || prior_ratio < 0.0
    {
        return INVALID_INPUT;
    }
    let values = unsafe { slice::from_raw_parts(values, count) };
    match fit_scale(values, ratio, initial_mean, prior_ratio) {
        Ok(estimate) => {
            unsafe { ptr::copy_nonoverlapping(estimate.as_ptr(), output, OUTPUT_LENGTH) };
            0
        }
        Err(Failure::Observation(index)) => {
            unsafe { error_index.write(index) };
            INVALID_INPUT
        }
        Err(Failure::Numeric(index)) => {
            unsafe { error_index.write(index) };
            NUMERIC_FAILURE
        }
        Err(Failure::Insufficient) => INSUFFICIENT,
        Err(Failure::ZeroEnergy) => ZERO_ENERGY,
        Err(Failure::ScaleRange) => SCALE_RANGE,
        Err(Failure::VarianceRange) => VARIANCE_RANGE,
    }
}
