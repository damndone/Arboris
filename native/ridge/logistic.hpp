#pragma once

namespace logistic {

enum class Status { ok, invalid_data, invalid_labels, single_class, numerical_range, work_limit, not_converged, interrupted };

constexpr std::size_t max_rows = 100'000;
constexpr std::size_t max_columns = 64;
constexpr std::size_t max_values = 1'000'000;
constexpr std::size_t max_iterations = 128;
constexpr std::size_t work_budget = 100'000'000;
constexpr double gradient_tolerance = 1e-10;

struct Problem {
    const char* design;
    const char* labels;
    std::size_t rows;
    std::size_t columns;
    double alpha;
    Checkpoint& checkpoint;
    std::size_t remaining_work = work_budget;

    Status evaluate(const std::vector<double>& beta, double& objective, std::vector<double>& gradient,
                    std::vector<double>* hessian) {
        const auto dimension = beta.size();
        const auto work = rows * dimension * (hessian == nullptr ? 1 : dimension);
        if (remaining_work < work) {
            return Status::work_limit;
        }
        remaining_work -= work;
        if (hessian != nullptr) {
            std::fill(hessian->begin(), hessian->end(), 0.0);
        }
        Sum loss;
        std::vector<Sum> derivatives(dimension);
        std::vector<double> features(dimension, 1.0);
        const double inverse_rows = 1.0 / static_cast<double>(rows);
        for (std::size_t row = 0; row < rows; ++row) {
            if (row % 256 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            Sum score;
            score.add(beta[columns]);
            for (std::size_t col = 0; col < columns; ++col) {
                features[col] = at(design, row * columns + col);
                if (!std::isfinite(features[col])) {
                    return Status::invalid_data;
                }
                score.add(features[col] * beta[col]);
            }
            const bool positive = at(labels, row) == 1.0;
            const double margin = positive ? score.value() : -score.value();
            if (!std::isfinite(margin)) {
                return Status::numerical_range;
            }
            const double tail = std::exp(-std::abs(margin));
            const double denominator = 1.0 + tail;
            const double residual = (positive ? -inverse_rows : inverse_rows)
                * (margin >= 0.0 ? tail : 1.0) / denominator;
            const double weight = (inverse_rows * tail) / (denominator * denominator);
            loss.add((std::max(-margin, 0.0) + std::log1p(tail)) * inverse_rows);
            for (std::size_t i = 0; i < dimension; ++i) {
                derivatives[i].add(residual * features[i]);
                if (hessian != nullptr) {
                    const double weighted = weight * features[i];
                    for (std::size_t j = 0; j <= i; ++j) {
                        (*hessian)[i * dimension + j] += weighted * features[j];
                    }
                }
            }
        }
        for (std::size_t col = 0; col < columns; ++col) {
            const double penalty_gradient = alpha * beta[col];
            loss.add(0.5 * penalty_gradient * beta[col]);
            derivatives[col].add(penalty_gradient);
            if (hessian != nullptr) {
                (*hessian)[col * dimension + col] += alpha;
            }
        }
        objective = loss.value();
        for (std::size_t col = 0; col < dimension; ++col) {
            gradient[col] = derivatives[col].value();
            if (!std::isfinite(gradient[col])) {
                return Status::numerical_range;
            }
        }
        return std::isfinite(objective) ? Status::ok : Status::numerical_range;
    }
};

double gradient_norm(const std::vector<double>& gradient) {
    double norm = 0.0;
    for (const double value : gradient) {
        norm = std::max(norm, std::abs(value));
    }
    return norm;
}

bool newton_direction(std::vector<double>& hessian, const std::vector<double>& gradient,
                      std::vector<double>& direction) {
    const auto dimension = gradient.size();
    for (std::size_t i = 0; i < dimension; ++i) {
        for (std::size_t j = 0; j <= i; ++j) {
            double value = hessian[i * dimension + j];
            for (std::size_t k = 0; k < j; ++k) {
                value -= hessian[i * dimension + k] * hessian[j * dimension + k];
            }
            if (i == j && (!(value > 0.0) || !std::isfinite(value))) {
                return false;
            }
            hessian[i * dimension + j] = i == j ? std::sqrt(value) : value / hessian[j * dimension + j];
        }
        double value = -gradient[i];
        for (std::size_t j = 0; j < i; ++j) {
            value -= hessian[i * dimension + j] * direction[j];
        }
        direction[i] = value / hessian[i * dimension + i];
    }
    for (std::size_t i = dimension; i-- > 0;) {
        for (std::size_t j = i + 1; j < dimension; ++j) {
            direction[i] -= hessian[j * dimension + i] * direction[j];
        }
        direction[i] /= hessian[i * dimension + i];
        if (!std::isfinite(direction[i])) {
            return false;
        }
    }
    return true;
}

Status solve(Problem& problem, std::size_t iterations, std::vector<double>& output) {
    std::size_t positives = 0;
    for (std::size_t row = 0; row < problem.rows; ++row) {
        if (row % 4096 == 0 && !problem.checkpoint.poll()) {
            return Status::interrupted;
        }
        const double label = at(problem.labels, row);
        if (label != 0.0 && label != 1.0) {
            return Status::invalid_labels;
        }
        positives += label == 1.0;
    }
    if (positives == 0 || positives == problem.rows) {
        return Status::single_class;
    }
    const auto dimension = problem.columns + 1;
    std::vector<double> beta(dimension, 0.0), gradient(dimension), hessian(dimension * dimension);
    std::vector<double> direction(dimension), candidate(dimension), candidate_gradient(dimension);
    beta.back() = std::log(static_cast<double>(positives)) - std::log(static_cast<double>(problem.rows - positives));
    for (std::size_t iteration = 0; iteration <= iterations; ++iteration) {
        double objective;
        const auto evaluated = problem.evaluate(beta, objective, gradient, &hessian);
        if (evaluated != Status::ok) {
            return evaluated;
        }
        const double norm = gradient_norm(gradient);
        if (norm <= gradient_tolerance) {
            if (!problem.checkpoint.poll()) {
                return Status::interrupted;
            }
            std::copy(beta.begin(), beta.end(), output.begin());
            output[dimension] = norm;
            output[dimension + 1] = objective;
            output[dimension + 2] = static_cast<double>(iteration);
            return Status::ok;
        }
        if (iteration == iterations) {
            break;
        }
        if (!newton_direction(hessian, gradient, direction)) {
            return Status::numerical_range;
        }
        Sum slope;
        for (std::size_t i = 0; i < dimension; ++i) {
            slope.add(gradient[i] * direction[i]);
        }
        const double directional_derivative = slope.value();
        if (!(directional_derivative < 0.0) || !std::isfinite(directional_derivative)) {
            return Status::numerical_range;
        }

        const double roundoff = 8.0 * std::numeric_limits<double>::epsilon() * objective;
        bool accepted = false;
        double step = 1.0;
        for (std::size_t trial = 0; trial < 24; ++trial, step *= 0.5) {
            for (std::size_t i = 0; i < dimension; ++i) {
                candidate[i] = beta[i] + step * direction[i];
            }
            double candidate_objective;
            const auto tested = problem.evaluate(candidate, candidate_objective, candidate_gradient, nullptr);
            if (tested == Status::numerical_range) {
                continue;
            }
            if (tested != Status::ok) {
                return tested;
            }
            const double expected_decrease = -step * directional_derivative;
            const bool armijo = candidate_objective < objective
                && candidate_objective <= objective - 1e-4 * expected_decrease;
            const bool rounded_loss_with_lower_gradient = expected_decrease <= roundoff && candidate_objective <= objective + roundoff
                && gradient_norm(candidate_gradient) < norm;
            if (armijo || rounded_loss_with_lower_gradient) {
                beta.swap(candidate);
                accepted = true;
                break;
            }
        }
        if (!accepted) {
            return Status::not_converged;
        }
    }
    return Status::not_converged;
}

PyObject* fit(PyObject*, PyObject* args) {
    PyObject* design;
    PyObject* labels;
    PyObject* callback = Py_None;
    Py_ssize_t rows_arg, columns_arg, iterations_arg;
    double alpha;
    if (!PyArg_ParseTuple(args, "O!O!nndn|O:fit_logistic", &PyBytes_Type, &design, &PyBytes_Type, &labels,
                          &rows_arg, &columns_arg, &alpha, &iterations_arg, &callback)) {
        return nullptr;
    }
    if (rows_arg < 2 || columns_arg < 1) {
        PyErr_SetString(PyExc_ValueError, "LOGISTIC_INVALID_DATA: training requires two rows and one predictor");
        return nullptr;
    }
    const auto rows = static_cast<std::size_t>(rows_arg);
    const auto columns = static_cast<std::size_t>(columns_arg);
    const auto dimension = columns + 1;
    if (rows > max_rows || columns > max_columns || rows * dimension > max_values
        || rows * dimension * (2 * dimension + 1) > work_budget
        || iterations_arg < 1 || static_cast<std::size_t>(iterations_arg) > max_iterations) {
        PyErr_SetString(PyExc_ValueError, "LOGISTIC_WORK_LIMIT: training shape or iterations exceed the work budget");
        return nullptr;
    }
    if (PyBytes_GET_SIZE(design) != static_cast<Py_ssize_t>(rows * columns * sizeof(double))
        || PyBytes_GET_SIZE(labels) != static_cast<Py_ssize_t>(rows * sizeof(double))) {
        PyErr_SetString(PyExc_ValueError, "LOGISTIC_INVALID_DATA: native buffers do not match the declared shape");
        return nullptr;
    }
    if (!std::isfinite(alpha) || alpha < 1e-6 || alpha > 1e6) {
        PyErr_SetString(PyExc_ValueError, "LOGISTIC_INVALID_ALPHA: alpha must be between 1e-6 and 1e6 inclusive");
        return nullptr;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "Logistic checkpoint must be callable");
        return nullptr;
    }
    try {
        const char* x = PyBytes_AS_STRING(design);
        const char* y = PyBytes_AS_STRING(labels);
        std::vector<double> output(dimension + 3);
        Status status;
        {
            Checkpoint checkpoint(callback);
            Problem problem{x, y, rows, columns, alpha, checkpoint};
            status = solve(problem, static_cast<std::size_t>(iterations_arg), output);
        }
        switch (status) {
        case Status::ok:
            return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(output.data()),
                                             (columns_arg + 4) * sizeof(double));
        case Status::invalid_data:
            PyErr_SetString(PyExc_ValueError, "LOGISTIC_INVALID_DATA: native predictors must be finite");
            break;
        case Status::invalid_labels:
            PyErr_SetString(PyExc_ValueError, "LOGISTIC_INVALID_LABELS: native labels must be exactly 0 or 1");
            break;
        case Status::single_class:
            PyErr_SetString(PyExc_ValueError, "LOGISTIC_TRAIN_SINGLE_CLASS: training must contain both 0 and 1");
            break;
        case Status::numerical_range:
            PyErr_SetString(PyExc_ValueError, "LOGISTIC_NUMERICAL_RANGE: nonfinite objective, gradient, or Newton system");
            break;
        case Status::work_limit:
            PyErr_SetString(PyExc_ValueError, "LOGISTIC_WORK_LIMIT: fitting exhausted the work budget");
            break;
        case Status::not_converged:
            PyErr_SetString(PyExc_ValueError, "LOGISTIC_NOT_CONVERGED: Newton fitting did not reach the gradient tolerance");
            break;
        case Status::interrupted:
            break;
        }
        return nullptr;
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

}  // namespace logistic
