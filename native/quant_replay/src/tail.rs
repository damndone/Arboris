use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

use super::{
    sum, INVALID_ARGUMENT, MAX_PERIODS, MAX_RISK_WINDOW, NUMERICAL, OUTPUT_COLUMNS, PANIC, RETURN,
};

const BASIS_POINTS: usize = 10_000;
const NET_RETURN_COLUMN: usize = OUTPUT_COLUMNS - 1;

fn historical_tail(
    ledger: &[f64],
    window: usize,
    confidence_bps: usize,
) -> Result<[f64; 2], (i32, usize)> {
    let first = ledger.len() / OUTPUT_COLUMNS - window;
    let mut losses = Vec::with_capacity(window);
    for (i, row) in ledger[first * OUTPUT_COLUMNS..]
        .chunks_exact(OUTPUT_COLUMNS)
        .enumerate()
    {
        let net_return = row[NET_RETURN_COLUMN];
        if !net_return.is_finite() || net_return < -1.0 {
            return Err((RETURN, first + i));
        }
        losses.push(0.0 - net_return);
    }
    losses.sort_unstable_by(|a, b| b.total_cmp(a));

    let units = window * (BASIS_POINTS - confidence_bps);
    let full = units / BASIS_POINTS;
    let fraction = units % BASIS_POINTS;
    let value_at_risk = losses[full];
    let highest = losses[0];
    let lowest_included = if fraction == 0 {
        losses[full - 1]
    } else {
        value_at_risk
    };
    if lowest_included == highest {
        return Ok([value_at_risk, highest]);
    }
    let scale = highest.abs().max(lowest_included.abs());
    let full_weight = BASIS_POINTS as f64 / units as f64;
    let boundary =
        (fraction > 0).then(|| (value_at_risk / scale) * (fraction as f64 / units as f64));
    let mean = sum(losses[..full]
        .iter()
        .map(|value| (value / scale) * full_weight)
        .chain(boundary));
    let lower = lowest_included / scale;
    let upper = highest / scale;
    let roundoff = 32.0 * f64::EPSILON;
    if !mean.is_finite() || mean < lower - roundoff || mean > upper + roundoff {
        return Err((NUMERICAL, ledger.len() / OUTPUT_COLUMNS - 1));
    }
    let expected_shortfall = (mean.clamp(lower, upper) * scale).clamp(lowest_included, highest);
    Ok([value_at_risk, expected_shortfall])
}

/// Returns historical VaR and fractional-tail ES from a completed replay ledger.
///
/// # Safety
/// The ledger must be readable and unchanged for its declared length. Output
/// and error pointers must be writable, valid, and alias no other buffer.
#[no_mangle]
pub unsafe extern "C" fn arboris_quant_tail_risk(
    periods: usize,
    window: usize,
    confidence_bps: usize,
    ledger: *const f64,
    ledger_len: usize,
    output: *mut f64,
    output_len: usize,
    error_row: *mut usize,
) -> i32 {
    if error_row.is_null() || !error_row.is_aligned() {
        return INVALID_ARGUMENT;
    }
    unsafe { error_row.write(usize::MAX) };
    if !(2..=MAX_PERIODS).contains(&periods)
        || !(2..=periods.min(MAX_RISK_WINDOW)).contains(&window)
        || !(1..BASIS_POINTS).contains(&confidence_bps)
        || ledger_len != periods * OUTPUT_COLUMNS
        || output_len != 2
        || ledger.is_null()
        || !ledger.is_aligned()
        || output.is_null()
        || !output.is_aligned()
    {
        return INVALID_ARGUMENT;
    }
    let result = catch_unwind(AssertUnwindSafe(|| unsafe {
        historical_tail(
            slice::from_raw_parts(ledger, ledger_len),
            window,
            confidence_bps,
        )
    }));
    match result {
        Ok(Ok(values)) => {
            unsafe { slice::from_raw_parts_mut(output, output_len) }.copy_from_slice(&values);
            0
        }
        Ok(Err((status, row))) => {
            unsafe { error_row.write(row) };
            status
        }
        Err(_) => PANIC,
    }
}
