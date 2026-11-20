use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

use super::min_variance::{checkpoint, region, Check, NO_ROW};
use super::{
    arboris_quant_replay_output_len, ReplayState, INVALID_ARGUMENT, MAX_ASSETS, OUTPUT_COLUMNS,
    PANIC, TIME_COLUMNS,
};

const SCENARIOS: usize = 2;
const CHECK_EVERY: usize = 64;

struct Specification {
    width: usize,
    rates: [f64; SCENARIOS],
    initial_equity: f64,
}

fn compare(
    times: &[i64],
    returns: &[f64],
    targets: &[f64],
    spec: Specification,
    output: &mut [f64],
    check: Check,
) -> Result<(), (i32, usize)> {
    let periods = times.len() / TIME_COLUMNS;
    let mut states = spec
        .rates
        .map(|_| ReplayState::new(spec.width, spec.initial_equity));
    let (base, higher) = output.split_at_mut(periods * OUTPUT_COLUMNS);
    let ledgers = base
        .chunks_exact_mut(OUTPUT_COLUMNS)
        .zip(higher.chunks_exact_mut(OUTPUT_COLUMNS));
    for (row, (((time, realized), weights), (base_row, higher_row))) in times
        .chunks_exact(TIME_COLUMNS)
        .zip(returns.chunks_exact(spec.width))
        .zip(targets.chunks_exact(spec.width))
        .zip(ledgers)
        .enumerate()
    {
        if row % CHECK_EVERY == 0 {
            checkpoint(check).map_err(|status| (status, NO_ROW))?;
        }
        for (scenario, (state, values)) in states.iter_mut().zip([base_row, higher_row]).enumerate()
        {
            state
                .step(time, realized, weights, spec.rates[scenario], values)
                .map_err(|status| (status, scenario * periods + row))?;
        }
    }
    checkpoint(check).map_err(|status| (status, NO_ROW))
}

/// Replays two one-way fee rates on a shared set of times, returns and targets.
/// The output consists of the base ledger followed by the higher-fee ledger,
/// each using the nine-column replay ABI. Failure leaves the output untouched.
/// A row error is encoded as scenario * periods + row, with base scenario zero.
///
/// # Safety
/// Buffers must be valid for their declared lengths and remain disjoint. The
/// inputs must stay unchanged during the call. The callback must not unwind.
#[no_mangle]
pub unsafe extern "C" fn arboris_quant_replay_fee_comparison(
    periods: usize,
    width: usize,
    times: *const i64,
    times_len: usize,
    returns: *const f64,
    returns_len: usize,
    targets: *const f64,
    targets_len: usize,
    base_rate: f64,
    higher_rate: f64,
    initial_equity: f64,
    output: *mut f64,
    output_len: usize,
    error_index: *mut usize,
    check: Check,
) -> i32 {
    let ledger_size = arboris_quant_replay_output_len(periods);
    if ledger_size == 0
        || !(1..=MAX_ASSETS).contains(&width)
        || output_len != SCENARIOS * ledger_size
        || times_len != periods * TIME_COLUMNS
        || returns_len != periods * width
        || targets_len != returns_len
        || !initial_equity.is_finite()
        || initial_equity <= 0.0
        || !(0.0..1.0).contains(&base_rate)
        || !(base_rate..1.0).contains(&higher_rate)
        || base_rate == higher_rate
    {
        return INVALID_ARGUMENT;
    }
    let [Some(clock), Some(panel), Some(weights), Some(result), Some(error)] = [
        region(times, times_len),
        region(returns, returns_len),
        region(targets, targets_len),
        region(output, output_len),
        region(error_index, 1),
    ] else {
        return INVALID_ARGUMENT;
    };
    let mut regions = [clock, panel, weights, result, error];
    regions.sort_unstable();
    if regions.windows(2).any(|pair| pair[0].1 > pair[1].0) {
        return INVALID_ARGUMENT;
    }
    unsafe { error_index.write(NO_ROW) };
    let spec = Specification {
        width,
        rates: [base_rate, higher_rate],
        initial_equity,
    };
    let result = catch_unwind(AssertUnwindSafe(|| {
        let times = unsafe { slice::from_raw_parts(times, times_len) };
        let returns = unsafe { slice::from_raw_parts(returns, returns_len) };
        let targets = unsafe { slice::from_raw_parts(targets, targets_len) };
        let mut candidate = vec![0.0; output_len];
        compare(times, returns, targets, spec, &mut candidate, check)?;
        Ok::<_, (i32, usize)>(candidate)
    }));
    match result {
        Ok(Ok(candidate)) => {
            unsafe { slice::from_raw_parts_mut(output, output_len) }.copy_from_slice(&candidate);
            0
        }
        Ok(Err((status, index))) => {
            unsafe { error_index.write(index) };
            status
        }
        Err(_) => PANIC,
    }
}
