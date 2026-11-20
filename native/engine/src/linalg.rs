//! Dense least squares by Householder QR. No BLAS, so results do not depend on the host's library.
use std::sync::atomic::{AtomicUsize, Ordering};
use std::thread;
use crate::cancel;

/// Column-major n x k matrix.
pub struct Matrix { pub rows: usize, pub cols: usize, pub columns: Vec<Vec<f64>> }

pub fn dot(a: &[f64], b: &[f64]) -> f64 {
    // Fixed-order compensated sum: the result does not depend on the thread count or the host.
    let (mut sum, mut carry) = (0.0f64, 0.0f64);
    for (left, right) in a.chunks(4096).zip(b.chunks(4096)) {
        cancel::checkpoint();
        for (x, y) in left.iter().zip(right) {
            let product = x * y;
            let error = x.mul_add(*y, -product); // exact product error via fused multiply-add
            let total = sum + product;
            let z = total - sum;
            carry += (sum - (total - z)) + (product - z) + error;
            sum = total;
        }
    }
    sum + carry
}

pub struct Qr { pub vectors: Matrix, pub taus: Vec<f64>, pub r: Vec<Vec<f64>> }

pub fn qr(mut a: Matrix) -> Result<Qr, String> {
    let (n, k) = (a.rows, a.cols);
    if n <= k { return Err("fewer usable rows than coefficients".into()); }
    let mut taus = vec![0.0; k];
    let mut r = vec![vec![0.0; k]; k];
    let scale: f64 = a.columns.iter().map(|column| column.chunks(4096).fold(0.0f64, |m, block| { cancel::checkpoint(); block.iter().fold(m, |m, v| m.max(v.abs())) })).fold(0.0, f64::max);
    for j in 0..k {
        cancel::checkpoint();
        let (left, right) = a.columns.split_at_mut(j + 1);
        let column = &mut left[j];
        let norm = dot(&column[j..], &column[j..]).sqrt();
        if norm <= scale * (n as f64) * f64::EPSILON { return Err(format!("the regressors are collinear at column {j}")); }
        let alpha = if column[j] > 0.0 { -norm } else { norm };
        let u0 = column[j] - alpha;
        for block in column[j + 1..].chunks_mut(4096) { cancel::checkpoint(); for value in block { *value /= u0; } }
        column[j] = 1.0;
        let tau = -u0 / alpha;
        taus[j] = tau;
        r[j][j] = alpha;
        let v = &column[j..];
        for (offset, other) in right.iter_mut().enumerate() {
            let tail = &mut other[j..];
            let weight = tau * dot(v, tail);
            for (targets, values) in tail.chunks_mut(4096).zip(v.chunks(4096)) {
                cancel::checkpoint();
                for (target, value) in targets.iter_mut().zip(values) { *target -= weight * value; }
            }
            r[j][j + 1 + offset] = tail[0];
        }
    }
    Ok(Qr { vectors: a, taus, r })
}

impl Qr {
    /// Apply Q' to a vector in place.
    pub fn qt(&self, y: &mut [f64]) {
        for j in 0..self.vectors.cols {
            let v = &self.vectors.columns[j][j..];
            let weight = self.taus[j] * dot(v, &y[j..]);
            for (targets, values) in y[j..].chunks_mut(4096).zip(v.chunks(4096)) {
                cancel::checkpoint();
                for (target, value) in targets.iter_mut().zip(values) { *target -= weight * value; }
            }
        }
    }

    /// Apply Q to a vector in place.
    pub fn q(&self, y: &mut [f64]) {
        for j in (0..self.vectors.cols).rev() {
            let v = &self.vectors.columns[j][j..];
            let weight = self.taus[j] * dot(v, &y[j..]);
            for (targets, values) in y[j..].chunks_mut(4096).zip(v.chunks(4096)) {
                cancel::checkpoint();
                for (target, value) in targets.iter_mut().zip(values) { *target -= weight * value; }
            }
        }
    }

    pub fn solve_r(&self, b: &[f64]) -> Vec<f64> {
        let k = self.vectors.cols;
        let mut x = b[..k].to_vec();
        for i in (0..k).rev() {
            cancel::checkpoint();
            for j in i + 1..k { x[i] -= self.r[i][j] * x[j]; }
            x[i] /= self.r[i][i];
        }
        x
    }

    /// R^-1, whose product with its transpose is (X'X)^-1.
    pub fn r_inverse(&self) -> Vec<Vec<f64>> {
        let k = self.vectors.cols;
        let mut inv = vec![vec![0.0; k]; k];
        for j in 0..k {
            let mut unit = vec![0.0; k];
            unit[j] = 1.0;
            let solved = self.solve_r(&unit);
            for i in 0..k { inv[i][j] = solved[i]; }
        }
        inv
    }
}

/// (X'X)^-1 from R^-1.
pub fn bread(inverse: &[Vec<f64>]) -> Vec<Vec<f64>> {
    let k = inverse.len();
    let mut out = vec![vec![0.0; k]; k];
    for i in 0..k { for j in 0..k { out[i][j] = (0..k).map(|l| inverse[i][l] * inverse[j][l]).sum(); } }
    out
}

/// Rows per block. Blocks are fixed and added in row order, so the bits do not depend on the thread count.
const BLOCK: usize = 1 << 16;

/// Sum of weight[i] * x[i] x[i]' over rows.
pub fn weighted_cross(x: &Matrix, weights: &[f64], threads: usize) -> Vec<Vec<f64>> {
    let columns: Vec<&[f64]> = x.columns.iter().map(Vec::as_slice).collect();
    weighted_cross_slices(&columns, weights, threads)
}

pub fn weighted_cross_slices(columns: &[&[f64]], weights: &[f64], threads: usize) -> Vec<Vec<f64>> {
    let k = columns.len();
    let rows = weights.len();
    let blocks = rows.div_ceil(BLOCK).max(1);
    let next = AtomicUsize::new(0);
    let stopped = cancel::flag();
    let mut parts: Vec<(usize, Vec<f64>)> = thread::scope(|scope| {
        let handles: Vec<_> = (0..threads.clamp(1, blocks)).map(|_| {
            let next = &next;
            let stopped = stopped.clone();
            scope.spawn(move || {
                let mut done = Vec::new();
                loop {
                    if stopped.as_ref().is_some_and(|flag| flag.load(Ordering::Relaxed)) { return done; }
                    let block = next.fetch_add(1, Ordering::Relaxed);
                    if block >= blocks { return done; }
                    let (start, end) = (block * BLOCK, ((block + 1) * BLOCK).min(rows));
                    let w = &weights[start..end];
                    let mut out = vec![0.0; k * k];
                    for a in 0..k {
                        let left = &columns[a][start..end];
                        for b in a..k {
                            let right = &columns[b][start..end];
                            let mut sum = 0.0;
                            for ((w, left), right) in w.chunks(4096).zip(left.chunks(4096)).zip(right.chunks(4096)) {
                                if stopped.as_ref().is_some_and(|flag| flag.load(Ordering::Relaxed)) { return done; }
                                for i in 0..left.len() { sum += w[i] * left[i] * right[i]; }
                            }
                            out[a * k + b] = sum;
                        }
                    }
                    done.push((block, out));
                }
            })
        }).collect();
        // Only this owner thread may call Python. Scoped helpers only read its stop flag;
        // scope drains all of them even when the owner's checkpoint unwinds to the C boundary.
        if stopped.is_some() {
            while handles.iter().any(|handle| !handle.is_finished()) {
                cancel::checkpoint();
                thread::sleep(std::time::Duration::from_millis(1));
            }
            cancel::checkpoint();
        }
        handles.into_iter().flat_map(|handle| handle.join().expect("worker")).collect()
    });
    parts.sort_by_key(|part| part.0);
    let mut meat = vec![vec![0.0; k]; k];
    for (_, part) in parts {
        for a in 0..k { for b in a..k { meat[a][b] += part[a * k + b]; meat[b][a] = meat[a][b]; } }
    }
    meat
}

/// Solve A x = b for a small dense A by Gaussian elimination with partial pivoting.
pub fn solve_dense(mut a: Vec<Vec<f64>>, mut b: Vec<f64>) -> Result<Vec<f64>, String> {
    let k = b.len();
    for column in 0..k {
        cancel::checkpoint();
        let pivot = (column..k).max_by(|i, j| a[*i][column].abs().total_cmp(&a[*j][column].abs())).unwrap_or(column);
        if a[pivot][column] == 0.0 || !a[pivot][column].is_finite() { return Err("singular covariance block".into()); }
        a.swap(column, pivot);
        b.swap(column, pivot);
        for row in column + 1..k {
            let factor = a[row][column] / a[column][column];
            for j in column..k { a[row][j] -= factor * a[column][j]; }
            b[row] -= factor * b[column];
        }
    }
    let mut x = vec![0.0; k];
    for i in (0..k).rev() {
        let tail: f64 = (i + 1..k).map(|j| a[i][j] * x[j]).sum();
        x[i] = (b[i] - tail) / a[i][i];
    }
    Ok(x)
}

pub fn sandwich(bread: &[Vec<f64>], meat: &[Vec<f64>]) -> Vec<Vec<f64>> {
    let k = bread.len();
    let mut first = vec![vec![0.0; k]; k];
    for i in 0..k { for j in 0..k { first[i][j] = (0..k).map(|l| bread[i][l] * meat[l][j]).sum(); } }
    let mut out = vec![vec![0.0; k]; k];
    for i in 0..k { for j in 0..k { out[i][j] = (0..k).map(|l| first[i][l] * bread[l][j]).sum(); } }
    out
}
