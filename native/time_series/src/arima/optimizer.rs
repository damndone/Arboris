use super::{Coefficients, Failure, Sample, StateSpace, MAX_DYNAMICS, MAX_ORDER, MAX_STATE};

const MAX_ITERATIONS: usize = 80;
const MAX_EVALUATIONS_PER_START: usize = 512;
const MAX_LIKELIHOOD_WORK: usize = 180_000_000;
const MAX_TRANSFORM: f64 = 3.5;
const GRADIENT_TOLERANCE: f64 = 1e-7;
const OBJECTIVE_TIE: f64 = 1e-8;

pub(super) type Coordinates = [f64; MAX_DYNAMICS];

fn autoregression(coordinates: &[f64]) -> Coefficients {
    let mut coefficients = [0.0; MAX_ORDER];
    for (degree, &coordinate) in coordinates.iter().enumerate() {
        let reflection = coordinate.tanh();
        let previous = coefficients;
        for index in 0..degree {
            coefficients[index] = previous[index] - reflection * previous[degree - 1 - index];
        }
        coefficients[degree] = reflection;
    }
    coefficients
}

pub(super) fn dynamics(point: &Coordinates, p: usize, q: usize) -> (Coefficients, Coefficients) {
    (
        autoregression(&point[..p]),
        autoregression(&point[p..p + q]).map(|coefficient| -coefficient),
    )
}

struct Objective<'a, Evaluate> {
    evaluate: &'a Evaluate,
    dimension: usize,
    budget: usize,
}

impl<Evaluate: Fn(&Coordinates) -> Result<f64, Failure>> Objective<'_, Evaluate> {
    fn at(&mut self, point: &Coordinates) -> Result<f64, Failure> {
        if self.budget == 0 {
            return Err(Failure::Convergence);
        }
        self.budget -= 1;
        (self.evaluate)(point)
    }

    fn gradient(&mut self, point: &Coordinates) -> Result<Coordinates, Failure> {
        let mut result = [0.0; MAX_DYNAMICS];
        for i in 0..self.dimension {
            let step = 6e-6 * (1.0 + point[i].abs());
            let mut probe = *point;
            probe[i] += step;
            let right = self.at(&probe)?;
            probe[i] = point[i] - step;
            result[i] = (right - self.at(&probe)?) / (2.0 * step);
        }
        Ok(result)
    }

    fn check_curvature(&mut self, point: &Coordinates, value: f64) -> Result<(), Failure> {
        let mut factor = [[0.0; MAX_DYNAMICS]; MAX_DYNAMICS];
        let h = 1e-3;
        for i in 0..self.dimension {
            for j in 0..=i {
                let mut probe = *point;
                probe[i] += h;
                let curvature = if i == j {
                    let right = self.at(&probe)?;
                    probe[i] = point[i] - h;
                    (right - 2.0 * value + self.at(&probe)?) / (h * h)
                } else {
                    probe[j] += h;
                    let right_right = self.at(&probe)?;
                    probe[j] = point[j] - h;
                    let right_left = self.at(&probe)?;
                    probe[i] = point[i] - h;
                    let left_left = self.at(&probe)?;
                    probe[j] = point[j] + h;
                    (right_right - right_left + left_left - self.at(&probe)?) / (4.0 * h * h)
                };
                let prior: f64 = factor[i][..j]
                    .iter()
                    .zip(&factor[j][..j])
                    .map(|(a, b)| a * b)
                    .sum();
                let remainder = curvature - prior;
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
}

fn dot(left: &Coordinates, right: &Coordinates) -> f64 {
    left.iter().zip(right).map(|(a, b)| a * b).sum()
}

fn identity() -> [Coordinates; MAX_DYNAMICS] {
    let mut result = [[0.0; MAX_DYNAMICS]; MAX_DYNAMICS];
    for (i, row) in result.iter_mut().enumerate() {
        row[i] = 1.0;
    }
    result
}

#[derive(Clone, Copy)]
struct Candidate {
    point: Coordinates,
    value: f64,
    iterations: usize,
    converged: bool,
}

fn search<Evaluate: Fn(&Coordinates) -> Result<f64, Failure>>(
    objective: &mut Objective<'_, Evaluate>,
    start: Coordinates,
) -> Result<Candidate, Failure> {
    let order = objective.dimension;
    let mut candidate = Candidate {
        point: start,
        value: objective.at(&start)?,
        iterations: 0,
        converged: false,
    };
    let mut inverse_hessian = identity();
    if objective.budget < 2 * order {
        return Ok(candidate);
    }
    let mut gradient = objective.gradient(&start)?;
    for _ in 0..MAX_ITERATIONS {
        let largest_gradient = gradient.iter().map(|g| g.abs()).fold(0.0, f64::max);
        if largest_gradient <= GRADIENT_TOLERANCE {
            candidate.converged = candidate
                .point
                .iter()
                .all(|p| p.abs() < MAX_TRANSFORM - 0.05);
            return Ok(candidate);
        }
        if objective.budget <= 2 * order {
            break;
        }
        let mut direction = [0.0; MAX_DYNAMICS];
        for i in 0..order {
            direction[i] = -dot(&inverse_hessian[i], &gradient);
        }
        if !direction.iter().all(|d| d.is_finite()) || dot(&direction, &gradient) >= 0.0 {
            direction = gradient.map(|value| -value);
            inverse_hessian = identity();
        }
        let max_step = direction.iter().map(|d| d.abs()).fold(0.0, f64::max);
        let mut fraction = (1.5 / max_step).min(1.0);
        let slope = dot(&direction, &gradient);
        let mut next = None;
        for _ in 0..24 {
            let mut trial = candidate.point;
            for i in 0..order {
                trial[i] += fraction * direction[i];
            }
            if trial.iter().all(|p| p.abs() < MAX_TRANSFORM) {
                match objective.at(&trial) {
                    Ok(value) if value <= candidate.value + 1e-4 * fraction * slope => {
                        next = Some((trial, value));
                        break;
                    }
                    Err(Failure::Cancelled) => return Err(Failure::Cancelled),
                    _ => {}
                }
            }
            if objective.budget <= 2 * order {
                break;
            }
            fraction *= 0.5;
        }
        let Some((next_point, next_value)) = next else {
            break;
        };
        if objective.budget < 2 * order {
            candidate.point = next_point;
            candidate.value = next_value;
            break;
        }
        let next_gradient = objective.gradient(&next_point)?;
        let mut step = [0.0; MAX_DYNAMICS];
        let mut change = [0.0; MAX_DYNAMICS];
        for i in 0..order {
            step[i] = next_point[i] - candidate.point[i];
            change[i] = next_gradient[i] - gradient[i];
        }
        let curvature = dot(&step, &change);
        if curvature > 1e-12 * dot(&step, &step) {
            let projected = inverse_hessian.map(|row| dot(&row, &change));
            let diagonal = (1.0 + dot(&change, &projected) / curvature) / curvature;
            for i in 0..order {
                for j in 0..order {
                    inverse_hessian[i][j] += diagonal * step[i] * step[j]
                        - (projected[i] * step[j] + step[i] * projected[j]) / curvature;
                }
            }
        } else {
            inverse_hessian = identity();
        }
        candidate.point = next_point;
        candidate.value = next_value;
        candidate.iterations += 1;
        gradient = next_gradient;
    }
    Ok(candidate)
}

pub(super) fn fit(
    sample: &Sample,
    p: usize,
    q: usize,
) -> Result<(Coefficients, Coefficients, usize), Failure> {
    let dimension = p + q;
    if dimension == 0 {
        return Ok(([0.0; MAX_ORDER], [0.0; MAX_ORDER], 0));
    }
    let (starts, count) = ordinary_starts(p, q);
    let starts = &starts[..count];
    let width = p.max(q + 1) + sample.difference;
    let work = sample.values.len() * width * width;
    let (point, iterations) = minimize(starts, dimension, work, |point| {
        let (ar, ma) = dynamics(point, p, q);
        sample.objective(&StateSpace::<MAX_STATE>::new(
            &ar[..p],
            &ma[..q],
            sample.difference,
        ))
    })?;
    let (ar, ma) = dynamics(&point, p, q);
    Ok((ar, ma, iterations))
}

pub(super) fn ordinary_starts(p: usize, q: usize) -> ([[f64; MAX_DYNAMICS]; 3], usize) {
    let mut starts = [[0.0; MAX_DYNAMICS]; 3];
    if q > 0 {
        starts[1][p] = 0.45;
        starts[2][p] = -0.45;
        if p > 0 {
            starts[1][0] = 0.75;
            starts[2][0] = -0.75;
        }
    }
    (starts, if q == 0 { 1 } else { 3 })
}

pub(super) fn enough_budget(work: usize, dimension: usize) -> bool {
    MAX_LIKELIHOOD_WORK / work >= (2 * dimension + 1) * 18 + 2 * dimension * dimension
}

pub(super) fn minimize(
    starts: &[Coordinates],
    dimension: usize,
    work: usize,
    evaluate: impl Fn(&Coordinates) -> Result<f64, Failure>,
) -> Result<(Coordinates, usize), Failure> {
    let curvature_cost = 2 * dimension * dimension;
    let mut remaining = (MAX_LIKELIHOOD_WORK / work).saturating_sub(curvature_cost);
    let mut candidates = [None; 3];
    let mut failure = Failure::Convergence;
    for (index, &point) in starts.iter().enumerate() {
        let budget = if index + 1 < starts.len() {
            remaining.div_ceil(2)
        } else {
            remaining
        }
        .min(MAX_EVALUATIONS_PER_START);
        if budget == 0 {
            break;
        }
        let mut objective = Objective {
            evaluate: &evaluate,
            dimension,
            budget,
        };
        match search(&mut objective, point) {
            Ok(candidate) => candidates[index] = Some(candidate),
            Err(Failure::Cancelled) => return Err(Failure::Cancelled),
            Err(error) => failure = error,
        }
        remaining -= budget - objective.budget;
    }
    let best_value = candidates
        .iter()
        .flatten()
        .map(|c| c.value)
        .min_by(f64::total_cmp);
    let Some(best_value) = best_value else {
        return Err(failure);
    };
    let best = candidates
        .iter()
        .flatten()
        .filter(|c| c.converged && c.value <= best_value + OBJECTIVE_TIE)
        .min_by(|left, right| left.value.total_cmp(&right.value))
        .ok_or(Failure::Convergence)?;
    for candidate in candidates.iter().flatten().filter(|c| c.converged) {
        if (candidate.value - best.value).abs() <= OBJECTIVE_TIE
            && candidate
                .point
                .iter()
                .zip(best.point)
                .any(|(left, right)| (left - right).abs() > 5e-3)
        {
            return Err(Failure::Degenerate);
        }
    }
    let mut objective = Objective {
        evaluate: &evaluate,
        dimension,
        budget: curvature_cost,
    };
    objective.check_curvature(&best.point, best.value)?;
    Ok((best.point, best.iterations))
}
