// Dense binary64 Ridge using Givens QR and an unpenalized intercept.
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <cmath>
#include <cstddef>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

namespace {

constexpr std::size_t max_rows = 1'000'000;
constexpr std::size_t max_features = 512;
constexpr std::size_t max_values = 4'000'000;
constexpr std::size_t work_budget = 100'000'000;
constexpr double max_design_to_penalty = 1e10;
static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559);

enum class FitStatus { ok, nonfinite_input, numerical_range, interrupted };

struct Sum {
    double total = 0.0;
    double correction = 0.0;

    void add(double term) {
        const double next = total + term;
        if (std::abs(total) >= std::abs(term)) {
            correction += (total - next) + term;
        } else {
            correction += (term - next) + total;
        }
        total = next;
    }

    double value() const { return total + correction; }
};

// The extension accepts immutable bytes so their storage can be read without the GIL.
// Loading through memcpy also works when a byte buffer is not double-aligned.
double at(const char* data, std::size_t index) {
    double value;
    std::memcpy(&value, data + index * sizeof(double), sizeof(double));
    return value;
}

class Checkpoint {
public:
    explicit Checkpoint(PyObject* callback)
        : state_(PyEval_SaveThread()), callback_(callback) {}
    ~Checkpoint() { PyEval_RestoreThread(state_); }

    Checkpoint(const Checkpoint&) = delete;
    Checkpoint& operator=(const Checkpoint&) = delete;

    bool poll() {
        PyEval_RestoreThread(state_);
        bool keep_running = PyErr_CheckSignals() == 0;
        if (keep_running && callback_ != Py_None) {
            PyObject* result = PyObject_CallNoArgs(callback_);
            keep_running = result != nullptr;
            Py_XDECREF(result);
        }
        state_ = PyEval_SaveThread();
        return keep_running;
    }

private:
    PyThreadState* state_;
    PyObject* callback_;
};

bool rotate(double& top, double& bottom, double cosine, double sine) {
    const double previous_top = top;
    top = cosine * previous_top + sine * bottom;
    bottom = cosine * bottom - sine * previous_top;
    return std::isfinite(top) && std::isfinite(bottom);
}

struct RidgeMeans {
    std::vector<double> predictors;
    double response;
};

struct RidgeWorkspace {
    std::vector<double> triangle;
    std::vector<double> centered;

    explicit RidgeWorkspace(std::size_t columns) : triangle(columns * columns, 0.0), centered(columns) {}
};

FitStatus prepare_ridge(
    const char* design, const char* target, std::size_t rows, std::size_t columns,
    RidgeMeans& means, Checkpoint& checkpoint
) {
    std::vector<Sum> column_means(columns);
    Sum target_mean;
    const double count = static_cast<double>(rows);
    // Division before accumulation avoids overflow from summing an entire column.
    for (std::size_t row = 0; row < rows; ++row) {
        if (row % 4096 == 0 && !checkpoint.poll()) {
            return FitStatus::interrupted;
        }
        const double response = at(target, row);
        if (!std::isfinite(response)) {
            return FitStatus::nonfinite_input;
        }
        target_mean.add(response / count);
        for (std::size_t col = 0; col < columns; ++col) {
            const double value = at(design, row * columns + col);
            if (!std::isfinite(value)) {
                return FitStatus::nonfinite_input;
            }
            column_means[col].add(value / count);
        }
    }

    means.response = target_mean.value();
    means.predictors.resize(columns);
    for (std::size_t col = 0; col < columns; ++col) {
        means.predictors[col] = column_means[col].value();
    }
    return FitStatus::ok;
}

FitStatus fit_prepared_ridge(
    const char* design, const char* target, std::size_t rows, std::size_t columns,
    const RidgeMeans& prepared, double alpha, RidgeWorkspace& workspace,
    std::vector<double>& result, Checkpoint& checkpoint
) {
    const double count = static_cast<double>(rows);
    const auto& means = prepared.predictors;
    const double response_mean = prepared.response;
    const double diagonal = std::sqrt(alpha);
    // sqrt(n * p) * max(abs(centered X)) bounds the spectral norm of X.
    const double max_element = diagonal * (max_design_to_penalty / std::sqrt(count * columns));
    auto& triangle = workspace.triangle;
    auto& centered = workspace.centered;
    for (std::size_t col = 0; col < columns; ++col) {
        triangle[col * columns + col] = diagonal;
    }

    // R starts as the penalty rows sqrt(alpha) * I. Rotations fold each
    // centered observation into R and Q'y without materializing the augmented matrix.
    const auto poll_rows = std::min<std::size_t>(4096, 1'048'576 / (columns * columns));
    for (std::size_t row = 0; row < rows; ++row) {
        if (row % poll_rows == 0 && !checkpoint.poll()) {
            return FitStatus::interrupted;
        }
        double centered_target = at(target, row) - response_mean;
        if (!std::isfinite(centered_target)) {
            return FitStatus::numerical_range;
        }
        for (std::size_t col = 0; col < columns; ++col) {
            centered[col] = at(design, row * columns + col) - means[col];
            if (!std::isfinite(centered[col]) || std::abs(centered[col]) > max_element) {
                return FitStatus::numerical_range;
            }
        }
        for (std::size_t col = 0; col < columns; ++col) {
            if (centered[col] == 0.0) {
                continue;
            }
            double* upper = triangle.data() + col * columns;
            const double norm = std::hypot(upper[col], centered[col]);
            if (!std::isfinite(norm)) {
                return FitStatus::numerical_range;
            }
            const double cosine = upper[col] / norm;
            const double sine = centered[col] / norm;
            upper[col] = norm;
            for (std::size_t tail = col + 1; tail < columns; ++tail) {
                if (!rotate(upper[tail], centered[tail], cosine, sine)) {
                    return FitStatus::numerical_range;
                }
            }
            if (!rotate(result[col], centered_target, cosine, sine)) {
                return FitStatus::numerical_range;
            }
        }
    }

    // Back substitution in Q'y. Every diagonal started strictly positive.
    for (std::size_t end = columns; end > 0; --end) {
        const std::size_t col = end - 1;
        const double* upper = triangle.data() + col * columns;
        for (std::size_t tail = col + 1; tail < columns; ++tail) {
            result[col] -= upper[tail] * result[tail];
        }
        result[col] /= upper[col];
        if (!std::isfinite(result[col])) {
            return FitStatus::numerical_range;
        }
    }

    Sum intercept;
    intercept.add(response_mean);
    for (std::size_t col = 0; col < columns; ++col) {
        intercept.add(-means[col] * result[col]);
    }
    result[columns] = intercept.value();
    if (!std::isfinite(result[columns])) {
        return FitStatus::numerical_range;
    }
    return checkpoint.poll() ? FitStatus::ok : FitStatus::interrupted;
}

FitStatus fit_ridge(
    const char* design, const char* target, std::size_t rows, std::size_t columns,
    double alpha, std::vector<double>& result, Checkpoint& checkpoint
) {
    RidgeMeans prepared{};
    const auto status = prepare_ridge(design, target, rows, columns, prepared, checkpoint);
    if (status != FitStatus::ok) {
        return status;
    }
    RidgeWorkspace workspace(columns);
    return fit_prepared_ridge(design, target, rows, columns, prepared, alpha, workspace, result, checkpoint);
}

PyObject* fit(PyObject*, PyObject* args) {
    PyObject* design;
    PyObject* target;
    PyObject* callback = Py_None;
    Py_ssize_t rows_arg, columns_arg;
    double alpha;
    if (!PyArg_ParseTuple(args, "O!O!nnd|O:fit", &PyBytes_Type, &design, &PyBytes_Type, &target,
                          &rows_arg, &columns_arg, &alpha, &callback)) {
        return nullptr;
    }
    if (rows_arg <= 0 || columns_arg <= 0) {
        PyErr_SetString(PyExc_ValueError, "RIDGE_INVALID_DATA: native dimensions must be positive");
        return nullptr;
    }
    const auto rows = static_cast<std::size_t>(rows_arg);
    const auto columns = static_cast<std::size_t>(columns_arg);
    if (rows > max_rows || columns > max_features || rows > max_values / (columns + 1)
        || rows > work_budget / columns / columns) {
        PyErr_SetString(PyExc_ValueError, "RIDGE_WORK_LIMIT: native training shape exceeds the work budget");
        return nullptr;
    }
    if (PyBytes_GET_SIZE(design) != static_cast<Py_ssize_t>(rows * columns * sizeof(double))
        || PyBytes_GET_SIZE(target) != static_cast<Py_ssize_t>(rows * sizeof(double))) {
        PyErr_SetString(PyExc_ValueError, "RIDGE_INVALID_DATA: native buffers do not match the declared shape");
        return nullptr;
    }
    if (!std::isfinite(alpha) || alpha <= 0.0) {
        PyErr_SetString(PyExc_ValueError, "RIDGE_INVALID_ALPHA: alpha must be finite and positive");
        return nullptr;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "Ridge checkpoint must be callable");
        return nullptr;
    }
    try {
        const char* x = PyBytes_AS_STRING(design);
        const char* y = PyBytes_AS_STRING(target);
        std::vector<double> result(columns + 1, 0.0);
        FitStatus status;
        {
            Checkpoint checkpoint(callback);
            status = fit_ridge(x, y, rows, columns, alpha, result, checkpoint);
        }
        if (status == FitStatus::ok) {
            return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(result.data()),
                                             (columns_arg + 1) * sizeof(double));
        }
        if (status == FitStatus::nonfinite_input) {
            PyErr_SetString(PyExc_ValueError, "RIDGE_INVALID_DATA: native inputs must be finite");
        } else if (status == FitStatus::numerical_range) {
            PyErr_SetString(PyExc_ValueError, "RIDGE_NUMERICAL_RANGE: native design or result is outside the numeric range");
        }
        return nullptr;
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

#include "elastic_net.hpp"
#include "ridge_selection.hpp"
#include "logistic.hpp"
#include "cart.hpp"
#include "cart_regression.hpp"
#include "random_forest.hpp"
#include "random_forest_classification.hpp"

PyMethodDef methods[] = {
    {"fit", fit, METH_VARARGS, "Fit dense Ridge and return native binary64 slopes followed by the intercept."},
    {"select_ridge", ridge_selection::select, METH_VARARGS, "Compare Ridge alphas on a separate validation block."},
    {"fit_elastic_net", elastic_net::fit, METH_VARARGS, "Fit dense Elastic Net and return slopes, intercept, and convergence evidence."},
    {"fit_logistic", logistic::fit, METH_VARARGS, "Fit binary L2 Logistic and return slopes, intercept, and convergence evidence."},
    {"fit_cart", cart::fit, METH_VARARGS, "Fit CART and return its preorder node table."},
    {"predict_cart", cart::predict, METH_VARARGS, "Score probabilities with a validated CART node table."},
    {"fit_cart_regression", cart_regression::fit, METH_VARARGS, "Fit squared-error CART and return its preorder node table."},
    {"predict_cart_regression", cart_regression::predict, METH_VARARGS, "Score a validated CART regression tree."},
    {"fit_random_forest_regression", random_forest::fit, METH_VARARGS, "Fit a bounded bootstrap regression forest."},
    {"predict_random_forest_regression", random_forest::predict, METH_VARARGS, "Score a validated regression forest."},
    {"fit_random_forest_classification", random_forest_classification::fit, METH_VARARGS, "Fit a bounded bootstrap binary forest."},
    {"predict_random_forest_classification", random_forest_classification::predict, METH_VARARGS, "Score binary probabilities with a validated forest."},
    {nullptr, nullptr, 0, nullptr},
};
PyModuleDef module_def = {PyModuleDef_HEAD_INIT, "_ridge", nullptr, -1, methods,
                          nullptr, nullptr, nullptr, nullptr};

}  // namespace

PyMODINIT_FUNC PyInit__ridge() {
    PyObject* module = PyModule_Create(&module_def);
    if (module && PyModule_AddIntConstant(module, "ABI_VERSION", 1) < 0) {
        Py_DECREF(module);
        return nullptr;
    }
    return module;
}
