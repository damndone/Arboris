#pragma once

namespace ridge_selection {

constexpr std::size_t max_candidates = 16;

struct Sample {
    const char* design;
    const char* outcome;
    std::size_t rows;
};

FitStatus validate_sample(Sample sample, std::size_t columns, Checkpoint& checkpoint) {
    for (std::size_t row = 0; row < sample.rows; ++row) {
        if (row % 1024 == 0 && !checkpoint.poll()) {
            return FitStatus::interrupted;
        }
        if (!std::isfinite(at(sample.outcome, row))) {
            return FitStatus::nonfinite_input;
        }
        for (std::size_t column = 0; column < columns; ++column) {
            if (!std::isfinite(at(sample.design, row * columns + column))) {
                return FitStatus::nonfinite_input;
            }
        }
    }
    return FitStatus::ok;
}

struct ScaledSquares {
    double scale = 0.0;
    Sum squares;

    void add(double residual) {
        const double magnitude = std::abs(residual);
        if (magnitude > scale) {
            const double ratio = scale / magnitude;
            const double factor = ratio * ratio;
            squares.total *= factor;
            squares.correction *= factor;
            scale = magnitude;
        }
        if (magnitude > 0.0) {
            const double scaled = magnitude / scale;
            squares.add(scaled * scaled);
        }
    }
};

FitStatus validation_loss(
    Sample validation, std::size_t columns, const std::vector<double>& coefficients, double magnitude,
    double& result, Checkpoint& checkpoint
) {
    ScaledSquares errors;
    for (std::size_t row = 0; row < validation.rows; ++row) {
        if (row % 1024 == 0 && !checkpoint.poll()) {
            return FitStatus::interrupted;
        }
        Sum score;
        score.add(coefficients[columns]);
        for (std::size_t column = 0; column < columns; ++column) {
            score.add(at(validation.design, row * columns + column) * coefficients[column]);
        }
        const double residual = score.value() * magnitude - at(validation.outcome, row);
        if (!std::isfinite(residual)) {
            return FitStatus::numerical_range;
        }
        errors.add(residual);
    }
    result = errors.scale * std::sqrt(errors.squares.value() / static_cast<double>(validation.rows));
    if (!std::isfinite(result) || (result == 0.0 && errors.scale != 0.0)) {
        return FitStatus::numerical_range;
    }
    return FitStatus::ok;
}

FitStatus compare(
    Sample fitting, Sample validation, std::size_t columns, const double* alphas, std::size_t count,
    double magnitude, double* result, Checkpoint& checkpoint
) {
    RidgeMeans means{};
    auto status = prepare_ridge(fitting.design, fitting.outcome, fitting.rows, columns, means, checkpoint);
    if (status != FitStatus::ok) {
        return status;
    }
    status = validate_sample(validation, columns, checkpoint);
    if (status != FitStatus::ok) {
        return status;
    }
    RidgeWorkspace workspace(columns);
    std::vector<double> coefficients(columns + 1, 0.0);
    std::size_t best = 0;
    for (std::size_t index = 0; index < count; ++index) {
        if (index > 0) {
            std::fill(workspace.triangle.begin(), workspace.triangle.end(), 0.0);
            std::fill(coefficients.begin(), coefficients.end(), 0.0);
        }
        status = fit_prepared_ridge(fitting.design, fitting.outcome, fitting.rows, columns, means,
                                    alphas[index], workspace, coefficients, checkpoint);
        if (status != FitStatus::ok) {
            return status;
        }
        auto& loss = result[index + 1];
        status = validation_loss(validation, columns, coefficients, magnitude, loss, checkpoint);
        if (status != FitStatus::ok) {
            return status;
        }
        if (loss < result[best + 1] || (loss == result[best + 1] && alphas[index] > alphas[best])) {
            best = index;
        }
    }
    result[0] = static_cast<double>(best);
    return checkpoint.poll() ? FitStatus::ok : FitStatus::interrupted;
}

bool matches(PyObject* design, PyObject* outcome, std::size_t rows, std::size_t columns) {
    return PyBytes_GET_SIZE(design) == static_cast<Py_ssize_t>(rows * columns * sizeof(double))
        && PyBytes_GET_SIZE(outcome) == static_cast<Py_ssize_t>(rows * sizeof(double));
}

PyObject* select(PyObject*, PyObject* args) {
    PyObject* fit_x;
    PyObject* fit_y;
    PyObject* validation_x;
    PyObject* validation_y;
    PyObject* grid;
    PyObject* callback = Py_None;
    Py_ssize_t fit_rows_arg, validation_rows_arg, columns_arg;
    double magnitude;
    if (!PyArg_ParseTuple(args, "O!O!O!O!nnnO!d|O:select_ridge",
                          &PyBytes_Type, &fit_x, &PyBytes_Type, &fit_y,
                          &PyBytes_Type, &validation_x, &PyBytes_Type, &validation_y,
                          &fit_rows_arg, &validation_rows_arg, &columns_arg,
                          &PyBytes_Type, &grid, &magnitude, &callback)) {
        return nullptr;
    }
    if (fit_rows_arg < 2 || validation_rows_arg < 1 || columns_arg < 1 || !std::isfinite(magnitude) || magnitude <= 0.0) {
        PyErr_SetString(PyExc_ValueError, "RIDGE_SELECTION_INVALID_DATA: the selection dimensions and outcome scale are invalid");
        return nullptr;
    }
    const auto bytes = static_cast<std::size_t>(PyBytes_GET_SIZE(grid));
    const auto count = bytes / sizeof(double);
    if (bytes % sizeof(double) != 0 || count < 2 || count > max_candidates) {
        PyErr_SetString(PyExc_ValueError, "RIDGE_SELECTION_INVALID_GRID: provide 2 to 16 distinct finite positive alphas");
        return nullptr;
    }
    std::array<double, max_candidates> alphas;
    for (std::size_t i = 0; i < count; ++i) {
        const double alpha = at(PyBytes_AS_STRING(grid), i);
        if (!std::isfinite(alpha) || alpha <= 0.0
            || std::find(alphas.begin(), alphas.begin() + i, alpha) != alphas.begin() + i) {
            PyErr_SetString(PyExc_ValueError, "RIDGE_SELECTION_INVALID_GRID: provide 2 to 16 distinct finite positive alphas");
            return nullptr;
        }
        alphas[i] = alpha;
    }
    const auto fit_rows = static_cast<std::size_t>(fit_rows_arg);
    const auto validation_rows = static_cast<std::size_t>(validation_rows_arg);
    const auto columns = static_cast<std::size_t>(columns_arg);
    if (fit_rows > max_rows || validation_rows > max_rows - fit_rows || columns > max_features
        || fit_rows + validation_rows > max_values / (columns + 1)) {
        PyErr_SetString(PyExc_ValueError, "RIDGE_SELECTION_WORK_LIMIT: the selection shape exceeds the Ridge size limit");
        return nullptr;
    }
    const std::size_t budget = work_budget / count;
    const std::size_t fit_cost = columns * columns;
    if (fit_rows > budget / fit_cost || validation_rows > (budget - fit_rows * fit_cost) / columns) {
        PyErr_SetString(PyExc_ValueError, "RIDGE_SELECTION_WORK_LIMIT: the candidate fits and validation exceed the work budget");
        return nullptr;
    }
    if (!matches(fit_x, fit_y, fit_rows, columns) || !matches(validation_x, validation_y, validation_rows, columns)) {
        PyErr_SetString(PyExc_ValueError, "RIDGE_SELECTION_INVALID_DATA: native buffers do not match their declared shapes");
        return nullptr;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "Ridge selection checkpoint must be callable");
        return nullptr;
    }
    try {
        const Sample fitting{PyBytes_AS_STRING(fit_x), PyBytes_AS_STRING(fit_y), fit_rows};
        const Sample validation{PyBytes_AS_STRING(validation_x), PyBytes_AS_STRING(validation_y), validation_rows};
        std::array<double, max_candidates + 1> result{};
        FitStatus status;
        {
            Checkpoint checkpoint(callback);
            status = compare(fitting, validation, columns, alphas.data(), count, magnitude, result.data(), checkpoint);
        }
        if (status == FitStatus::ok) {
            return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(result.data()), (count + 1) * sizeof(double));
        }
        if (status == FitStatus::nonfinite_input) {
            PyErr_SetString(PyExc_ValueError, "RIDGE_SELECTION_INVALID_DATA: fitting and validation inputs must be finite");
        } else if (status == FitStatus::numerical_range) {
            PyErr_SetString(PyExc_ValueError, "RIDGE_SELECTION_NUMERICAL_RANGE: a candidate or validation loss exceeded binary64 range");
        }
        return nullptr;
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

}
