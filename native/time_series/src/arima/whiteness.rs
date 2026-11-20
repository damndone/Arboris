use std::{ptr, slice};

use super::{
    disjoint_regions, fit_arima_with_whiteness, region, supported, CancellationCheck, FitBuffers,
    LagCorrelation, Trend, MAX_OBSERVATIONS, RESIDUAL_LAGS,
};

const OUTPUT_LENGTH: usize = 6;
const MIN_INNOVATIONS: usize = 20;

pub(super) struct Summary {
    lag: usize,
    fit_df: usize,
    count: usize,
    mean: f64,
    energy: f64,
    output: [f64; OUTPUT_LENGTH],
}

impl Summary {
    fn new(lag: usize, fit_df: usize) -> Self {
        Self {
            lag,
            fit_df,
            count: 0,
            mean: 0.0,
            energy: 0.0,
            output: [f64::NAN; OUTPUT_LENGTH],
        }
    }

    pub(super) fn add(&mut self, value: f64) {
        self.count += 1;
        let deviation = value - self.mean;
        self.mean += deviation / self.count as f64;
        self.energy = deviation.mul_add(value - self.mean, self.energy);
    }

    pub(super) fn finish(
        &mut self,
        pairs: &[LagCorrelation; RESIDUAL_LAGS],
        n: usize,
        has_gap: bool,
    ) {
        let degrees = self.lag as i32 - self.fit_df as i32;
        let statistic = if has_gap {
            Err(1)
        } else if degrees <= 0 {
            Err(2)
        } else if n < MIN_INNOVATIONS || self.lag >= n {
            Err(3)
        } else if self.count != n || !self.energy.is_finite() {
            Err(5)
        } else if self.energy <= n as f64 * (32.0 * f64::EPSILON * self.mean.abs()).powi(2) {
            Err(4)
        } else {
            self.statistic(&pairs[..self.lag], n)
        };
        let (status, q) = match statistic {
            Ok(q) => (0, q),
            Err(status) => (status, f64::NAN),
        };
        self.output = [
            status as f64,
            n as f64,
            self.lag as f64,
            self.fit_df as f64,
            degrees as f64,
            q,
        ];
    }

    fn statistic(&self, pairs: &[LagCorrelation], n: usize) -> Result<f64, i32> {
        let mut terms = 0.0;
        for (index, pair) in pairs.iter().enumerate() {
            let expected = n - index - 1;
            if pair.count != expected {
                return Err(5);
            }
            let offset = (pair.previous_mean - self.mean) * (pair.current_mean - self.mean);
            let correlation = (pair.count as f64).mul_add(offset, pair.cross) / self.energy;
            if !correlation.is_finite() || correlation.abs() > 1.0 + 1e-12 {
                return Err(5);
            }
            terms += correlation.powi(2) / expected as f64;
        }
        let q = (n as f64) * (n as f64 + 2.0) * terms;
        if !q.is_finite() {
            return Err(5);
        }
        Ok(q)
    }
}

/// # Safety
/// The initialized input and separate output buffers must be valid for their stated lengths.
/// The optional callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_arima_fit_with_whiteness(
    values: *const f64,
    count: usize,
    p: usize,
    d: usize,
    q: usize,
    trend: i32,
    horizon: usize,
    lag: usize,
    fit: *mut f64,
    fit_len: usize,
    forecasts: *mut f64,
    forecasts_len: usize,
    residuals: *mut f64,
    residuals_len: usize,
    whiteness: *mut f64,
    whiteness_len: usize,
    error_index: *mut usize,
    check: CancellationCheck,
) -> i32 {
    let Some(trend) = Trend::from_code(trend) else {
        return 6;
    };
    if !supported(p, d, q, trend) || count > MAX_OBSERVATIONS {
        return 6;
    }
    if !(1..=RESIDUAL_LAGS).contains(&lag) || whiteness_len != OUTPUT_LENGTH {
        return 1;
    }
    let outputs = FitBuffers {
        fit: (fit, fit_len),
        forecast: (forecasts, forecasts_len),
        residuals: (residuals, residuals_len),
        error_index,
    };
    let Some([input, fit, forecast, residual, error]) =
        outputs.regions(values, count, p + q, horizon)
    else {
        return 1;
    };
    let Some(diagnostic) = region(whiteness, whiteness_len) else {
        return 1;
    };
    if !disjoint_regions([input, fit, forecast, residual, error, diagnostic]) {
        return 1;
    }

    unsafe { error_index.write(usize::MAX) };
    let values = unsafe { slice::from_raw_parts(values, count) };
    let mut diagnostic = Summary::new(lag, p + q);
    match fit_arima_with_whiteness(
        values,
        [p, d, q],
        trend,
        horizon,
        check,
        Some(&mut diagnostic),
    ) {
        Ok(estimate) => unsafe {
            ptr::copy_nonoverlapping(diagnostic.output.as_ptr(), whiteness, whiteness_len);
            outputs.write(&estimate, p, q, &[])
        },
        Err(failure) => unsafe { outputs.failure(failure) },
    }
}

#[cfg(test)]
#[path = "whiteness_tests.rs"]
mod tests;
