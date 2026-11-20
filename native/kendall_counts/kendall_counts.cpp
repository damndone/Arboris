// Independent pilot: exact Kendall integer counts, not tau/p-value certification.
// Two sorts and a Fenwick tree: O(n log n), O(n) owned native storage. No NumPy
// or SciPy headers/library/API, Python scalar conversion, or input .tolist().
// count: native float64. count_with_ties: each column independently native
// float64, signed int64, or unsigned int64; no integer-to-double conversion.
// Buffers must be equal-length, one-dimensional and C-contiguous.
// NaN is rejected; infinities order normally and either signed zero is a tie.
// Buffers are copied while the GIL is held, then released. The native sort/tree
// phase releases the GIL, operates only on the snapshot, and calls no Python API.
// External writers must not mutate buffers during the initial snapshot. There
// is no bounded cancellation-latency guarantee inside std::sort/Fenwick work.
// Row storage is 16*n bytes: once y sorting assigns dense ranks, the original
// y value is no longer needed and its eight-byte slot holds that integer rank.
// The tree uses <=4*(n+1) bytes. count_with_ties additionally owns uint32 tie
// groups and returns binary sizes in sorted rank order (no Python scalar list).
// These allocation sizes do not establish process peak RSS or speed improvement.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <stdexcept>
#include <type_traits>
#include <vector>

static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559,
              "Kendall pilot requires IEEE-754 binary64 double");
constexpr std::uint64_t MAX_INPUT_SIZE = 1000000;
// The largest per-variable weighted sum is n*(n-1)*(2*n+5); merging tie groups
// increases this sum. This bound also covers sum t*(t-1)*(t-2), pair totals,
// and discordance. Products of the returned statistics are NOT computed here.
static_assert(MAX_INPUT_SIZE <= std::numeric_limits<std::uint64_t>::max()
    / (MAX_INPUT_SIZE - 1) / (2 * MAX_INPUT_SIZE + 5), "tie statistics exceed uint64");

// Per-call requested-byte accounting for owned vectors. allocate() is recorded
// before the old vector allocation is deallocated, so growth overlaps count.
// This is heap payload, not allocator metadata, std::sort stack, or process RSS.
struct Workspace {
    size_t live = 0, peak = 0;
    void add(size_t bytes) { live += bytes; peak = std::max(peak, live); }
    void remove(size_t bytes) { live -= bytes; }
};
static std::atomic<size_t> process_workspace_live{0}, process_workspace_peak{0};
static void workspace_add(size_t bytes) {
    const size_t live = process_workspace_live.fetch_add(bytes, std::memory_order_relaxed) + bytes;
    size_t peak = process_workspace_peak.load(std::memory_order_relaxed);
    while (peak < live && !process_workspace_peak.compare_exchange_weak(
               peak, live, std::memory_order_relaxed)) {}
}
template <typename T> struct TrackedAllocator {
    using value_type = T;
    using propagate_on_container_move_assignment = std::true_type;
    using is_always_equal = std::false_type;
    Workspace* workspace = nullptr;
    explicit TrackedAllocator(Workspace& value) : workspace(&value) {}
    template <typename U> TrackedAllocator(const TrackedAllocator<U>& other)
        : workspace(other.workspace) {}
    T* allocate(size_t count) {
        const size_t bytes = count * sizeof(T);
        // Count before allocate and remove after free: outstanding requests
        // conservatively include concurrent and in-progress allocations too.
        workspace->add(bytes);
        workspace_add(bytes);
        try { return std::allocator<T>{}.allocate(count); }
        catch (...) {
            workspace->remove(bytes);
            process_workspace_live.fetch_sub(bytes, std::memory_order_relaxed);
            throw;
        }
    }
    void deallocate(T* pointer, size_t count) {
        std::allocator<T>{}.deallocate(pointer, count);
        workspace->remove(count * sizeof(T));
        process_workspace_live.fetch_sub(count * sizeof(T), std::memory_order_relaxed);
    }
};
template <typename T, typename U>
bool operator==(const TrackedAllocator<T>& left, const TrackedAllocator<U>& right) {
    return left.workspace == right.workspace;
}
template <typename T, typename U>
bool operator!=(const TrackedAllocator<T>& left, const TrackedAllocator<U>& right) {
    return !(left == right);
}

enum class Kind { Float, Signed, Unsigned };
struct Buffer {
    Py_buffer view{};
    bool active = false;
    Kind kind = Kind::Float;
    ~Buffer() { release(); }
    void release() { if (active) { PyBuffer_Release(&view); active = false; } }
    bool acquire(PyObject* value, bool numeric) {
        if (PyObject_GetBuffer(value, &view, PyBUF_FORMAT | PyBUF_ND | PyBUF_STRIDES) < 0) return false;
        active = true;
        const char* format = view.format;
        const bool floating = format && (!std::strcmp(format, "d") || !std::strcmp(format, "@d")
                                        || !std::strcmp(format, "=d"));
        const bool signed_integer = format && (!std::strcmp(format, "q") || !std::strcmp(format, "@q")
            || !std::strcmp(format, "=q") || (sizeof(long) == 8 &&
                (!std::strcmp(format, "l") || !std::strcmp(format, "@l"))));
        const bool unsigned_integer = format && (!std::strcmp(format, "Q") || !std::strcmp(format, "@Q")
            || !std::strcmp(format, "=Q") || (sizeof(unsigned long) == 8 &&
                (!std::strcmp(format, "L") || !std::strcmp(format, "@L"))));
        if (view.itemsize != 8 || (!floating && !(numeric && (signed_integer || unsigned_integer)))) {
            PyErr_SetString(PyExc_TypeError, numeric
                ? "Kendall counts requires native float64/int64/uint64 buffers"
                : "Kendall counts requires native float64 buffers");
            return false;
        }
        kind = floating ? Kind::Float : (signed_integer ? Kind::Signed : Kind::Unsigned);
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

union Number {
    double floating;
    std::int64_t signed_integer;
    std::uint64_t unsigned_integer;
    Number() : unsigned_integer(0) {}
};
struct Row { Number x, y; };
static_assert(sizeof(Row) == 16, "Kendall row layout requires two eight-byte slots");
template <typename T> static T number(const Number& value) {
    if constexpr (std::is_same_v<T, double>) return value.floating;
    else if constexpr (std::is_same_v<T, std::int64_t>) return value.signed_integer;
    else return value.unsigned_integer;
}
using Rows = std::vector<Row, TrackedAllocator<Row>>;
using Integers = std::vector<std::uint32_t, TrackedAllocator<std::uint32_t>>;
struct Ties {
    std::uint64_t pairs = 0, triples = 0, weighted = 0;
    Integers sizes;
    explicit Ties(Workspace& workspace) : sizes(TrackedAllocator<std::uint32_t>(workspace)) {}
    void add(std::uint64_t t, bool keep_sizes) {
        if (t < 2) return;
        pairs += t * (t - 1) / 2;
        triples += t * (t - 1) * (t - 2);
        weighted += t * (t - 1) * (2 * t + 5);
        if (keep_sizes) sizes.push_back(static_cast<std::uint32_t>(t));
    }
};
struct Counts {
    std::uint64_t n = 0, discordant = 0, joint_pairs = 0;
    bool public_float_compatible = true;
    Ties x, y;
    explicit Counts(Workspace& workspace) : x(workspace), y(workspace) {}
};

template <typename X, typename Y>
static Counts compute(Rows& rows, bool keep_sizes, Workspace& workspace) {
    Counts out(workspace);
    const size_t n = rows.size();
    out.n = n;
    std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) {
        return number<Y>(a.y) < number<Y>(b.y);
    });
    std::uint32_t rank = 0;
    for (size_t start = 0; start < n;) {
        size_t end = start + 1;
        while (end < n && number<Y>(rows[end].y) == number<Y>(rows[start].y)) ++end;
        out.y.add(end - start, keep_sizes);
        ++rank;
        for (size_t i = start; i < end; ++i) rows[i].y.unsigned_integer = rank;
        start = end;
    }
    std::sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) {
        return number<X>(a.x) < number<X>(b.x) || (number<X>(a.x) == number<X>(b.x)
            && a.y.unsigned_integer < b.y.unsigned_integer);
    });
    Integers tree(static_cast<size_t>(rank) + 1, 0, TrackedAllocator<std::uint32_t>(workspace));
    std::uint64_t seen = 0;
    for (size_t start = 0; start < n;) {
        size_t end = start + 1;
        while (end < n && number<X>(rows[end].x) == number<X>(rows[start].x)) ++end;
        out.x.add(end - start, keep_sizes);
        for (size_t first = start; first < end;) {
            size_t last = first + 1;
            while (last < end && rows[last].y.unsigned_integer == rows[first].y.unsigned_integer) ++last;
            const std::uint64_t size = last - first;
            out.joint_pairs += size * (size - 1) / 2;
            // One query per joint group instead of per observation. Every
            // member has the same y prefix, while x ties remain excluded.
            std::uint64_t prefix = 0;
            for (size_t index = rows[first].y.unsigned_integer; index; index &= index - 1) prefix += tree[index];
            out.discordant += (seen - prefix) * size;
            first = last;
        }
        // Query the entire x-tie group before inserting any of it. The inclusive
        // y prefix excludes y ties too, so only strictly discordant pairs count.
        for (size_t first = start; first < end;) {
            size_t last = first + 1;
            while (last < end && rows[last].y.unsigned_integer == rows[first].y.unsigned_integer) ++last;
            const auto size = static_cast<std::uint32_t>(last - first);
            for (size_t index = rows[first].y.unsigned_integer; index < tree.size(); index += index & -index) tree[index] += size;
            first = last;
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

struct NaNInput {};
template <typename T> static bool snapshot_number(Number& target, const char* source) {
    T value;
    std::memcpy(&value, source, 8);  // read-only and unaligned exporters remain valid
    if constexpr (std::is_same_v<T, double>) {
        if (std::isnan(value)) throw NaNInput{};
        target.floating = value;
        return true;
    } else if constexpr (std::is_same_v<T, std::int64_t>) {
        target.signed_integer = value;
        return value >= -INT64_C(9007199254740992) && value <= INT64_C(9007199254740992);
    } else {
        target.unsigned_integer = value;
        return value <= UINT64_C(9007199254740992);
    }
}
template <typename X, typename Y>
static Counts snapshot_and_compute(Buffer& x, Buffer& y, bool keep_sizes, Workspace& workspace) {
    const size_t n = static_cast<size_t>(x.view.shape[0]);
    Rows rows(n, TrackedAllocator<Row>(workspace));
    bool compatible = true;
    for (size_t i = 0; i < n; ++i) {
        const bool left = snapshot_number<X>(rows[i].x, static_cast<const char*>(x.view.buf) + 8 * i);
        const bool right = snapshot_number<Y>(rows[i].y, static_cast<const char*>(y.view.buf) + 8 * i);
        compatible = compatible && left && right;
    }
    x.release();
    y.release();
    ReleaseGIL unlocked;
    Counts out = compute<X, Y>(rows, keep_sizes, workspace);
    out.public_float_compatible = compatible;
    return out;
}
template <typename X>
static Counts dispatch_y(Buffer& x, Buffer& y, bool keep_sizes, Workspace& workspace) {
    if (y.kind == Kind::Float) return snapshot_and_compute<X, double>(x, y, keep_sizes, workspace);
    if (y.kind == Kind::Signed) return snapshot_and_compute<X, std::int64_t>(x, y, keep_sizes, workspace);
    return snapshot_and_compute<X, std::uint64_t>(x, y, keep_sizes, workspace);
}

static PyObject* count_impl(PyObject* arguments, bool keep_sizes) {
    PyObject *left, *right;
    if (!PyArg_ParseTuple(arguments, keep_sizes ? "OO:count_with_ties" : "OO:count", &left, &right)) return nullptr;
    Buffer x, y;
    if (!x.acquire(left, keep_sizes) || !y.acquire(right, keep_sizes)) return nullptr;
    if (x.view.shape[0] != y.view.shape[0]) {
        PyErr_SetString(PyExc_ValueError, "Kendall buffers must have the same length");
        return nullptr;
    }
    Workspace workspace;
    Counts counts(workspace);
    if (x.kind == Kind::Float) counts = dispatch_y<double>(x, y, keep_sizes, workspace);
    else if (x.kind == Kind::Signed) counts = dispatch_y<std::int64_t>(x, y, keep_sizes, workspace);
    else counts = dispatch_y<std::uint64_t>(x, y, keep_sizes, workspace);
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
    if (keep_sizes) {
        if (PyDict_SetItemString(output.get(), "public_float_compatible",
                                counts.public_float_compatible ? Py_True : Py_False) < 0) return nullptr;
        Owned peak(PyLong_FromSize_t(workspace.peak));
        if (!peak || PyDict_SetItemString(output.get(), "workspace_bytes", peak.get()) < 0) return nullptr;
        const std::pair<const char*, const Ties*> ties[] = {
            {"x_tie_sizes", &counts.x}, {"y_tie_sizes", &counts.y},
        };
        for (const auto& field : ties) {
            const auto& sizes = field.second->sizes;
            Owned value(PyBytes_FromStringAndSize(reinterpret_cast<const char*>(sizes.data()),
                static_cast<Py_ssize_t>(sizes.size() * sizeof(std::uint32_t))));
            if (!value || PyDict_SetItemString(output.get(), field.first, value.get()) < 0) return nullptr;
        }
    }
    return output.release();
}

static PyObject* count(PyObject*, PyObject* arguments) {
    try { return count_impl(arguments, false); }
    catch (const NaNInput&) {
        PyErr_SetString(PyExc_ValueError, "Kendall counts does not accept NaN"); return nullptr;
    }
    catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
    catch (const std::length_error&) { return PyErr_NoMemory(); }
}
static PyObject* count_with_ties(PyObject*, PyObject* arguments) {
    try { return count_impl(arguments, true); }
    catch (const NaNInput&) {
        PyErr_SetString(PyExc_ValueError, "Kendall counts does not accept NaN"); return nullptr;
    }
    catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
    catch (const std::length_error&) { return PyErr_NoMemory(); }
}
static PyObject* workspace_bytes(PyObject*, PyObject*) {
    return PyLong_FromSize_t(process_workspace_peak.load(std::memory_order_relaxed));
}
static PyMethodDef methods[] = {
    {"count", count, METH_VARARGS,
     "Return exact discordant/x/y/joint tie pairs and tie triples/weighted sums, not p-values.\n"
     "triples=sum(t*(t-1)*(t-2)); weighted=sum(t*(t-1)*(2*t+5)) over variable tie groups."},
    {"count_with_ties", count_with_ties, METH_VARARGS,
     "Return exact counts plus native uint32 tie-size bytes, sorted by variable rank."},
    {"workspace_bytes", workspace_bytes, METH_NOARGS,
     "Process high-water of outstanding owned-vector byte requests; fresh worker required, not RSS."},
    {nullptr, nullptr, 0, nullptr},
};
static PyModuleDef definition = {
    PyModuleDef_HEAD_INIT, "_kendall_counts", "Independent native integer Kendall-count pilot.",
    -1, methods, nullptr, nullptr, nullptr, nullptr,
};
PyMODINIT_FUNC PyInit__kendall_counts() {
    Owned module(PyModule_Create(&definition));
    if (!module || PyModule_AddIntConstant(module.get(), "MAX_INPUT_SIZE", MAX_INPUT_SIZE) < 0
        || PyModule_AddIntConstant(module.get(), "API_VERSION", 4) < 0) return nullptr;
    return module.release();
}
