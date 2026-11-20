//! arboris-engine as a library: the command-line program and the in-process C ABI share these fits.
//! A panic becomes a nonzero status, never an unwind into C.
pub mod csv;
pub mod dist;
pub mod iv;
pub mod linalg;
pub mod models;

use std::panic::catch_unwind;
use std::slice;

pub const ABI_VERSION: i32 = 1;
pub const STATUS_OK: i32 = 0;
pub const STATUS_PANIC: i32 = 1;
/// The requested dimensions are outside the fitted diagnostics' domain.
pub const STATUS_NOT_IDENTIFIED: i32 = 2;
pub const STATUS_BAD_ARGUMENTS: i32 = 3;
/// A computation failed after input admission; never an unsupported-feature fallback.
pub const STATUS_NUMERICAL_ERROR: i32 = 4;
/// The execution owner's checkpoint interrupted this call; never fall back.
pub const STATUS_CANCELLED: i32 = 5;

/// Per-call cancellation only: the existing Python execution owner is the sole authority.
/// Controlled unwinding stays inside catch_unwind and does not invoke a panic hook.
pub(crate) mod cancel {
    use std::cell::Cell;
    use std::ffi::c_void;
    use std::sync::{Arc, atomic::{AtomicBool, Ordering}};

    pub type Check = extern "C" fn(*mut c_void) -> i32;
    pub struct Cancelled;
    struct Owner { check: Check, context: *mut c_void, stopped: Arc<AtomicBool> }
    thread_local! { static OWNER: Cell<*const Owner> = const { Cell::new(std::ptr::null()) }; }
    struct Restore(*const Owner);
    impl Drop for Restore { fn drop(&mut self) { OWNER.with(|slot| slot.set(self.0)); } }

    pub fn scope<T>(check: Option<Check>, context: *mut c_void, call: impl FnOnce() -> T) -> T {
        let Some(check) = check else { return call(); };
        let owner = Owner { check, context, stopped: Arc::new(AtomicBool::new(false)) };
        let _restore = Restore(OWNER.with(|slot| slot.replace(&owner)));
        call()
    }

    pub fn checkpoint() {
        OWNER.with(|slot| {
            let pointer = slot.get();
            if pointer.is_null() { return; }
            // Only the calling/owner thread can enter this TLS scope. Rust helpers never call Python.
            let owner = unsafe { &*pointer };
            if owner.stopped.load(Ordering::Relaxed) || (owner.check)(owner.context) != 0 {
                owner.stopped.store(true, Ordering::Relaxed);
                std::panic::resume_unwind(Box::new(Cancelled));
            }
        });
    }

    pub fn flag() -> Option<Arc<AtomicBool>> {
        OWNER.with(|slot| unsafe { slot.get().as_ref().map(|owner| Arc::clone(&owner.stopped)) })
    }
    pub fn copy(values: &[f64]) -> Vec<f64> {
        let mut result = Vec::with_capacity(values.len());
        for block in values.chunks(4096) { checkpoint(); result.extend_from_slice(block); }
        result
    }
}

#[no_mangle]
pub extern "C" fn arboris_engine_abi() -> i32 { ABI_VERSION }

/// Doubles `arboris_iv_2sls` writes for k = n_exog + n_endog parameters.
#[no_mangle]
pub extern "C" fn arboris_iv_2sls_output_len(n_exog: usize, n_endog: usize) -> usize {
    let k = n_exog + n_endog;
    k + k * k + 2 + n_endog + 5
}

unsafe fn columns<'a>(pointers: *const *const f64, count: usize, rows: usize) -> Vec<&'a [f64]> {
    if count == 0 { return Vec::new(); }
    slice::from_raw_parts(pointers, count).iter().map(|pointer| slice::from_raw_parts(*pointer, rows)).collect()
}

/// Output, in order: params[k], cov[k*k] row-major, ssr, centered tss, first-stage Wald[n_endog],
/// first-stage residual df, Wooldridge regression, Wooldridge overid, Sargan, Wu-Hausman (NaN when not computed).
///
/// # Safety
/// Every column pointer must address `rows` doubles and `out` must address `out_len` doubles.
#[no_mangle]
pub unsafe extern "C" fn arboris_iv_2sls(
    rows: usize, y: *const f64,
    exog: *const *const f64, n_exog: usize,
    endog: *const *const f64, n_endog: usize,
    instruments: *const *const f64, n_instruments: usize,
    covariance: i32, threads: usize, out: *mut f64, out_len: usize,
) -> i32 {
    iv_entry(rows, y, exog, n_exog, endog, n_endog, instruments, n_instruments,
             covariance, threads, out, out_len, None, std::ptr::null_mut())
}

/// Cancellable extension of the unchanged legacy C entry point.
/// The callback must not unwind; nonzero requests cancellation by the existing owner.
/// # Safety
/// The legacy entry point's pointer requirements apply; callback/context must live until return.
#[no_mangle]
pub unsafe extern "C" fn arboris_iv_2sls_cancellable(
    rows: usize, y: *const f64,
    exog: *const *const f64, n_exog: usize,
    endog: *const *const f64, n_endog: usize,
    instruments: *const *const f64, n_instruments: usize,
    covariance: i32, threads: usize, out: *mut f64, out_len: usize,
    check: Option<cancel::Check>, context: *mut std::ffi::c_void,
) -> i32 {
    iv_entry(rows, y, exog, n_exog, endog, n_endog, instruments, n_instruments,
             covariance, threads, out, out_len, check, context)
}

unsafe fn iv_entry(
    rows: usize, y: *const f64,
    exog: *const *const f64, n_exog: usize,
    endog: *const *const f64, n_endog: usize,
    instruments: *const *const f64, n_instruments: usize,
    covariance: i32, threads: usize, out: *mut f64, out_len: usize,
    check: Option<cancel::Check>, context: *mut std::ffi::c_void,
) -> i32 {
    if out_len != arboris_iv_2sls_output_len(n_exog, n_endog) || y.is_null() || out.is_null() { return STATUS_BAD_ARGUMENTS; }
    let kind = match covariance { 0 => iv::Covariance::Unadjusted, 1 => iv::Covariance::Robust, _ => return STATUS_BAD_ARGUMENTS };
    if n_endog == 0 || n_instruments < n_endog || rows <= n_exog + 2 * n_endog {
        return STATUS_NOT_IDENTIFIED;
    }
    let input = iv::IvInput {
        y: slice::from_raw_parts(y, rows),
        exog: columns(exog, n_exog, rows),
        endog: columns(endog, n_endog, rows),
        instruments: columns(instruments, n_instruments, rows),
        covariance: kind,
        threads: threads.max(1),
    };
    let out = slice::from_raw_parts_mut(out, out_len);
    match catch_unwind(|| cancel::scope(check, context, || {
        cancel::checkpoint();
        let fit = iv::iv_2sls(&input);
        cancel::checkpoint();
        fit
    })) {
        Err(error) => if error.is::<cancel::Cancelled>() { STATUS_CANCELLED } else { STATUS_PANIC },
        Ok(Err(_)) => STATUS_NUMERICAL_ERROR,
        Ok(Ok(fit)) => {
            let mut values = fit.params.clone();
            for row in &fit.cov { values.extend_from_slice(row); }
            values.extend([fit.ssr, fit.centered_tss]);
            values.extend_from_slice(&fit.first_stage_wald);
            values.extend([fit.first_stage_df_resid, fit.wooldridge_regression, fit.wooldridge_overid, fit.sargan, fit.wu_hausman]);
            out.copy_from_slice(&values);
            STATUS_OK
        }
    }
}

#[cfg(test)]
mod cancellation_tests {
    use super::*;
    use std::sync::Arc;

    extern "C" fn stop(_context: *mut std::ffi::c_void) -> i32 { 1 }

    #[test]
    fn parallel_cancel_joins_every_helper_before_the_owner_returns() {
        let values = vec![1.0; (1 << 17) + 1];
        let columns = vec![values.as_slice(); 32];
        let mut stopped = None;
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            cancel::scope(Some(stop), std::ptr::null_mut(), || {
                stopped = cancel::flag();
                // First owner check is inside the real parallel accumulation, after helpers spawn.
                linalg::weighted_cross_slices(&columns, &values, 2);
            });
        }));
        assert!(result.unwrap_err().is::<cancel::Cancelled>());
        let stopped = stopped.unwrap();
        assert!(stopped.load(std::sync::atomic::Ordering::Relaxed));
        // Each scoped helper owns a clone. No clone/compute survives the caught owner exit.
        assert_eq!(Arc::strong_count(&stopped), 1);
        assert!(cancel::flag().is_none());
    }
}
