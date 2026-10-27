// Independent pilot: exact Kendall integer counts, not tau/p-value certification.
// Two sorts and a Fenwick tree: O(n log n), O(n) owned native storage. No NumPy
// or SciPy headers/library/API, Python scalar conversion, or input .tolist().
// Accepted: equal-length, one-dimensional C-contiguous native float64 buffers.
// NaN is rejected; infinities order normally and either signed zero is a tie.
// Buffers are copied while the GIL is held, then released. The native sort/tree
// phase releases the GIL, operates only on the snapshot, and calls no Python API.
// External writers must not mutate buffers during the initial snapshot. There
// is no bounded cancellation-latency guarantee inside std::sort/Fenwick work.
// Typical 64-bit layout: 24*n bytes of rows plus <=4*(n+1) bytes for the tree;
// no additional n-sized permutation/rank arrays. Inputs themselves remain owned
// by the caller. sizeof(Row)/sort stack are platform details, not RSS evidence.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <stdexcept>
#include <vector>

static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559,
              "Kendall pilot requires IEEE-754 binary64 double");
constexpr std::uint64_t MAX_INPUT_SIZE = 1000000;
// The largest per-variable weighted sum is n*(n-1)*(2*n+5); merging tie groups
// increases this sum. This bound also covers sum t*(t-1)*(t-2), pair totals,
// and discordance. Products of the returned statistics are NOT computed here.
static_assert(MAX_INPUT_SIZE <= std::numeric_limits<std::uint64_t>::max()
    / (MAX_INPUT_SIZE - 1) / (2 * MAX_INPUT_SIZE + 5), "tie statistics exceed uint64");

struct Buffer {
    Py_buffer view{};
    bool active = false;
    ~Buffer() { release(); }
    void release() { if (active) { PyBuffer_Release(&view); active = false; } }
    bool acquire(PyObject* value) {
        if (PyObject_GetBuffer(value, &view, PyBUF_FORMAT | PyBUF_ND | PyBUF_STRIDES) < 0) return false;
        active = true;
        if (view.itemsize != 8 || !view.format ||
            (std::strcmp(view.format, "d") && std::strcmp(view.format, "@d") && std::strcmp(view.format, "=d"))) {
            PyErr_SetString(PyExc_TypeError, "Kendall counts requires native float64 buffers");
            return false;
        }
        if (view.ndim != 1 || !view.shape || view.suboffsets || !PyBuffer_IsContiguous(&view, 'C')) {
            PyErr_SetString(PyExc_ValueError, "Kendall counts requires one-dimensional contiguous buffers");
            return false;
        }
        const Py_ssize_t n = view.shape[0];
        if (n < 0) {
            PyErr_SetString(PyExc_ValueError, "invalid buffer length");
            return false;
        }
        if (static_cast<std::uint64_t>(n) > MAX_INPUT_SIZE) {
            PyErr_SetString(PyExc_OverflowError, "Kendall counts supports at most 1000000 elements");
            return false;
        }
        if (view.len != n * 8 || (n && !view.buf)) {
            PyErr_SetString(PyExc_ValueError, "invalid float64 buffer layout");
            return false;
        }
        return true;
    }
};

struct Row { double x, y; std::uint32_t y_rank; };
struct Ties {
    std::uint64_t pairs = 0, triples = 0, weighted = 0;
    void add(std::uint64_t t) {
        if (t < 2) return;
        pairs += t * (t - 1) / 2;
        triples += t * (t - 1) * (t - 2);
        weighted += t * (t - 1) * (2 * t + 5);
    }
};
struct Counts {
    std::uint64_t n = 0, discordant = 0, joint_pairs = 0;
    Ties x, y;
};

static Counts compute(std::vector<Row>& rows) {
    Counts out;
    const size_t n = rows.size();
    out.n = n;
    std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) { return a.y < b.y; });
    std::uint32_t rank = 0;
    for (size_t start = 0; start < n;) {
        size_t end = start + 1;
        while (end < n && rows[end].y == rows[start].y) ++end;
        out.y.add(end - start);
        ++rank;
        for (size_t i = start; i < end; ++i) rows[i].y_rank = rank;
        start = end;
    }
    std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) {
        return a.x < b.x || (a.x == b.x && a.y_rank < b.y_rank);
    });
    std::vector<std::uint32_t> tree(static_cast<size_t>(rank) + 1, 0);
    std::uint64_t seen = 0;
    for (size_t start = 0; start < n;) {
        size_t end = start + 1;
        while (end < n && rows[end].x == rows[start].x) ++end;
        out.x.add(end - start);
        for (size_t first = start; first < end;) {
            size_t last = first + 1;
            while (last < end && rows[last].y_rank == rows[first].y_rank) ++last;
            const std::uint64_t size = last - first;
            out.joint_pairs += size * (size - 1) / 2;
            first = last;
        }
        // Query the entire x-tie group before inserting any of it. The inclusive
        // y prefix excludes y ties too, so only strictly discordant pairs count.
        for (size_t i = start; i < end; ++i) {
            std::uint64_t prefix = 0;
            for (size_t index = rows[i].y_rank; index; index &= index - 1) prefix += tree[index];
            out.discordant += seen - prefix;
        }
        for (size_t i = start; i < end; ++i) {
            for (size_t index = rows[i].y_rank; index < tree.size(); index += index & -index) ++tree[index];
        }
        seen += end - start;
        start = end;
    }
    return out;
}

struct ReleaseGIL {
    PyThreadState* state = PyEval_SaveThread();
    ~ReleaseGIL() { PyEval_RestoreThread(state); }
};
struct Decref { void operator()(PyObject* value) const { Py_XDECREF(value); } };
using Owned = std::unique_ptr<PyObject, Decref>;

static PyObject* count_impl(PyObject* arguments) {
    PyObject *left, *right;
    if (!PyArg_ParseTuple(arguments, "OO:count", &left, &right)) return nullptr;
    Buffer x, y;
    if (!x.acquire(left) || !y.acquire(right)) return nullptr;
    if (x.view.shape[0] != y.view.shape[0]) {
        PyErr_SetString(PyExc_ValueError, "Kendall buffers must have the same length");
        return nullptr;
    }
    const size_t n = static_cast<size_t>(x.view.shape[0]);
    std::vector<Row> rows(n);
    for (size_t i = 0; i < n; ++i) {
        // memcpy also accepts read-only exporters and unaligned contiguous views.
        std::memcpy(&rows[i].x, static_cast<const char*>(x.view.buf) + 8 * i, 8);
        std::memcpy(&rows[i].y, static_cast<const char*>(y.view.buf) + 8 * i, 8);
        if (std::isnan(rows[i].x) || std::isnan(rows[i].y)) {
            PyErr_SetString(PyExc_ValueError, "Kendall counts does not accept NaN");
            return nullptr;
        }
    }
    x.release();
    y.release();
    Counts counts;
    { ReleaseGIL unlocked; counts = compute(rows); }
    if (PyErr_CheckSignals() < 0) return nullptr;
    Owned output(PyDict_New());
    if (!output) return nullptr;
    const std::pair<const char*, std::uint64_t> fields[] = {
        {"n", counts.n}, {"discordant", counts.discordant}, {"joint_tie_pairs", counts.joint_pairs},
        {"x_tie_pairs", counts.x.pairs}, {"y_tie_pairs", counts.y.pairs},
        {"x_tie_triples", counts.x.triples}, {"y_tie_triples", counts.y.triples},
        {"x_tie_weighted", counts.x.weighted}, {"y_tie_weighted", counts.y.weighted},
    };
    for (const auto& field : fields) {
        Owned value(PyLong_FromUnsignedLongLong(static_cast<unsigned long long>(field.second)));
        if (!value || PyDict_SetItemString(output.get(), field.first, value.get()) < 0) return nullptr;
    }
    return output.release();
}

static PyObject* count(PyObject*, PyObject* arguments) {
    try { return count_impl(arguments); }
    catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
    catch (const std::length_error&) { return PyErr_NoMemory(); }
}
static PyMethodDef methods[] = {
    {"count", count, METH_VARARGS,
     "Return exact discordant/x/y/joint tie pairs and tie triples/weighted sums, not p-values.\n"
     "triples=sum(t*(t-1)*(t-2)); weighted=sum(t*(t-1)*(2*t+5)) over variable tie groups."},
    {nullptr, nullptr, 0, nullptr},
};
static PyModuleDef definition = {
    PyModuleDef_HEAD_INIT, "_kendall_counts", "Independent native integer Kendall-count pilot.",
    -1, methods, nullptr, nullptr, nullptr, nullptr,
};
PyMODINIT_FUNC PyInit__kendall_counts() {
    Owned module(PyModule_Create(&definition));
    if (!module || PyModule_AddIntConstant(module.get(), "MAX_INPUT_SIZE", MAX_INPUT_SIZE) < 0) return nullptr;
    return module.release();
}
