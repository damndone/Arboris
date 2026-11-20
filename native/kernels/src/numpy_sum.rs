//! NumPy's float64 `add.reduce`, operation for operation, so that sums round the same way.

fn pairwise(a: &[f64]) -> f64 {
    let n = a.len();
    if n < 8 {
        let mut total = -0.0;
        for value in a {
            total += value;
        }
        total
    } else if n <= 128 {
        let mut r = [a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]];
        let blocks = n - n % 8;
        let mut i = 8;
        while i < blocks {
            for j in 0..8 {
                r[j] += a[i + j];
            }
            i += 8;
        }
        let mut total = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for value in &a[blocks..] {
            total += value;
        }
        total
    } else {
        let half = n / 2;
        let half = half - half % 8;
        pairwise(&a[..half]) + pairwise(&a[half..])
    }
}

/// `np.add.reduce` of a contiguous vector: its identity, plus the pairwise sum of all of it.
pub fn reduce(a: &[f64]) -> f64 {
    0.0 + pairwise(a)
}

pub fn mean(a: &[f64]) -> f64 {
    reduce(a) / a.len() as f64
}

/// `np.median` of a vector with no NaN and no negative zero; reorders `a`.
pub fn median(a: &mut [f64]) -> f64 {
    let n = a.len();
    let mid = n / 2;
    let (below, upper, _) = a.select_nth_unstable_by(mid, f64::total_cmp);
    let upper = *upper;
    if n % 2 == 1 {
        return upper;
    }
    let lower = below.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    (lower + upper) / 2.0
}
