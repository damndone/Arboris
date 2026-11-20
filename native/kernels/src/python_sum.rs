//! CPython's builtin `sum()` over floats, operation for operation (Python 3.12+).
//!
//! `sum` starts from the int 0, so the first float is added to 0.0; every later float goes
//! through Neumaier's compensated update, and the compensation is added once at the end when
//! it is nonzero and finite (so a negative zero, an infinity or an overflow is kept).

pub fn sum(values: &[f64]) -> f64 {
    let Some((first, rest)) = values.split_first() else {
        return 0.0;
    };
    let mut total = 0.0 + first;
    let mut compensation = 0.0;
    for &value in rest {
        let next = total + value;
        if total.abs() >= value.abs() {
            compensation += (total - next) + value;
        } else {
            compensation += (value - next) + total;
        }
        total = next;
    }
    if compensation != 0.0 && compensation.is_finite() {
        total += compensation;
    }
    total
}
