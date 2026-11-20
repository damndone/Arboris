#pragma once

// Included inside the Ridge module to share immutable byte reads, sums, and checkpoints.
namespace elastic_net {

enum Status : int {
    ok = 0,
    invalid_shape = 1,
    invalid_penalty = 2,
    nonfinite_input = 3,
    numerical_range = 4,
    work_limit = 5,
    not_converged = 6,
    interrupted = 7,
};

constexpr std::size_t max_rows = 100'000;
constexpr std::size_t max_columns = 128;
constexpr std::size_t max_values = 1'000'000;
constexpr std::size_t max_sweeps = 100'000;
constexpr std::size_t work_budget = 50'000'000;
constexpr double max_trace_to_l2 = 1e10;
static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559);

double mean_dot(const double* a, const double* b, std::size_t rows) {
    Sum sum;
    const double n = static_cast<double>(rows);
    for (std::size_t row = 0; row < rows; ++row) {
        sum.add((a[row] / n) * b[row]);
    }
    return sum.value();
}

double soft_threshold(double value, double penalty) {
    if (value > penalty) {
        return value - penalty;
    }
    if (value < -penalty) {
        return value + penalty;
    }
    return 0.0;
}

Status solve(const char* design, const char* target, std::size_t rows, std::size_t columns,
             double l1, double l2, double tolerance, std::size_t sweeps,
             std::vector<double>& output, Checkpoint& checkpoint) {
    std::vector<double> centered_design(rows * columns);
    std::vector<Sum> x_sums(columns);
    Sum y_sum;
    const double n = static_cast<double>(rows);
    for (std::size_t row = 0; row < rows; ++row) {
        if (row % 2048 == 0 && !checkpoint.poll()) {
            return interrupted;
        }
        const double response = at(target, row);
        if (!std::isfinite(response)) {
            return nonfinite_input;
        }
        y_sum.add(response / n);
        for (std::size_t col = 0; col < columns; ++col) {
            const double value = at(design, row * columns + col);
            if (!std::isfinite(value)) {
                return nonfinite_input;
            }
            x_sums[col].add(value / n);
            centered_design[col * rows + row] = value;
        }
    }

    const double y_mean = y_sum.value();
    double intercept_scale = 0.0;
    std::vector<double> centered_target(rows);
    for (std::size_t row = 0; row < rows; ++row) {
        const double value = at(target, row) - y_mean;
        if (!std::isfinite(value)) {
            return numerical_range;
        }
        centered_target[row] = value;
        intercept_scale = std::max(intercept_scale, std::abs(value));
    }
    if (intercept_scale == 0.0) {
        intercept_scale = 1.0;
    }

    const auto poll_columns = std::max<std::size_t>(1, 65536 / rows);
    std::vector<double> variances(columns);
    double slope_scale = l1;
    Sum trace;
    for (std::size_t col = 0; col < columns; ++col) {
        if (col % poll_columns == 0 && !checkpoint.poll()) {
            return interrupted;
        }
        double* feature = centered_design.data() + col * rows;
        const double center = x_sums[col].value();
        for (std::size_t row = 0; row < rows; ++row) {
            feature[row] -= center;
            if (!std::isfinite(feature[row])) {
                return numerical_range;
            }
        }
        const double variance = mean_dot(feature, feature, rows);
        const double cross = mean_dot(feature, centered_target.data(), rows);
        if (!std::isfinite(variance + l2) || !std::isfinite(cross)) {
            return numerical_range;
        }
        variances[col] = variance;
        trace.add(variance);
        slope_scale = std::max(slope_scale, std::abs(cross));
    }
    // A tiny L2 term can leave near-duplicate columns numerically indistinguishable.
    // The trace bounds the largest eigenvalue of the centered Gram matrix.
    if (!std::isfinite(trace.value()) || trace.value() / l2 > max_trace_to_l2) {
        return numerical_range;
    }

    std::vector<double> beta(columns, 0.0);
    std::vector<double> residual = centered_target;
    for (std::size_t sweep = 1; sweep <= sweeps; ++sweep) {
        for (std::size_t col = 0; col < columns; ++col) {
            if (col % poll_columns == 0 && !checkpoint.poll()) {
                return interrupted;
            }
            const double* feature = centered_design.data() + col * rows;
            const double partial = mean_dot(feature, residual.data(), rows) + variances[col] * beta[col];
            if (!std::isfinite(partial)) {
                return numerical_range;
            }
            const double updated = soft_threshold(partial, l1) / (variances[col] + l2);
            const double delta = updated - beta[col];
            if (!std::isfinite(delta)) {
                return numerical_range;
            }
            if (delta != 0.0) {
                beta[col] = updated;
                for (std::size_t row = 0; row < rows; ++row) {
                    residual[row] -= delta * feature[row];
                    if (!std::isfinite(residual[row])) {
                        return numerical_range;
                    }
                }
            }
        }

        // Certify against a fresh residual instead of accumulated coordinate updates.
        residual = centered_target;
        for (std::size_t col = 0; col < columns; ++col) {
            if (col % poll_columns == 0 && !checkpoint.poll()) {
                return interrupted;
            }
            const double* feature = centered_design.data() + col * rows;
            for (std::size_t row = 0; row < rows; ++row) {
                residual[row] -= beta[col] * feature[row];
                if (!std::isfinite(residual[row])) {
                    return numerical_range;
                }
            }
        }
        Sum residual_mean;
        for (const double value : residual) {
            residual_mean.add(value / n);
        }
        double max_violation = 0.0;
        double beta_scale = 1.0;
        for (std::size_t col = 0; col < columns; ++col) {
            if (col % poll_columns == 0 && !checkpoint.poll()) {
                return interrupted;
            }
            const double* feature = centered_design.data() + col * rows;
            const double gradient = -mean_dot(feature, residual.data(), rows) + l2 * beta[col];
            const double violation = beta[col] == 0.0 ? std::max(std::abs(gradient) - l1, 0.0)
                : std::abs(gradient + std::copysign(l1, beta[col]));
            if (!std::isfinite(violation)) {
                return numerical_range;
            }
            max_violation = std::max(max_violation, violation);
            beta_scale = std::max(beta_scale, std::abs(beta[col]));
        }
        const double intercept_kkt = std::abs(residual_mean.value()) / intercept_scale;
        const double kkt = std::max(intercept_kkt, max_violation / slope_scale);
        // For lambda2-strong convexity, ||beta - beta*||2 <= ||subgradient||2 / lambda2
        // in exact arithmetic. Use the computed infinity norm as a conservative estimate.
        const double coefficient_bound = (max_violation / beta_scale) / l2 * std::sqrt(columns);
        if (!std::isfinite(kkt) || !std::isfinite(coefficient_bound)) {
            return numerical_range;
        }
        if (kkt <= tolerance && coefficient_bound <= tolerance) {
            Sum offset;
            offset.add(y_mean);
            for (std::size_t col = 0; col < columns; ++col) {
                offset.add(-x_sums[col].value() * beta[col]);
            }
            if (!std::isfinite(offset.value())) {
                return numerical_range;
            }
            if (!checkpoint.poll()) {
                return interrupted;
            }
            std::copy(beta.begin(), beta.end(), output.begin());
            output[columns] = offset.value();
            output[columns + 1] = kkt;
            output[columns + 2] = coefficient_bound;
            output[columns + 3] = static_cast<double>(sweep);
            return ok;
        }
    }
    return not_converged;
}


PyObject* fit(PyObject*, PyObject* args) {
    PyObject* design;
    PyObject* target;
    PyObject* callback = Py_None;
    Py_ssize_t rows_arg, columns_arg, sweeps_arg;
    double alpha, mixing, tolerance;
    if (!PyArg_ParseTuple(args, "O!O!nndddn|O:fit_elastic_net", &PyBytes_Type, &design, &PyBytes_Type, &target,
                          &rows_arg, &columns_arg, &alpha, &mixing, &tolerance, &sweeps_arg, &callback)) {
        return nullptr;
    }
    if (rows_arg < 2 || columns_arg < 1) {
        PyErr_SetString(PyExc_ValueError, "ELASTIC_NET_INVALID_DATA: native shape requires two rows and one predictor");
        return nullptr;
    }
    const auto rows = static_cast<std::size_t>(rows_arg);
    const auto columns = static_cast<std::size_t>(columns_arg);
    if (rows > max_rows || columns > max_columns || rows * columns > max_values
        || sweeps_arg <= 0 || static_cast<std::size_t>(sweeps_arg) > max_sweeps
        || static_cast<std::size_t>(sweeps_arg) > work_budget / rows / columns) {
        PyErr_SetString(PyExc_ValueError, "ELASTIC_NET_WORK_LIMIT: training shape or sweeps exceed the work budget");
        return nullptr;
    }
    if (PyBytes_GET_SIZE(design) != static_cast<Py_ssize_t>(rows * columns * sizeof(double))
        || PyBytes_GET_SIZE(target) != static_cast<Py_ssize_t>(rows * sizeof(double))) {
        PyErr_SetString(PyExc_ValueError, "ELASTIC_NET_INVALID_DATA: native buffers do not match the declared shape");
        return nullptr;
    }
    if (!std::isfinite(alpha) || alpha <= 0.0 || !std::isfinite(mixing)
        || mixing <= 0.0 || mixing >= 1.0 || !std::isfinite(tolerance)
        || tolerance < 1e-14 || tolerance > 1e-6) {
        PyErr_SetString(PyExc_ValueError, "ELASTIC_NET_INVALID_PENALTY: invalid alpha, l1_ratio, or tolerance");
        return nullptr;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "Elastic Net checkpoint must be callable");
        return nullptr;
    }
    const double l1 = alpha * mixing;
    const double l2 = alpha * (1.0 - mixing);
    if (l1 <= 0.0 || l2 <= 0.0) {
        PyErr_SetString(PyExc_ValueError, "ELASTIC_NET_NUMERICAL_RANGE: both penalty weights must be representable");
        return nullptr;
    }
    try {
        const char* x = PyBytes_AS_STRING(design);
        const char* y = PyBytes_AS_STRING(target);
        std::vector<double> result(columns + 4);
        Status status;
        {
            Checkpoint checkpoint(callback);
            status = solve(x, y, rows, columns, l1, l2, tolerance, static_cast<std::size_t>(sweeps_arg),
                           result, checkpoint);
        }
        if (status == ok) {
            return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(result.data()),
                                             (columns_arg + 4) * sizeof(double));
        }
        if (status == nonfinite_input) {
            PyErr_SetString(PyExc_ValueError, "ELASTIC_NET_INVALID_DATA: native inputs must be finite");
        } else if (status == numerical_range) {
            PyErr_SetString(PyExc_ValueError, "ELASTIC_NET_NUMERICAL_RANGE: training values or L2 curvature are outside the numeric range");
        } else if (status == not_converged) {
            PyErr_Format(PyExc_ValueError,
                         "ELASTIC_NET_NOT_CONVERGED: %zd sweeps exhausted before meeting the tolerance", sweeps_arg);
        }
        return nullptr;
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

}  // namespace elastic_net
