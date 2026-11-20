use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

use super::{
    sum, INVALID_ARGUMENT, MAX_ASSETS, MAX_PERIODS, MAX_RISK_WINDOW, NUMERICAL, PANIC, RETURN,
    TIME_ORDER,
};

#[derive(Clone, Copy, Default)]
struct Moment {
    anchor: f64,
    mean_shift: f64,
    centered_square: f64,
}

impl Moment {
    fn one(anchor: f64) -> Self {
        Self {
            anchor,
            mean_shift: 0.0,
            centered_square: 0.0,
        }
    }

    fn merge(self, left_count: usize, later: Self, right_count: usize) -> Option<Self> {
        // Pébay's pairwise centered-moment merge. Carrying each mean
        // relative to an observed anchor preserves small variation at offsets.
        let right_fraction = right_count as f64 / (left_count + right_count) as f64;
        let delta = sum([
            later.anchor,
            -self.anchor,
            later.mean_shift,
            -self.mean_shift,
        ]);
        let mean_shift = self.mean_shift + delta * right_fraction;
        let square = sum([
            self.centered_square,
            later.centered_square,
            delta * delta * (left_count as f64 * right_fraction),
        ]);
        if !mean_shift.is_finite() || !square.is_finite() || (square == 0.0 && delta != 0.0) {
            return None;
        }
        Some(Self {
            anchor: self.anchor,
            mean_shift,
            centered_square: square,
        })
    }
}

fn rolling_volatility(
    panel: &[f64],
    width: usize,
    window: usize,
    output: &mut [f64],
) -> Result<(), usize> {
    let periods = panel.len() / width;
    let mut suffixes = vec![Moment::default(); (window - 1) * width];
    let divisor = (window - 1) as f64;
    for block in (0..periods).step_by(window) {
        // The full window at each row consists of a suffix of the preceding
        // block and a prefix of the current block. Neither requires downdates.
        if block > 0 {
            for length in 1..window {
                let begin = (block - length) * width;
                let offset = (length - 1) * width;
                for column in 0..width {
                    let one = Moment::one(panel[begin + column]);
                    suffixes[offset + column] = if length == 1 {
                        one
                    } else {
                        one.merge(1, suffixes[offset - width + column], length - 1)
                            .ok_or(block)?
                    };
                }
            }
        }
        let mut prefix = [Moment::default(); MAX_ASSETS];
        for row in block..periods.min(block + window) {
            let right_count = row - block + 1;
            let left_count = window - right_count;
            for column in 0..width {
                let one = Moment::one(panel[row * width + column]);
                prefix[column] = if right_count == 1 {
                    one
                } else {
                    prefix[column].merge(right_count - 1, one, 1).ok_or(row)?
                };
                if row + 1 >= window {
                    let moment = if left_count == 0 {
                        prefix[column]
                    } else {
                        suffixes[(left_count - 1) * width + column]
                            .merge(left_count, prefix[column], right_count)
                            .ok_or(row)?
                    };
                    let variance = moment.centered_square / divisor;
                    if variance == 0.0 && moment.centered_square > 0.0 {
                        return Err(row);
                    }
                    output[(row + 1 - window) * width + column] = variance.sqrt();
                }
            }
        }
    }
    Ok(())
}

pub(super) fn latest_covariance(
    tail: &[f64],
    width: usize,
    window: usize,
    output: &mut [f64],
) -> Option<()> {
    // One full latest-window matrix. Center on offsets in a separate pass
    // and reflect the triangle so paired elements have identical bits.
    let anchor = &tail[..width];
    let mut mean_shift = [0.0; MAX_ASSETS];
    for (column, mean) in mean_shift.iter_mut().take(width).enumerate() {
        *mean = sum(tail
            .chunks_exact(width)
            .map(|row| row[column] - anchor[column]))
            / window as f64;
    }
    for i in 0..width {
        for j in i..width {
            let products = tail.chunks_exact(width).map(|row| {
                let x = (row[i] - anchor[i]) - mean_shift[i];
                let y = (row[j] - anchor[j]) - mean_shift[j];
                x * y
            });
            let covariance = sum(products) / (window - 1) as f64;
            if !covariance.is_finite() {
                return None;
            }
            output[i * width + j] = covariance;
            output[j * width + i] = covariance;
        }
    }
    Some(())
}

fn risk(
    times: &[i64],
    panel: &[f64],
    width: usize,
    window: usize,
    output: &mut [f64],
) -> Result<(), (i32, usize)> {
    for (row, pair) in times.windows(2).enumerate() {
        if pair[0] >= pair[1] {
            return Err((TIME_ORDER, row + 1));
        }
    }
    for (row, values) in panel.chunks_exact(width).enumerate() {
        if !values.iter().all(|value| value.is_finite()) {
            return Err((RETURN, row));
        }
    }
    let (volatility, covariance) = output.split_at_mut((times.len() - window + 1) * width);
    rolling_volatility(panel, width, window, volatility).map_err(|row| (NUMERICAL, row))?;
    let tail = &panel[(times.len() - window) * width..];
    latest_covariance(tail, width, window, covariance).ok_or((NUMERICAL, times.len() - 1))
}

#[no_mangle]
pub extern "C" fn arboris_quant_risk_output_len(
    periods: usize,
    width: usize,
    window: usize,
) -> usize {
    if (2..=MAX_PERIODS).contains(&periods)
        && (1..=MAX_ASSETS).contains(&width)
        && (2..=periods.min(MAX_RISK_WINDOW)).contains(&window)
    {
        (periods - window + 1) * width + width * width
    } else {
        0
    }
}

/// ABI 1 risk output consists of complete-window volatilities followed by
/// the latest full covariance, both in row-major order.
///
/// # Safety
/// Input pointers must be valid, readable, and unchanged for the given lengths.
/// Output and error pointers must be valid, writable, and alias no other buffer.
/// Output is valid on status 0.
#[no_mangle]
pub unsafe extern "C" fn arboris_quant_risk(
    periods: usize,
    width: usize,
    window: usize,
    times: *const i64,
    times_len: usize,
    returns: *const f64,
    returns_len: usize,
    output: *mut f64,
    output_len: usize,
    error_row: *mut usize,
) -> i32 {
    if error_row.is_null() || !error_row.is_aligned() {
        return INVALID_ARGUMENT;
    }
    unsafe { error_row.write(usize::MAX) };
    let expected = arboris_quant_risk_output_len(periods, width, window);
    if expected == 0
        || output_len != expected
        || times_len != periods
        || returns_len != periods * width
        || times.is_null()
        || !times.is_aligned()
        || returns.is_null()
        || !returns.is_aligned()
        || output.is_null()
        || !output.is_aligned()
    {
        return INVALID_ARGUMENT;
    }
    // Bounded shape and nonnull aligned pointers were checked above.
    let result = catch_unwind(AssertUnwindSafe(|| unsafe {
        risk(
            slice::from_raw_parts(times, times_len),
            slice::from_raw_parts(returns, returns_len),
            width,
            window,
            slice::from_raw_parts_mut(output, output_len),
        )
    }));
    match result {
        Ok(Ok(())) => 0,
        Ok(Err((status, row))) => {
            unsafe { error_row.write(row) };
            status
        }
        Err(_) => PANIC,
    }
}
