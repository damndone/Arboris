use super::{Failure, Point, DIMENSIONS, STARTS};

const MAX_STEPS: usize = 128;
const MAX_EVALUATIONS_PER_START: usize = 256;
const SCORE_TOLERANCE: f64 = 1e-7;
const OBJECTIVE_TIE: f64 = 1e-8;
const TRANSITION_LOGIT_LIMIT: f64 = 9.21024036697585;
const LOWER: Point = [
    -2.0,
    -14.0,
    -52.0,
    -TRANSITION_LOGIT_LIMIT,
    -TRANSITION_LOGIT_LIMIT,
];
const UPPER: Point = [
    2.0,
    std::f64::consts::LN_2 * 2.0,
    std::f64::consts::LN_2 * 2.0,
    TRANSITION_LOGIT_LIMIT,
    TRANSITION_LOGIT_LIMIT,
];
type Matrix = [Point; DIMENSIONS];

fn dot(left: Point, right: Point) -> f64 {
    left.iter().zip(right).map(|(a, b)| a * b).sum()
}

fn max_abs(values: Point) -> f64 {
    values.into_iter().map(f64::abs).fold(0.0, f64::max)
}

fn identity() -> Matrix {
    let mut matrix = [[0.0; DIMENSIONS]; DIMENSIONS];
    for (i, row) in matrix.iter_mut().enumerate() {
        row[i] = 1.0;
    }
    matrix
}

fn feasible(point: Point, margin: f64) -> bool {
    point
        .into_iter()
        .zip(LOWER)
        .zip(UPPER)
        .all(|((value, lower), upper)| value > lower + margin && value < upper - margin)
}

#[derive(Clone, Copy)]
struct Candidate {
    point: Point,
    value: f64,
    iterations: usize,
    converged: bool,
}

fn search(
    start: Point,
    budget: &mut usize,
    evaluate: &mut impl FnMut(Point) -> Result<(f64, Point), Failure>,
) -> Result<Candidate, Failure> {
    *budget -= 1;
    let (value, mut gradient) = evaluate(start)?;
    let mut candidate = Candidate {
        point: start,
        value,
        iterations: 0,
        converged: false,
    };
    let mut inverse_hessian = identity();
    for iteration in 0..=MAX_STEPS {
        let score = max_abs(gradient);
        if score <= SCORE_TOLERANCE {
            candidate.converged = feasible(candidate.point, 0.04);
            break;
        }
        if iteration == MAX_STEPS || *budget == 0 {
            break;
        }
        let mut direction = inverse_hessian.map(|row| -dot(row, gradient));
        if !direction.iter().all(|value| value.is_finite()) || dot(direction, gradient) >= 0.0 {
            direction = gradient.map(|value| -value);
            inverse_hessian = identity();
        }
        let slope = dot(direction, gradient);
        let mut fraction = (1.5 / max_abs(direction)).min(1.0);
        let mut next = None;
        for _ in 0..24 {
            if *budget == 0 {
                break;
            }
            let trial = std::array::from_fn(|i| candidate.point[i] + fraction * direction[i]);
            if feasible(trial, 0.0) {
                *budget -= 1;
                match evaluate(trial) {
                    Ok((value, new_gradient)) => {
                        let expected = -fraction * slope;
                        let roundoff = 16.0 * f64::EPSILON * (1.0 + candidate.value.abs());
                        let descent =
                            value < candidate.value && value <= candidate.value - 1e-4 * expected;
                        let rounded = expected <= roundoff
                            && value <= candidate.value + roundoff
                            && max_abs(new_gradient) < score;
                        if descent || rounded {
                            next = Some((trial, value, new_gradient));
                            break;
                        }
                    }
                    Err(Failure::Cancelled) => return Err(Failure::Cancelled),
                    Err(_) => {}
                }
            }
            fraction *= 0.5;
        }
        let Some((point, value, next_gradient)) = next else {
            break;
        };
        let step = std::array::from_fn(|i| point[i] - candidate.point[i]);
        let change = std::array::from_fn(|i| next_gradient[i] - gradient[i]);
        let curvature = dot(step, change);
        if curvature > 1e-12 * dot(step, step) {
            let projected = inverse_hessian.map(|row| dot(row, change));
            let scale = (1.0 + dot(change, projected) / curvature) / curvature;
            for i in 0..DIMENSIONS {
                for j in 0..DIMENSIONS {
                    inverse_hessian[i][j] += scale * step[i] * step[j]
                        - (projected[i] * step[j] + step[i] * projected[j]) / curvature;
                }
            }
        } else {
            inverse_hessian = identity();
        }
        candidate.point = point;
        candidate.value = value;
        candidate.iterations = iteration + 1;
        gradient = next_gradient;
    }
    Ok(candidate)
}

fn check_curvature(
    point: Point,
    evaluate: &mut impl FnMut(Point) -> Result<(f64, Point), Failure>,
) -> Result<(), Failure> {
    let mut hessian = [[0.0; DIMENSIONS]; DIMENSIONS];
    for i in 0..DIMENSIONS {
        let step = 1e-4 * (1.0 + point[i].abs());
        let mut probe = point;
        probe[i] += step;
        let right = evaluate(probe)?.1;
        probe[i] = point[i] - step;
        let left = evaluate(probe)?.1;
        for j in 0..DIMENSIONS {
            hessian[j][i] = (right[j] - left[j]) / (2.0 * step);
        }
    }
    let diagonal: Point = std::array::from_fn(|i| hessian[i][i]);
    if diagonal
        .iter()
        .any(|&value| !value.is_finite() || value < 1e-8)
    {
        return Err(Failure::Degenerate);
    }
    let scale = diagonal.map(f64::sqrt);
    let mut factor = [[0.0; DIMENSIONS]; DIMENSIONS];
    for i in 0..DIMENSIONS {
        for j in 0..=i {
            let normalized = 0.5 * (hessian[i][j] + hessian[j][i]) / (scale[i] * scale[j]);
            let previous: f64 = factor[i][..j]
                .iter()
                .zip(&factor[j][..j])
                .map(|(a, b)| a * b)
                .sum();
            let remainder = normalized - previous;
            factor[i][j] = if i == j {
                if !remainder.is_finite() || remainder <= 1e-6 {
                    return Err(Failure::Degenerate);
                }
                remainder.sqrt()
            } else {
                remainder / factor[j][j]
            };
        }
    }
    Ok(())
}

pub(super) fn minimize(
    starts: [Point; STARTS],
    evaluations: usize,
    mut evaluate: impl FnMut(Point) -> Result<(f64, Point), Failure>,
) -> Result<(Point, usize), Failure> {
    let mut remaining = evaluations.saturating_sub(2 * DIMENSIONS);
    if remaining < STARTS {
        return Err(Failure::WorkLimit);
    }
    let mut candidates = [None; STARTS];
    let mut failure = Failure::Convergence;
    for (i, start) in starts.into_iter().enumerate() {
        let allowance = remaining
            .div_ceil(STARTS - i)
            .min(MAX_EVALUATIONS_PER_START);
        let mut budget = allowance;
        if budget == 0 {
            break;
        }
        match search(start, &mut budget, &mut evaluate) {
            Ok(candidate) => candidates[i] = Some(candidate),
            Err(Failure::Cancelled) => return Err(Failure::Cancelled),
            Err(error) => failure = error,
        }
        remaining -= allowance - budget;
    }
    let best_value = candidates
        .iter()
        .flatten()
        .map(|candidate| candidate.value)
        .min_by(f64::total_cmp);
    let Some(best_value) = best_value else {
        return Err(failure);
    };
    let selected = candidates
        .iter()
        .flatten()
        .filter(|candidate| candidate.converged && candidate.value <= best_value + OBJECTIVE_TIE)
        .min_by(|a, b| a.value.total_cmp(&b.value));
    let Some(selected) = selected else {
        return Err(if remaining == 0 {
            Failure::WorkLimit
        } else {
            Failure::Convergence
        });
    };
    for other in candidates.iter().flatten() {
        if (selected.value - other.value).abs() <= OBJECTIVE_TIE
            && selected
                .point
                .iter()
                .zip(other.point)
                .any(|(a, b)| (a - b).abs() > 5e-3)
        {
            return Err(Failure::Degenerate);
        }
    }
    check_curvature(selected.point, &mut evaluate)?;
    Ok((selected.point, selected.iterations))
}
