#![deny(unsafe_op_in_unsafe_fn)]

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

mod fee_comparison;
mod min_variance;
mod risk;
mod tail;
mod walk_forward;

const MAX_PERIODS: usize = 10_000;
const MAX_ASSETS: usize = 32;
const MAX_RISK_WINDOW: usize = 2048;
const TIME_COLUMNS: usize = 3;
const OUTPUT_COLUMNS: usize = 9;

const INVALID_ARGUMENT: i32 = 1;
const TIME_ORDER: i32 = 2;
const LOOKAHEAD: i32 = 3;
const RETURN: i32 = 4;
const WEIGHT: i32 = 5;
const NONPOSITIVE_EQUITY: i32 = 6;
const NUMERICAL: i32 = 7;
const PANIC: i32 = 8;

fn sum(values: impl IntoIterator<Item = f64>) -> f64 {
    let mut total: f64 = 0.0;
    let mut correction = 0.0;
    for value in values {
        let next = total + value;
        correction += if total.abs() >= value.abs() {
            (total - next) + value
        } else {
            (value - next) + total
        };
        total = next;
    }
    total + correction
}

fn reconciles(left: f64, right: f64, scale: f64) -> bool {
    left.is_finite() && right.is_finite() && (left - right).abs() / scale <= 64.0 * f64::EPSILON
}

fn funded_fraction(
    prior_weights: &[f64],
    weights: &[f64],
    prior_cash_weight: f64,
    cash_weight: f64,
    fee_rate: f64,
) -> f64 {
    if fee_rate == 0.0 || prior_weights == weights {
        return 1.0;
    }
    // Rewrite absolute turnover as prior risky weight minus target risky
    // weight, plus twice the buys. This keeps a small retained value when
    // the fee approaches one without subtracting two values near one.
    let retained = (1.0 - fee_rate) + fee_rate * prior_cash_weight;
    let slope = (1.0 - fee_rate) + fee_rate * cash_weight;
    let mut low = 0.0;
    let mut high = 1.0;
    for _ in 0..128 {
        let mid = low + (high - low) * 0.5;
        if mid == low || mid == high {
            break;
        }
        let buys = sum(prior_weights
            .iter()
            .zip(weights)
            .map(|(prior, target)| (mid * target - prior).max(0.0)));
        if slope * mid + 2.0 * fee_rate * buys > retained {
            high = mid;
        } else {
            low = mid;
        }
    }
    low + (high - low) * 0.5
}

fn residual_cash_weight(weights: &[f64]) -> f64 {
    sum([1.0]
        .into_iter()
        .chain(weights.iter().map(|weight| -weight)))
}

struct ReplayState {
    starting: f64,
    holdings: Vec<f64>,
    prior_weights: Vec<f64>,
    cash: f64,
    previous_end: Option<i64>,
}

impl ReplayState {
    fn new(width: usize, initial_equity: f64) -> Self {
        Self {
            starting: initial_equity,
            holdings: vec![0.0; width],
            prior_weights: vec![0.0; width],
            cash: initial_equity,
            previous_end: None,
        }
    }

    fn step(
        &mut self,
        time: &[i64],
        r: &[f64],
        weights: &[f64],
        fee_rate: f64,
        values: &mut [f64],
    ) -> Result<(), i32> {
        let starting = self.starting;
        let holdings = &mut self.holdings;
        let prior_weights = &mut self.prior_weights;
        let (signal, start, end) = (time[0], time[1], time[2]);
        if start >= end || self.previous_end.is_some_and(|previous| start != previous) {
            return Err(TIME_ORDER);
        }
        if signal >= start {
            return Err(LOOKAHEAD);
        }
        if starting <= 0.0 {
            return Err(NONPOSITIVE_EQUITY);
        }
        if !r.iter().all(|value| value.is_finite() && *value >= -1.0) {
            return Err(RETURN);
        }
        if !weights.iter().all(|weight| (0.0..=1.0).contains(weight)) {
            return Err(WEIGHT);
        }
        // Sum the residual directly, so an overweight portfolio is visible
        // even if the risky weights would round to a total of one.
        let cash_weight = residual_cash_weight(weights);
        if cash_weight < 0.0 {
            return Err(WEIGHT);
        }

        for (prior, holding) in prior_weights.iter_mut().zip(holdings.iter()) {
            *prior = holding / starting;
        }
        let post = funded_fraction(
            prior_weights,
            weights,
            self.cash / starting,
            cash_weight,
            fee_rate,
        ) * starting;
        let notional = sum(holdings
            .iter()
            .zip(weights)
            .map(|(prior, target)| (post * target - prior).abs()));
        let fees = fee_rate * notional;
        if post <= 0.0 || !notional.is_finite() || !reconciles(starting - fees, post, starting) {
            return Err(NUMERICAL);
        }
        let holding_pnl = sum(weights
            .iter()
            .zip(r)
            .map(|(weight, ret)| (post * weight) * ret));
        for ((holding, weight), ret) in holdings.iter_mut().zip(weights).zip(r) {
            *holding = (post * weight) * (1.0 + ret);
        }
        self.cash = post * cash_weight;
        let ending = sum(holdings.iter().copied().chain([self.cash]));
        let net_pnl = holding_pnl - fees;
        let net_return = if ending == 0.0 {
            -1.0
        } else {
            net_pnl / starting
        };
        if !net_return.is_finite()
            || net_return < -1.0
            || !reconciles(ending - starting, net_pnl, ending.max(starting))
        {
            return Err(NUMERICAL);
        }
        // ABI 1: starting, post-trade, ending, gross exposure, fees, notional,
        // holding P&L, net P&L, net return. Net exposure equals gross for long-only.
        values.copy_from_slice(&[
            starting,
            post,
            ending,
            1.0 - cash_weight,
            fees,
            notional,
            holding_pnl,
            net_pnl,
            net_return,
        ]);
        self.starting = ending;
        self.previous_end = Some(end);
        Ok(())
    }
}

fn replay(
    times: &[i64],
    returns: &[f64],
    targets: &[f64],
    width: usize,
    fee_rate: f64,
    initial_equity: f64,
    output: &mut [f64],
) -> Result<(), (i32, usize)> {
    let mut state = ReplayState::new(width, initial_equity);
    for (row, (((time, r), weights), values)) in times
        .chunks_exact(TIME_COLUMNS)
        .zip(returns.chunks_exact(width))
        .zip(targets.chunks_exact(width))
        .zip(output.chunks_exact_mut(OUTPUT_COLUMNS))
        .enumerate()
    {
        state
            .step(time, r, weights, fee_rate, values)
            .map_err(|status| (status, row))?;
    }
    Ok(())
}

#[no_mangle]
pub extern "C" fn arboris_quant_replay_abi() -> i32 {
    1
}

#[no_mangle]
pub extern "C" fn arboris_quant_replay_output_len(periods: usize) -> usize {
    if (1..=MAX_PERIODS).contains(&periods) {
        periods * OUTPUT_COLUMNS
    } else {
        0
    }
}

/// Replays aligned flat buffers with the ABI 1 layout.
///
/// # Safety
/// Each input pointer must be valid and readable for its stated length and
/// unchanged for the call. Output and error pointers must refer to separate
/// writable storage that does not alias any input. Output is valid on status 0.
#[no_mangle]
pub unsafe extern "C" fn arboris_quant_replay(
    periods: usize,
    width: usize,
    times: *const i64,
    times_len: usize,
    returns: *const f64,
    returns_len: usize,
    weights: *const f64,
    weights_len: usize,
    fee_rate: f64,
    initial_equity: f64,
    output: *mut f64,
    output_len: usize,
    error_row: *mut usize,
) -> i32 {
    if error_row.is_null() || !error_row.is_aligned() {
        return INVALID_ARGUMENT;
    }
    unsafe { error_row.write(usize::MAX) };
    let expected = arboris_quant_replay_output_len(periods);
    if expected == 0
        || !(1..=MAX_ASSETS).contains(&width)
        || output_len != expected
        || times_len != periods * TIME_COLUMNS
        || returns_len != periods * width
        || weights_len != returns_len
        || !initial_equity.is_finite()
        || initial_equity <= 0.0
        || !(0.0..1.0).contains(&fee_rate)
        || times.is_null()
        || !times.is_aligned()
        || returns.is_null()
        || !returns.is_aligned()
        || weights.is_null()
        || !weights.is_aligned()
        || output.is_null()
        || !output.is_aligned()
    {
        return INVALID_ARGUMENT;
    }
    // The ABI lengths are bounded above; validity and non-aliasing of their
    // backing allocations are the caller's responsibility.
    let result = catch_unwind(AssertUnwindSafe(|| unsafe {
        replay(
            slice::from_raw_parts(times, times_len),
            slice::from_raw_parts(returns, returns_len),
            slice::from_raw_parts(weights, weights_len),
            width,
            fee_rate,
            initial_equity,
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
