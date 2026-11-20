//! Math kernels for workbench.native_kernels. Each one repeats the reference's arithmetic in
//! the reference's order, so results are bit-identical; threads only split independent work.
//! Callers validate arguments; a panic becomes a nonzero status, never an unwind into C.
mod numpy_rng;
mod numpy_sum;
mod python_sum;

use numpy_rng::Rng;
use std::panic::catch_unwind;
use std::slice;
use std::thread;

pub const ABI_VERSION: i32 = 2;
const MAX_THREADS: usize = 8;

#[no_mangle]
pub extern "C" fn arboris_kernels_abi() -> i32 {
    ABI_VERSION
}

fn threads_for(work: usize) -> usize {
    if work < 2_000_000 {
        return 1;
    }
    thread::available_parallelism().map_or(1, |n| n.get()).min(MAX_THREADS)
}

fn guarded(body: impl FnOnce() + std::panic::UnwindSafe) -> i32 {
    if catch_unwind(body).is_ok() { 0 } else { 1 }
}

/// Fills `out[i]` from `seeds[i]`; `one` gets the replicate's generator and a private buffer.
fn over_seeds(seeds: &[u64], out: &mut [f64], size: usize, work: usize,
              one: &(impl Fn(&mut Rng, &mut [f64]) -> f64 + Sync)) {
    let threads = threads_for(work);
    let chunk = seeds.len().div_ceil(threads).max(1);
    thread::scope(|scope| {
        for (seed_part, out_part) in seeds.chunks(chunk).zip(out.chunks_mut(chunk)) {
            scope.spawn(move || {
                let mut buffer = vec![0.0; size];
                for (seed, slot) in seed_part.iter().zip(out_part) {
                    *slot = one(&mut Rng::new(*seed), &mut buffer);
                }
            });
        }
    });
}

fn statistic(id: i32, values: &mut [f64]) -> f64 {
    if id == 0 { numpy_sum::mean(values) } else { numpy_sum::median(values) }
}

/// One bootstrap statistic per seed: `values[rng.integers(0, n, n)]`, then mean (0) or median (1).
///
/// # Safety
/// `values` holds `n` doubles; `seeds` and `out` hold `count` items each.
#[no_mangle]
pub unsafe extern "C" fn arboris_bootstrap(values: *const f64, n: usize, seeds: *const u64,
                                           count: usize, statistic_id: i32, out: *mut f64) -> i32 {
    let values = slice::from_raw_parts(values, n);
    let seeds = slice::from_raw_parts(seeds, count);
    let out = slice::from_raw_parts_mut(out, count);
    let max = (n - 1) as u32;
    guarded(std::panic::AssertUnwindSafe(|| {
        over_seeds(seeds, out, n, n * count, &|rng: &mut Rng, buffer: &mut [f64]| {
            for slot in buffer.iter_mut() {
                *slot = values[rng.bounded(max) as usize];
            }
            statistic(statistic_id, buffer)
        });
    }))
}

/// One two-sample statistic per seed: `rng.permutation(pooled)`, then the difference of the
/// means (0) or medians (1) of the first `left` values and the rest.
///
/// # Safety
/// `pooled` holds `n` doubles; `seeds` and `out` hold `count` items each.
#[no_mangle]
pub unsafe extern "C" fn arboris_permutation(pooled: *const f64, n: usize, left: usize,
                                             seeds: *const u64, count: usize, statistic_id: i32,
                                             out: *mut f64) -> i32 {
    let pooled = slice::from_raw_parts(pooled, n);
    let seeds = slice::from_raw_parts(seeds, count);
    let out = slice::from_raw_parts_mut(out, count);
    guarded(std::panic::AssertUnwindSafe(|| {
        over_seeds(seeds, out, n, n * count, &|rng: &mut Rng, buffer: &mut [f64]| {
            buffer.copy_from_slice(pooled);
            for i in (1..n).rev() {
                buffer.swap(i, rng.interval(i as u32) as usize);
            }
            let (first, second) = buffer.split_at_mut(left);
            statistic(statistic_id, first) - statistic(statistic_id, second)
        });
    }))
}

/// For each row: the squared distance to its nearest center and that center's first index.
fn nearest(row: &[f64], centers: &[f64], d: usize, squares: &mut [f64]) -> (f64, usize) {
    let mut best = (f64::INFINITY, 0);
    let mut first = true;
    for (index, center) in centers.chunks_exact(d).enumerate() {
        for ((slot, value), mean) in squares.iter_mut().zip(row).zip(center) {
            let difference = value - mean;
            *slot = difference * difference;
        }
        let distance = numpy_sum::reduce(squares);
        if first || distance < best.0 {
            best = (distance, index);
            first = false;
        }
    }
    best
}

/// `np.min(np.square(values[:, None, :] - centers[None, :, :]).sum(axis=2), axis=1)`.
///
/// # Safety
/// `values` holds `n * d` doubles, `centers` `k * d`, `out` `n`.
#[no_mangle]
pub unsafe extern "C" fn arboris_min_distances(values: *const f64, n: usize, d: usize,
                                               centers: *const f64, k: usize, out: *mut f64) -> i32 {
    let values = slice::from_raw_parts(values, n * d);
    let centers = slice::from_raw_parts(centers, k * d);
    let out = slice::from_raw_parts_mut(out, n);
    guarded(std::panic::AssertUnwindSafe(|| {
        let chunk = n.div_ceil(threads_for(n * k * d)).max(1);
        thread::scope(|scope| {
            for (rows, slots) in values.chunks(chunk * d).zip(out.chunks_mut(chunk)) {
                scope.spawn(move || {
                    let mut squares = vec![0.0; d];
                    for (row, slot) in rows.chunks_exact(d).zip(slots) {
                        *slot = nearest(row, centers, d, &mut squares).0;
                    }
                });
            }
        });
    }))
}

/// One Lloyd iteration: `labels` from argmin of the distances, `new_centers` the mean of each
/// cluster's rows, or for an empty cluster the row farthest from its nearest center.
///
/// # Safety
/// `values` holds `n * d` doubles, `centers` and `new_centers` `k * d`, `labels` `n`.
#[no_mangle]
pub unsafe extern "C" fn arboris_lloyd_step(values: *const f64, n: usize, d: usize,
                                            centers: *const f64, k: usize, labels: *mut i64,
                                            new_centers: *mut f64) -> i32 {
    let values = slice::from_raw_parts(values, n * d);
    let centers = slice::from_raw_parts(centers, k * d);
    let labels = slice::from_raw_parts_mut(labels, n);
    let new_centers = slice::from_raw_parts_mut(new_centers, k * d);
    guarded(std::panic::AssertUnwindSafe(|| {
        let chunk = n.div_ceil(threads_for(n * k * d)).max(1);
        let farthest = thread::scope(|scope| {
            let workers: Vec<_> = values.chunks(chunk * d).zip(labels.chunks_mut(chunk))
                .enumerate().map(|(part, (rows, slots))| {
                scope.spawn(move || {
                    let mut squares = vec![0.0; d];
                    let mut far = (f64::NEG_INFINITY, 0);
                    for (i, (row, slot)) in rows.chunks_exact(d).zip(slots).enumerate() {
                        let (distance, label) = nearest(row, centers, d, &mut squares);
                        *slot = label as i64;
                        if distance > far.0 {
                            far = (distance, part * chunk + i);
                        }
                    }
                    far
                })
            }).collect();
            let mut far = (f64::NEG_INFINITY, 0);
            for worker in workers {
                let part = worker.join().unwrap();
                if part.0 > far.0 {
                    far = part;
                }
            }
            far.1
        });
        let mut counts = vec![0u64; k];
        if d == 1 {
            // A single column makes `members.mean(axis=0)` one reduction along the rows.
            let mut members = vec![Vec::new(); k];
            for (value, label) in values.iter().zip(labels.iter()) {
                members[*label as usize].push(*value);
            }
            for (cluster, group) in members.iter().enumerate() {
                counts[cluster] = group.len() as u64;
                new_centers[cluster] = numpy_sum::reduce(group);
            }
        } else {
            // Otherwise each cluster's sum folds its rows in row order, from the identity.
            new_centers.fill(0.0);
            for (row, label) in values.chunks_exact(d).zip(labels.iter()) {
                let label = *label as usize;
                for (slot, value) in new_centers[label * d..(label + 1) * d].iter_mut().zip(row) {
                    *slot += value;
                }
                counts[label] += 1;
            }
        }
        for (target, count) in new_centers.chunks_exact_mut(d).zip(&counts) {
            if *count == 0 {
                target.copy_from_slice(&values[farthest * d..(farthest + 1) * d]);
            } else {
                for slot in target.iter_mut() {
                    *slot /= *count as f64;
                }
            }
        }
    }))
}

/// The Cox time-interaction score sweep when every failure time is distinct, in the order of
/// ph_score_test's loop. `rows` lists row indices by descending time, `g` the centered log
/// time of each row, `score` holds `p` values and `information` `2p * 2p` in row order.
///
/// # Safety
/// `x` holds `n * p` doubles, `weights` and `g` `n`, `rows` `n`, `event` `n`, as above for the rest.
#[no_mangle]
pub unsafe extern "C" fn arboris_ph_sweep(x: *const f64, n: usize, p: usize, weights: *const f64,
                                          g: *const f64, rows: *const i64, event: *const u8,
                                          score: *mut f64, information: *mut f64) -> i32 {
    let x = slice::from_raw_parts(x, n * p);
    let weights = slice::from_raw_parts(weights, n);
    let g = slice::from_raw_parts(g, n);
    let rows = slice::from_raw_parts(rows, n);
    let event = slice::from_raw_parts(event, n);
    let score = slice::from_raw_parts_mut(score, p);
    let information = slice::from_raw_parts_mut(information, 4 * p * p);
    guarded(std::panic::AssertUnwindSafe(|| {
        let mut s0 = 0.0;
        let mut s1 = vec![0.0; p];
        let mut s2 = vec![0.0; p * p];
        let mut mean = vec![0.0; p];
        let wide = 2 * p;
        for &row in rows {
            let row = row as usize;
            let (values, weight) = (&x[row * p..(row + 1) * p], weights[row]);
            s0 += weight;
            for i in 0..p {
                s1[i] += values[i] * weight;
                for j in 0..p {
                    s2[i * p + j] += values[i] * (values[j] * weight);
                }
            }
            if event[row] == 0 {
                continue;
            }
            let time = g[row];
            for i in 0..p {
                score[i] += time * (0.0 + values[i]);
                mean[i] = s1[i] / s0;
                score[i] -= time * mean[i];
            }
            for i in 0..p {
                for j in 0..p {
                    let variance = s2[i * p + j] / s0 - mean[i] * mean[j];
                    let scaled = time * variance;
                    information[i * wide + j] += variance;
                    information[i * wide + p + j] += scaled;
                    information[(i + p) * wide + j] += scaled;
                    information[(i + p) * wide + p + j] += time * time * variance;
                }
            }
        }
    }))
}

/// `sum(map(float, values))` as CPython computes it, into `out`.
///
/// # Safety
/// `values` holds `n` doubles and `out` one; `n` is at least 1.
#[no_mangle]
pub unsafe extern "C" fn arboris_python_sum(values: *const f64, n: usize, out: *mut f64) -> i32 {
    let values = slice::from_raw_parts(values, n);
    guarded(std::panic::AssertUnwindSafe(|| {
        *out = python_sum::sum(values);
    }))
}
