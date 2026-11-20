use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

use super::min_variance::{
    checkpoint, fund_weights, region, solve_window, Check, BPS, CANCELLED, NO_ROW, SUMMARY,
};
use super::{
    ReplayState, INVALID_ARGUMENT, MAX_PERIODS, OUTPUT_COLUMNS, PANIC, RETURN, TIME_ORDER,
};

const MAX_ASSETS: usize = 16;
const MAX_WINDOW: usize = 512;
const MAX_EVALUATIONS: usize = 256;
const EVIDENCE: usize = 5;

fn result_size(periods: usize, width: usize, window: usize, first: usize) -> Option<usize> {
    if !(2..=MAX_ASSETS).contains(&width)
        || !(2..=MAX_WINDOW).contains(&window)
        || periods > MAX_PERIODS
        || !(window + 2..=periods).contains(&first)
    {
        return None;
    }
    let evaluations = periods - first + 1;
    (2..=MAX_EVALUATIONS)
        .contains(&evaluations)
        .then_some(width + 2 + evaluations * (2 * OUTPUT_COLUMNS + width + EVIDENCE))
}

struct Specification {
    width: usize,
    window: usize,
    first: usize,
    shrinkage: usize,
    fee: f64,
    equity: f64,
}

fn walk_forward(
    times: &[i64],
    returns: &[f64],
    spec: Specification,
    output: &mut [f64],
    check: Check,
) -> Result<(), (i32, usize)> {
    let Specification {
        width,
        window,
        first,
        shrinkage,
        fee,
        equity,
    } = spec;
    let global = |code| (code, NO_ROW);
    for (row, values) in returns.chunks_exact(width).enumerate() {
        if row % 256 == 0 {
            checkpoint(check).map_err(global)?;
        }
        if row > 0 && times[row - 1] >= times[row] {
            return Err((TIME_ORDER, row));
        }
        if !values
            .iter()
            .all(|value| value.is_finite() && *value >= -1.0)
        {
            return Err((RETURN, row));
        }
    }

    let (header, rows) = output.split_at_mut(width + 2);
    let (equal, equal_evidence) = header.split_at_mut(width);
    equal.fill(1.0 / width as f64);
    let equal_funding = fund_weights(equal).map_err(global)?;
    equal_evidence.copy_from_slice(&[equal_funding.cash, equal_funding.adjustment]);
    let mut strategy = ReplayState::new(width, equity);
    let mut benchmark = ReplayState::new(width, equity);
    let mut workspace = vec![0.0; width + 2 * width * width + SUMMARY];
    for (offset, result) in rows
        .chunks_exact_mut(2 * OUTPUT_COLUMNS + width + EVIDENCE)
        .enumerate()
    {
        checkpoint(check).map_err(global)?;
        let row = first - 1 + offset;
        let observed = row - 1;
        let history = &returns[(observed - window) * width..observed * width];
        let fit = solve_window(history, width, shrinkage, &mut workspace, true, check)
            .map_err(|(code, _)| (code, if code == CANCELLED { NO_ROW } else { row }))?;
        let weights = &workspace[..width];
        let time = [times[observed - 1], times[row - 1], times[row]];
        let realized = &returns[row * width..(row + 1) * width];
        let (selected, rest) = result.split_at_mut(OUTPUT_COLUMNS);
        let (reference, rest) = rest.split_at_mut(OUTPUT_COLUMNS);
        let (target, evidence) = rest.split_at_mut(width);
        strategy
            .step(&time, realized, weights, fee, selected)
            .map_err(|code| (code, row))?;
        benchmark
            .step(&time, realized, equal, fee, reference)
            .map_err(|code| (code, row))?;
        target.copy_from_slice(weights);
        evidence.copy_from_slice(&[
            fit.sample_rank as f64,
            fit.objective_variance,
            fit.kkt,
            fit.funding.cash,
            fit.funding.adjustment,
        ]);
    }
    checkpoint(check).map_err(global)
}

/// Rebalances two offline paths from strictly earlier completed returns.
///
/// # Safety
/// All pointers must be valid for the declared lengths. Buffers must remain
/// disjoint and inputs unchanged during the call. The callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_quant_walk_forward(
    periods: usize,
    width: usize,
    window: usize,
    first_period: usize,
    shrinkage_bps: usize,
    times: *const i64,
    times_len: usize,
    returns: *const f64,
    returns_len: usize,
    fee_rate: f64,
    initial_equity: f64,
    output: *mut f64,
    output_len: usize,
    error_row: *mut usize,
    check: Check,
) -> i32 {
    let Some(expected) = result_size(periods, width, window, first_period) else {
        return INVALID_ARGUMENT;
    };
    if output_len != expected
        || times_len != periods
        || returns_len != periods * width
        || shrinkage_bps > BPS
        || !(0.0..1.0).contains(&fee_rate)
        || !initial_equity.is_finite()
        || initial_equity <= 0.0
    {
        return INVALID_ARGUMENT;
    }
    let [Some(clock), Some(panel), Some(result), Some(error)] = [
        region(times, times_len),
        region(returns, returns_len),
        region(output, output_len),
        region(error_row, 1),
    ] else {
        return INVALID_ARGUMENT;
    };
    let mut regions = [clock, panel, result, error];
    regions.sort_unstable();
    if regions.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return INVALID_ARGUMENT;
    }
    unsafe { error_row.write(NO_ROW) };
    let spec = Specification {
        width,
        window,
        first: first_period,
        shrinkage: shrinkage_bps,
        fee: fee_rate,
        equity: initial_equity,
    };
    let result = catch_unwind(AssertUnwindSafe(|| {
        let times = unsafe { slice::from_raw_parts(times, times_len) };
        let returns = unsafe { slice::from_raw_parts(returns, returns_len) };
        let mut candidate = vec![0.0; output_len];
        walk_forward(times, returns, spec, &mut candidate, check)?;
        Ok::<_, (i32, usize)>(candidate)
    }));
    match result {
        Ok(Ok(candidate)) => {
            unsafe { slice::from_raw_parts_mut(output, output_len) }.copy_from_slice(&candidate);
            0
        }
        Ok(Err((status, row))) => {
            unsafe { error_row.write(row) };
            status
        }
        Err(_) => PANIC,
    }
}
