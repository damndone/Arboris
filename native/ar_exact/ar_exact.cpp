// Exact dyadic HC0 AR sufficient statistics and residual covariance.
// No floating-point arithmetic, observation-sized PyObject storage, or NumPy ABI.
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <new>
#include <thread>
#include <utility>
#include <vector>

#ifndef AR_EXACT_SOURCE_SHA256
#define AR_EXACT_SOURCE_SHA256 "unregistered"
#endif

namespace {
struct PythonError {};
struct Object {
    PyObject* p = nullptr;
    Object() = default;
    explicit Object(PyObject* value) : p(value) { if (!p) throw PythonError{}; }
    Object(const Object& other) : p(other.p) { Py_XINCREF(p); }
    Object(Object&& other) noexcept : p(std::exchange(other.p, nullptr)) {}
    Object& operator=(Object other) noexcept { std::swap(p, other.p); return *this; }
    ~Object() { Py_XDECREF(p); }
    PyObject* release() { return std::exchange(p, nullptr); }
};
Object integer(long value) { return Object(PyLong_FromLong(value)); }
Object plus(const Object& a, const Object& b) { return Object(PyNumber_Add(a.p, b.p)); }
Object times(const Object& a, const Object& b) { return Object(PyNumber_Multiply(a.p, b.p)); }
Object minus(const Object& a, const Object& b) { return Object(PyNumber_Subtract(a.p, b.p)); }
void invalid(const char* message) { PyErr_SetString(PyExc_ValueError, message); throw PythonError{}; }
using Vector = std::vector<Object>;

void checkpoint(PyObject* check_cancel) {
    // PyLong operations need the GIL. Yield only between bounded row blocks,
    // then run the execution owner's check under the GIL. Preserve its error.
    auto* state = PyEval_SaveThread();
    std::this_thread::yield();
    PyEval_RestoreThread(state);
    if (PyErr_CheckSignals() < 0) throw PythonError{};
    if (check_cancel != Py_None) { Object checked(PyObject_CallNoArgs(check_cancel)); }
}
void validate_callback(PyObject* check_cancel) {
    if (check_cancel != Py_None && !PyCallable_Check(check_cancel)) {
        PyErr_SetString(PyExc_TypeError, "native_ar_check_cancel_must_be_callable");
        throw PythonError{};
    }
}

struct Buffer {
    Py_buffer b{};
    explicit Buffer(PyObject* obj) {
        if (PyObject_GetBuffer(obj, &b, PyBUF_FORMAT | PyBUF_STRIDES) < 0) throw PythonError{};
        if (b.itemsize != 8 || !b.format ||
            (std::strcmp(b.format, "d") && std::strcmp(b.format, "=d") && std::strcmp(b.format, "@d"))) {
            PyBuffer_Release(&b);
            invalid("native_ar_requires_native_binary64_buffer");
        }
        if (b.suboffsets) {
            PyBuffer_Release(&b);
            invalid("native_ar_indirect_binary64_buffer_unsupported");
        }
    }
    Buffer(const Buffer&) = delete;
    ~Buffer() { PyBuffer_Release(&b); }
    uint64_t bits(Py_ssize_t row, Py_ssize_t col = 0) const {
        uint64_t result;
        const auto* ptr = static_cast<const char*>(b.buf) + row*b.strides[0];
        if (b.ndim == 2) ptr += col*b.strides[1];
        std::memcpy(&result, ptr, sizeof(result));
        return result;
    }
};

struct Dyadic { uint64_t mantissa; int exponent; bool negative; };
Dyadic decode(uint64_t bits) {
    const unsigned exp = static_cast<unsigned>((bits >> 52) & 0x7ff);
    if (exp == 0x7ff) invalid("nonfinite_original_binary64");
    uint64_t mantissa = bits & ((uint64_t{1} << 52)-1);
    int exponent = -1074;
    if (exp) { mantissa |= uint64_t{1} << 52; exponent = static_cast<int>(exp)-1075; }
    if (mantissa) {
        const int zeros = __builtin_ctzll(mantissa);
        mantissa >>= zeros;
        exponent += zeros;
    } else exponent = 0;
    return {mantissa, exponent, bool(bits >> 63)};
}
Object scaled_integer(uint64_t bits, int scale) {
    const auto d = decode(bits);
    if (!d.mantissa) return integer(0); // Includes both signed zeros.
    const int shift = d.exponent + scale;
    if (shift < 0) invalid("native_ar_inconsistent_dyadic_scale");
    Object result(PyLong_FromUnsignedLongLong(d.mantissa));
    if (shift) { auto amount = integer(shift); result = Object(PyNumber_Lshift(result.p, amount.p)); }
    if (d.negative) result = Object(PyNumber_Negative(result.p));
    return result;
}

struct Inputs {
    Buffer y, x, z, w;
    Py_ssize_t n;
    int p, q, nw;
    Inputs(PyObject* yy, PyObject* xx, PyObject* zz, PyObject* ww) : y(yy), x(xx), z(zz), w(ww) {
        if ((y.b.ndim != 1 && y.b.ndim != 2) || (y.b.ndim == 2 && y.b.shape[1] != 1) ||
            x.b.ndim != 2 || x.b.shape[1] != 1 || z.b.ndim != 2 || w.b.ndim != 2)
            invalid("native_ar_input_shape");
        n = y.b.shape[0];
        if (n <= 0 || x.b.shape[0] != n || z.b.shape[0] != n || w.b.shape[0] != n)
            invalid("native_ar_input_shape");
        if (z.b.shape[1] < 1 || z.b.shape[1] > 4 || w.b.shape[1] > 12-z.b.shape[1])
            invalid("outside_exact_certification_envelope");
        q = static_cast<int>(z.b.shape[1]); nw = static_cast<int>(w.b.shape[1]); p = q+nw;
    }
    uint64_t bits(Py_ssize_t row, int col) const {
        if (col == 0) return y.bits(row);
        if (col == 1) return x.bits(row);
        if (col-2 < nw) return w.bits(row, col-2);
        return z.bits(row, col-2-nw);
    }
    int scale(PyObject* check_cancel) const {
        int result = 0;
        for (Py_ssize_t row = 0; row < n; ++row) {
            if ((row & 255) == 0) checkpoint(check_cancel);
            for (int col = 0; col < p+2; ++col)
                result = std::max(result, -decode(bits(row, col)).exponent);
        }
        return result;
    }
    Vector row(Py_ssize_t i, int scale) const {
        Vector values; values.reserve(p+2);
        for (int col = 0; col < p+2; ++col) values.emplace_back(scaled_integer(bits(i, col), scale));
        return values;
    }
};

Object list(const Vector& values) {
    Object result(PyList_New(static_cast<Py_ssize_t>(values.size())));
    for (size_t i = 0; i < values.size(); ++i) {
        Py_INCREF(values[i].p); PyList_SET_ITEM(result.p, i, values[i].p);
    }
    return result;
}
Vector integers(PyObject* sequence, int size) {
    Object fast(PySequence_Fast(sequence, "native_ar_integer_vector_required"));
    if (PySequence_Fast_GET_SIZE(fast.p) != size) invalid("native_ar_integer_vector_shape");
    Vector result; result.reserve(size);
    for (int i = 0; i < size; ++i) {
        auto* item = PySequence_Fast_GET_ITEM(fast.p, i);
        if (!PyLong_CheckExact(item)) invalid("native_ar_exact_integer_required");
        Py_INCREF(item); result.emplace_back(item);
    }
    return result;
}
Object dot(const Vector& a, const Vector& b, int offset = 0) {
    auto result = integer(0);
    for (size_t j = 0; j < a.size(); ++j) result = plus(result, times(a[j], b[j+offset]));
    return result;
}

PyObject* sufficient_statistics(PyObject*, PyObject* args) {
    PyObject *y, *x, *z, *w, *check_cancel = Py_None;
    if (!PyArg_ParseTuple(args, "OOOO|O", &y, &x, &z, &w, &check_cancel)) return nullptr;
    try {
        validate_callback(check_cancel);
        Inputs input(y, x, z, w);
        const int scale = input.scale(check_cancel);
        Vector gram(input.p*input.p, integer(0)), cy(input.p, integer(0)), cx(input.p, integer(0));
        for (Py_ssize_t i = 0; i < input.n; ++i) {
            if ((i & 255) == 0) checkpoint(check_cancel);
            const auto row = input.row(i, scale);
            for (int j = 0; j < input.p; ++j) {
                cy[j] = plus(cy[j], times(row[j+2], row[0]));
                cx[j] = plus(cx[j], times(row[j+2], row[1]));
                for (int k = 0; k <= j; ++k)
                    gram[j*input.p+k] = plus(gram[j*input.p+k], times(row[j+2], row[k+2]));
            }
        }
        Object rows(PyList_New(input.p));
        for (int j = 0; j < input.p; ++j) {
            Vector row; row.reserve(input.p);
            for (int k = 0; k < input.p; ++k) row.push_back(gram[std::max(j,k)*input.p+std::min(j,k)]);
            PyList_SET_ITEM(rows.p, j, list(row).release());
        }
        Object result(PyTuple_New(4));
        PyTuple_SET_ITEM(result.p, 0, integer(scale).release());
        PyTuple_SET_ITEM(result.p, 1, rows.release());
        PyTuple_SET_ITEM(result.p, 2, list(cy).release());
        PyTuple_SET_ITEM(result.p, 3, list(cx).release());
        return result.release();
    } catch (const PythonError&) { return nullptr; }
      catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
}

PyObject* covariance_polynomial(PyObject*, PyObject* args) {
    PyObject *y, *x, *z, *w, *aa, *dd, *uu, *vv, *check_cancel = Py_None;
    int scale;
    if (!PyArg_ParseTuple(args, "OOOOiOOOO|O", &y, &x, &z, &w, &scale, &aa, &dd, &uu, &vv, &check_cancel)) return nullptr;
    try {
        validate_callback(check_cancel);
        Inputs input(y, x, z, w);
        if (scale < 0 || scale > 1074) invalid("native_ar_inconsistent_dyadic_scale");
        if (!PyLong_CheckExact(dd)) invalid("native_ar_exact_integer_required");
        Py_INCREF(dd); Object d(dd);
        const auto u = integers(uu, input.p), v = integers(vv, input.p);
        Object outer(PySequence_Fast(aa, "native_ar_integer_matrix_required"));
        if (PySequence_Fast_GET_SIZE(outer.p) != input.p) invalid("native_ar_integer_matrix_shape");
        std::vector<Vector> a; a.reserve(input.q);
        for (int j = input.p-input.q; j < input.p; ++j)
            a.emplace_back(integers(PySequence_Fast_GET_ITEM(outer.p, j), input.p));
        Vector m(input.q*input.q*3, integer(0));
        const auto negative_two = integer(-2);
        for (Py_ssize_t i = 0; i < input.n; ++i) {
            if ((i & 255) == 0) checkpoint(check_cancel);
            const auto row = input.row(i, scale);
            auto e = minus(times(d, row[0]), dot(u, row, 2));
            auto f = minus(times(d, row[1]), dot(v, row, 2));
            // Exact integer reassociation: (K_i E)(K_j E),
            // (K_i E)(K_j F), (K_i F)(K_j F). The middle sum is
            // multiplied by -2 once after accumulation. Each sum retains
            // observation order; no division, rounding or cancellation.
            Vector ke, kf; ke.reserve(input.q); kf.reserve(input.q);
            for (const auto& line : a) {
                const auto k = dot(line, row, 2);
                ke.emplace_back(times(k, e));
                kf.emplace_back(times(k, f));
            }
            for (int j = 0; j < input.q; ++j)
                for (int h = 0; h <= j; ++h) {
                    const auto index = (j*input.q+h)*3;
                    m[index] = plus(m[index], times(ke[j], ke[h]));
                    m[index+1] = plus(m[index+1], times(ke[j], kf[h]));
                    m[index+2] = plus(m[index+2], times(kf[j], kf[h]));
                }
        }
        Object result(PyList_New(input.q));
        for (int j = 0; j < input.q; ++j) {
            Object row(PyList_New(input.q));
            for (int h = 0; h < input.q; ++h) {
                const auto index = (std::max(j,h)*input.q+std::min(j,h))*3;
                Vector polynomial{m[index], times(negative_two, m[index+1]), m[index+2]};
                PyList_SET_ITEM(row.p, h, list(polynomial).release());
            }
            PyList_SET_ITEM(result.p, j, row.release());
        }
        return result.release();
    } catch (const PythonError&) { return nullptr; }
      catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
}

PyMethodDef methods[] = {
    {"sufficient_statistics", sufficient_statistics, METH_VARARGS, "Exact Gram/cross from original binary64 buffers."},
    {"covariance_polynomial", covariance_polynomial, METH_VARARGS, "Exact residual covariance from original binary64 buffers."},
    {nullptr, nullptr, 0, nullptr}
};
PyModuleDef module = {PyModuleDef_HEAD_INIT, "_ar_exact", nullptr, -1, methods, nullptr, nullptr, nullptr, nullptr};
} // namespace

PyMODINIT_FUNC PyInit__ar_exact() {
    PyObject* result = PyModule_Create(&module);
    if (!result) return nullptr;
    if (PyModule_AddIntConstant(result, "ABI_VERSION", 2) < 0 ||
        PyModule_AddStringConstant(result, "SOURCE_SHA256", AR_EXACT_SOURCE_SHA256) < 0) {
        Py_DECREF(result); return nullptr;
    }
    return result;
}
