// The Breslow partial-likelihood sweep of statsmodels PHReg, without a Python
// step per failure time. Each sum keeps the order NumPy reduces in (pairwise
// along a contiguous 1-D buffer, row after row along axis 0, fused in einsum), and
// the build forbids contracting anything else, so results equal the reference bit for bit.
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <cmath>
#include <cstdint>
#include <new>
#include <vector>

namespace {
struct Index { const int32_t* rows; const int64_t* offsets; };

double pairwise(const double* a, Py_ssize_t n) {
    if (n < 8) {
        double sum = -0.0;
        for (Py_ssize_t i = 0; i < n; ++i) sum += a[i];
        return sum;
    }
    if (n <= 128) {
        double r[8];
        for (int j = 0; j < 8; ++j) r[j] = a[j];
        Py_ssize_t i = 8;
        for (; i < n - (n % 8); i += 8)
            for (int j = 0; j < 8; ++j) r[j] += a[i + j];
        double sum = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]));
        for (; i < n; ++i) sum += a[i];
        return sum;
    }
    Py_ssize_t half = n / 2;
    half -= half % 8;
    return pairwise(a, half) + pairwise(a + half, n - half);
}

// a.sum() on a 1-D buffer.
double reduce(const std::vector<double>& a) {
    return a.empty() ? 0.0 : pairwise(a.data(), static_cast<Py_ssize_t>(a.size()));
}

// m.sum(0) on (rows, p): one column reduces like a 1-D buffer, more columns row after row.
void reduce_rows(const std::vector<double>& m, Py_ssize_t rows, Py_ssize_t p, double* out) {
    if (p == 1) { out[0] = reduce(m); return; }
    for (Py_ssize_t j = 0; j < p; ++j) out[j] = m[j];
    for (Py_ssize_t i = 1; i < rows; ++i)
        for (Py_ssize_t j = 0; j < p; ++j) out[j] += m[i * p + j];
}

struct Sweep {
    const double* e; const double* x; Py_ssize_t p;
    std::vector<double> values, scaled, column;
    double e_sum(const int32_t* ix, Py_ssize_t n) {
        values.resize(n);
        for (Py_ssize_t i = 0; i < n; ++i) values[i] = e[ix[i]];
        return reduce(values);
    }
    void x_sum(const int32_t* ix, Py_ssize_t n, double* out) {
        scaled.resize(n * p);
        for (Py_ssize_t i = 0; i < n; ++i)
            for (Py_ssize_t j = 0; j < p; ++j) scaled[i * p + j] = e[ix[i]] * x[ix[i] * p + j];
        reduce_rows(scaled, n, p, out);
    }
    void xx_sum(const int32_t* ix, Py_ssize_t n, double* out) {
        for (Py_ssize_t j = 0; j < p; ++j)
            for (Py_ssize_t k = 0; k < p; ++k) {
                double accumulated = 0.0;
                for (Py_ssize_t i = 0; i < n; ++i) {
                    const double* row = x + ix[i] * p;
                    // np.einsum's three-operand loop fuses this addition on this platform.
                    accumulated = std::fma(row[j] * row[k], e[ix[i]], accumulated);
                }
                out[j * p + k] = accumulated;
            }
    }
};

struct Inputs {
    Py_buffer linpred{}, e{}, x{}, fail{}, fail_off{}, enter{}, enter_off{}, leave{}, leave_off{};
    Py_ssize_t p = 0, times = 0;
    bool held[9] = {};
    Py_buffer* all() { return &linpred; }
    ~Inputs() { for (int i = 0; i < 9; ++i) if (held[i]) PyBuffer_Release(all() + i); }
};

bool read_inputs(PyObject* args, Inputs& in) {
    PyObject* objects[9];
    if (!PyArg_ParseTuple(args, "OOOnOOOOOO", &objects[0], &objects[1], &objects[2], &in.p,
                          &objects[3], &objects[4], &objects[5], &objects[6], &objects[7], &objects[8])) return false;
    const Py_ssize_t items[9] = {8, 8, 8, 4, 8, 4, 8, 4, 8};
    for (int i = 0; i < 9; ++i) {
        if (PyObject_GetBuffer(objects[i], in.all() + i, PyBUF_C_CONTIGUOUS) < 0) return false;
        in.held[i] = true;
        if (in.all()[i].itemsize != items[i] && in.all()[i].len % items[i] != 0) {
            PyErr_SetString(PyExc_ValueError, "Cox sweep buffer has the wrong element size");
            return false;
        }
    }
    in.times = in.fail_off.len / 8 - 1;
    const Py_ssize_t rows = in.e.len / 8;
    if (in.p < 1 || in.times < 0 || in.linpred.len != in.e.len || in.x.len != rows * in.p * 8
        || in.enter_off.len != in.fail_off.len || in.leave_off.len != in.fail_off.len) {
        PyErr_SetString(PyExc_ValueError, "Cox sweep buffers disagree on rows, columns or failure times");
        return false;
    }
    const struct { const Py_buffer* idx; const Py_buffer* off; } lists[3] =
        {{&in.fail, &in.fail_off}, {&in.enter, &in.enter_off}, {&in.leave, &in.leave_off}};
    for (const auto& list : lists) {
        const auto* rows_at = static_cast<const int32_t*>(list.idx->buf);
        const auto* off = static_cast<const int64_t*>(list.off->buf);
        const Py_ssize_t count = list.idx->len / 4;
        if (off[0] != 0 || off[in.times] != count) {
            PyErr_SetString(PyExc_ValueError, "Cox sweep offsets do not cover their rows");
            return false;
        }
        for (Py_ssize_t t = 0; t < in.times; ++t)
            if (off[t + 1] < off[t]) { PyErr_SetString(PyExc_ValueError, "Cox sweep offsets decrease"); return false; }
        for (Py_ssize_t i = 0; i < count; ++i)
            if (rows_at[i] < 0 || rows_at[i] >= rows) { PyErr_SetString(PyExc_ValueError, "Cox sweep row is out of range"); return false; }
    }
    return true;
}

template <class T> const T* at(const Py_buffer& b) { return static_cast<const T*>(b.buf); }

PyObject* loglike(PyObject*, PyObject* args) {
    Inputs in;
    if (!read_inputs(args, in)) return nullptr;
    double like = 0.0;
    try {
        Py_BEGIN_ALLOW_THREADS
        Sweep s{at<double>(in.e), at<double>(in.x), in.p, {}, {}, {}};
        const auto* linpred = at<double>(in.linpred);
        double xp0 = 0.0;
        std::vector<double> terms;
        for (Py_ssize_t t = in.times - 1; t >= 0; --t) {
            const int64_t a = at<int64_t>(in.enter_off)[t], b = at<int64_t>(in.enter_off)[t + 1];
            xp0 += s.e_sum(at<int32_t>(in.enter) + a, b - a);
            const int64_t f = at<int64_t>(in.fail_off)[t], g = at<int64_t>(in.fail_off)[t + 1];
            const double log_xp0 = std::log(xp0);
            terms.resize(g - f);
            for (int64_t i = f; i < g; ++i) terms[i - f] = linpred[at<int32_t>(in.fail)[i]] - log_xp0;
            like += reduce(terms);
            const int64_t c = at<int64_t>(in.leave_off)[t], d = at<int64_t>(in.leave_off)[t + 1];
            xp0 -= s.e_sum(at<int32_t>(in.leave) + c, d - c);
        }
        Py_END_ALLOW_THREADS
    } catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
    return PyFloat_FromDouble(like);
}

PyObject* gradient(PyObject*, PyObject* args) {
    Inputs in;
    if (!read_inputs(args, in)) return nullptr;
    PyObject* output = PyBytes_FromStringAndSize(nullptr, in.p * 8);
    if (!output) return nullptr;
    auto* grad = reinterpret_cast<double*>(PyBytes_AS_STRING(output));
    try {
        Py_BEGIN_ALLOW_THREADS
        const Py_ssize_t p = in.p;
        Sweep s{at<double>(in.e), at<double>(in.x), p, {}, {}, {}};
        double xp0 = 0.0;
        std::vector<double> xp1(p, 0.0), block(p), mean(p), centred;
        for (Py_ssize_t j = 0; j < p; ++j) grad[j] = 0.0;
        for (Py_ssize_t t = in.times - 1; t >= 0; --t) {
            const int64_t a = at<int64_t>(in.enter_off)[t], b = at<int64_t>(in.enter_off)[t + 1];
            if (b > a) {
                xp0 += s.e_sum(at<int32_t>(in.enter) + a, b - a);
                s.x_sum(at<int32_t>(in.enter) + a, b - a, block.data());
                for (Py_ssize_t j = 0; j < p; ++j) xp1[j] += block[j];
            }
            const int64_t f = at<int64_t>(in.fail_off)[t], g = at<int64_t>(in.fail_off)[t + 1];
            for (Py_ssize_t j = 0; j < p; ++j) mean[j] = xp1[j] / xp0;
            centred.resize((g - f) * p);
            for (int64_t i = f; i < g; ++i) {
                const double* row = s.x + at<int32_t>(in.fail)[i] * p;
                for (Py_ssize_t j = 0; j < p; ++j) centred[(i - f) * p + j] = row[j] - mean[j];
            }
            reduce_rows(centred, g - f, p, block.data());
            for (Py_ssize_t j = 0; j < p; ++j) grad[j] += block[j];
            const int64_t c = at<int64_t>(in.leave_off)[t], d = at<int64_t>(in.leave_off)[t + 1];
            if (d > c) {
                xp0 -= s.e_sum(at<int32_t>(in.leave) + c, d - c);
                s.x_sum(at<int32_t>(in.leave) + c, d - c, block.data());
                for (Py_ssize_t j = 0; j < p; ++j) xp1[j] -= block[j];
            }
        }
        Py_END_ALLOW_THREADS
    } catch (const std::bad_alloc&) { Py_DECREF(output); return PyErr_NoMemory(); }
    return output;
}

PyObject* hessian(PyObject*, PyObject* args) {
    Inputs in;
    if (!read_inputs(args, in)) return nullptr;
    PyObject* output = PyBytes_FromStringAndSize(nullptr, in.p * in.p * 8);
    if (!output) return nullptr;
    auto* hess = reinterpret_cast<double*>(PyBytes_AS_STRING(output));
    try {
        Py_BEGIN_ALLOW_THREADS
        const Py_ssize_t p = in.p;
        Sweep s{at<double>(in.e), at<double>(in.x), p, {}, {}, {}};
        double xp0 = 0.0;
        std::vector<double> xp1(p, 0.0), xp2(p * p, 0.0), block(p), square(p * p);
        for (Py_ssize_t j = 0; j < p * p; ++j) hess[j] = 0.0;
        for (Py_ssize_t t = in.times - 1; t >= 0; --t) {
            const int64_t a = at<int64_t>(in.enter_off)[t], b = at<int64_t>(in.enter_off)[t + 1];
            if (b > a) {
                xp0 += s.e_sum(at<int32_t>(in.enter) + a, b - a);
                s.x_sum(at<int32_t>(in.enter) + a, b - a, block.data());
                for (Py_ssize_t j = 0; j < p; ++j) xp1[j] += block[j];
                s.xx_sum(at<int32_t>(in.enter) + a, b - a, square.data());
                for (Py_ssize_t j = 0; j < p * p; ++j) xp2[j] += square[j];
            }
            const double m = static_cast<double>(at<int64_t>(in.fail_off)[t + 1] - at<int64_t>(in.fail_off)[t]);
            const double xp0_squared = xp0 * xp0;
            for (Py_ssize_t j = 0; j < p; ++j)
                for (Py_ssize_t k = 0; k < p; ++k) {
                    const double first = xp2[j * p + k] / xp0;
                    const double outer = xp1[j] * xp1[k];
                    const double second = outer / xp0_squared;
                    const double difference = first - second;
                    const double term = m * difference;
                    hess[j * p + k] += term;
                }
            const int64_t c = at<int64_t>(in.leave_off)[t], d = at<int64_t>(in.leave_off)[t + 1];
            if (d > c) {
                xp0 -= s.e_sum(at<int32_t>(in.leave) + c, d - c);
                s.x_sum(at<int32_t>(in.leave) + c, d - c, block.data());
                for (Py_ssize_t j = 0; j < p; ++j) xp1[j] -= block[j];
                s.xx_sum(at<int32_t>(in.leave) + c, d - c, square.data());
                for (Py_ssize_t j = 0; j < p * p; ++j) xp2[j] -= square[j];
            }
        }
        Py_END_ALLOW_THREADS
    } catch (const std::bad_alloc&) { Py_DECREF(output); return PyErr_NoMemory(); }
    return output;
}

PyMethodDef methods[] = {
    {"loglike", loglike, METH_VARARGS, "Breslow log partial likelihood."},
    {"gradient", gradient, METH_VARARGS, "Breslow gradient as binary64 bytes."},
    {"hessian", hessian, METH_VARARGS, "Breslow Hessian before negation, as binary64 bytes in C order."},
    {nullptr, nullptr, 0, nullptr},
};
PyModuleDef definition = {PyModuleDef_HEAD_INIT, "_cox_breslow", nullptr, -1, methods, nullptr, nullptr, nullptr, nullptr};
}  // namespace

PyMODINIT_FUNC PyInit__cox_breslow() {
    PyObject* module = PyModule_Create(&definition);
    if (module && PyModule_AddIntConstant(module, "ABI_VERSION", 1) < 0) { Py_DECREF(module); return nullptr; }
    return module;
}
