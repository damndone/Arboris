// Spearman prototype only: exact average ranks, native 64-bit numeric buffers.
// No NumPy ABI and no int->double conversion before ordering/tie detection.
// Input is snapshotted into monotone uint64 keys while the GIL is held; radix
// passes and output filling then release the GIL over private C++ data only.
// Returned bytes own a float64 (n_rows, n_columns) Fortran-order rank matrix.
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <numeric>
#include <stdexcept>
#include <utility>
#include <vector>

static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559,
              "Spearman rank output requires IEEE754 binary64");

namespace {
constexpr Py_ssize_t MAX_ROWS = 1000000;
constexpr Py_ssize_t MAX_COLUMNS = 32;
constexpr uint64_t SIGN = uint64_t{1} << 63;
constexpr uint64_t EXPONENT = uint64_t{0x7ff} << 52;
struct PythonError {};

// Always-on requested-byte accounting, independent of Python tracemalloc.
// The allocator sees actual vector allocate/deallocate sizes (also capacity
// growth and failed requests). It does not claim malloc usable-size/RSS.
struct Ledger {
    std::atomic<size_t> live{0}, peak{0}, allocated{0}, allocations{0}, failures{0}, attempted_peak{0};
    static void high(std::atomic<size_t>& target, size_t value) {
        auto old = target.load(std::memory_order_relaxed);
        while (old < value && !target.compare_exchange_weak(old,value,std::memory_order_relaxed)) {}
    }
    void acquire(size_t bytes) {
        high(peak,live.fetch_add(bytes,std::memory_order_relaxed)+bytes);
        allocated.fetch_add(bytes,std::memory_order_relaxed);
        allocations.fetch_add(1,std::memory_order_relaxed);
    }
    void release(size_t bytes) { live.fetch_sub(bytes,std::memory_order_relaxed); }
};
Ledger cpp_workspace, python_output;

template<class T> class CountingAllocator {
public:
    using value_type = T;
    CountingAllocator() noexcept = default;
    template<class U> CountingAllocator(const CountingAllocator<U>&) noexcept {}
    T* allocate(size_t n) {
        if (n > std::numeric_limits<size_t>::max()/sizeof(T)) throw std::bad_alloc{};
        const size_t bytes = n*sizeof(T);
        Ledger::high(cpp_workspace.attempted_peak,bytes);
        try {
            T* result = std::allocator<T>{}.allocate(n);
            cpp_workspace.acquire(bytes);
            return result;
        } catch (...) { cpp_workspace.failures.fetch_add(1,std::memory_order_relaxed); throw; }
    }
    void deallocate(T* p, size_t n) noexcept {
        std::allocator<T>{}.deallocate(p,n);
        cpp_workspace.release(n*sizeof(T));
    }
    template<class U> bool operator==(const CountingAllocator<U>&) const noexcept { return true; }
    template<class U> bool operator!=(const CountingAllocator<U>&) const noexcept { return false; }
};
template<class T> using Vector = std::vector<T,CountingAllocator<T>>;

class OutputRequest {
    size_t bytes;
public:
    explicit OutputRequest(size_t n) : bytes(n) { python_output.acquire(bytes); }
    ~OutputRequest() { python_output.release(bytes); }
};

class Object {
public:
    PyObject* value;
    explicit Object(PyObject* p) : value(p) { if (!p) throw PythonError{}; }
    Object(const Object&) = delete;
    ~Object() { Py_XDECREF(value); }
    PyObject* release() { return std::exchange(value, nullptr); }
};

class ReleasedGIL {
    PyThreadState* state = PyEval_SaveThread();
public:
    ReleasedGIL() = default;
    ReleasedGIL(const ReleasedGIL&) = delete;
    ~ReleasedGIL() { PyEval_RestoreThread(state); }
};

void fail(PyObject* type, const char* message) {
    PyErr_SetString(type,message);
    throw PythonError{};
}

void checkpoint(PyObject* check_cancel) {
    if (PyErr_CheckSignals() < 0) throw PythonError{};
    if (check_cancel != Py_None) { Object checked(PyObject_CallNoArgs(check_cancel)); }
}

enum class Kind { Float64, Int64, UInt64 };

Kind native_kind(const Py_buffer& buffer) {
    if (buffer.itemsize != 8 || !buffer.format)
        fail(PyExc_TypeError,"Spearman ranks require a native float64/int64/uint64 buffer");
    const char* format = buffer.format;
    const size_t length = std::strlen(format);
    if (length == 2) {
        const uint16_t one = 1;
        const bool little = *reinterpret_cast<const unsigned char*>(&one) == 1;
        if ((format[0] == '<' && !little) || (format[0] == '>' && little) || format[0] == '!')
            fail(PyExc_TypeError,"Spearman ranks reject non-native byte order");
        if (format[0] != '=' && format[0] != '@' && format[0] != '<' && format[0] != '>')
            fail(PyExc_TypeError,"Spearman ranks require a native float64/int64/uint64 buffer");
        ++format;
    } else if (length != 1) {
        fail(PyExc_TypeError,"Spearman ranks require a native float64/int64/uint64 buffer");
    }
    if (format[0] == 'd') return Kind::Float64;
    if (format[0] == 'q' || format[0] == 'l') return Kind::Int64;
    if (format[0] == 'Q' || format[0] == 'L') return Kind::UInt64;
    fail(PyExc_TypeError,"Spearman ranks require a native float64/int64/uint64 buffer");
    return Kind::Float64; // fail always throws.
}

class Buffer {
public:
    Py_buffer view{};
    Kind kind;
    explicit Buffer(PyObject* source) {
        if (PyObject_GetBuffer(source,&view,PyBUF_FORMAT|PyBUF_STRIDES) < 0) throw PythonError{};
        try {
            kind = native_kind(view);
            if (view.ndim != 2 || view.shape[0] < 0 || view.shape[1] < 1)
                fail(PyExc_ValueError,"Spearman rank buffer shape must be (rows, columns)");
            if (view.shape[0] > MAX_ROWS || view.shape[1] > MAX_COLUMNS)
                fail(PyExc_ValueError,"Spearman prototype outside finite <=1M-row, <=32-column envelope");
            if (view.suboffsets)
                fail(PyExc_TypeError,"Spearman rank buffer does not support indirect storage");
        } catch (...) { PyBuffer_Release(&view); throw; }
    }
    Buffer(const Buffer&) = delete;
    ~Buffer() { PyBuffer_Release(&view); }
    uint64_t word(Py_ssize_t row, Py_ssize_t column) const {
        uint64_t result;
        const char* address = static_cast<const char*>(view.buf)
            + row*view.strides[0] + column*view.strides[1];
        std::memcpy(&result,address,8);
        return result;
    }
};

uint64_t ordered_key(uint64_t word, Kind kind) {
    if (kind == Kind::Int64) return word ^ SIGN;
    if (kind == Kind::UInt64) return word;
    if ((word & EXPONENT) == EXPONENT)
        fail(PyExc_ValueError,"Spearman native rank envelope requires finite binary64 values");
    // Both signed zeros have one tie key, like numerical equality in rankdata.
    if ((word & ~SIGN) == 0) word = 0;
    return word & SIGN ? ~word : word ^ SIGN;
}

void store_rank(char* destination, Py_ssize_t row, Py_ssize_t column,
                Py_ssize_t count, double rank) {
    const auto offset = static_cast<size_t>(column*count+row)*sizeof(double);
    std::memcpy(destination+offset,&rank,sizeof(rank));
}

PyObject* rank_matrix(PyObject*, PyObject* args) {
    PyObject *source, *check_cancel = Py_None;
    if (!PyArg_ParseTuple(args,"O|O",&source,&check_cancel)) return nullptr;
    try {
        if (check_cancel != Py_None && !PyCallable_Check(check_cancel))
            fail(PyExc_TypeError,"Spearman rank cancellation check must be callable");
        Buffer input(source);
        const Py_ssize_t n = input.view.shape[0], columns = input.view.shape[1];
        const size_t total = static_cast<size_t>(n)*static_cast<size_t>(columns);
        if (total > static_cast<size_t>(PY_SSIZE_T_MAX)/sizeof(double)) return PyErr_NoMemory();
        // Snapshot all input before any GIL release or Python signal/callback.
        // This also validates every float before std::sort/radix assumptions.
        Vector<uint64_t> keys(total), varying(static_cast<size_t>(columns),0);
        for (Py_ssize_t col = 0; col < columns; ++col) {
            uint64_t first = 0;
            for (Py_ssize_t row = 0; row < n; ++row) {
                const auto key = ordered_key(input.word(row,col),input.kind);
                keys[static_cast<size_t>(col*n+row)] = key;
                if (row == 0) first = key;
                varying[static_cast<size_t>(col)] |= key ^ first;
            }
        }
        Ledger::high(python_output.attempted_peak,total*sizeof(double));
        PyObject* raw_result = PyBytes_FromStringAndSize(nullptr,static_cast<Py_ssize_t>(total*sizeof(double)));
        if (!raw_result) { python_output.failures.fetch_add(1,std::memory_order_relaxed); throw PythonError{}; }
        Object result(raw_result);
        OutputRequest output_request(total*sizeof(double));
        if (n == 0) { checkpoint(check_cancel); return result.release(); }
        char* output = PyBytes_AS_STRING(result.value);
        Vector<uint32_t> order(static_cast<size_t>(n)), scratch(static_cast<size_t>(n));
        checkpoint(check_cancel);
        for (Py_ssize_t col = 0; col < columns; ++col) {
            const uint64_t* values = keys.data()+static_cast<size_t>(col*n);
            {
                ReleasedGIL released;
                std::iota(order.begin(),order.end(),uint32_t{0});
            }
            for (unsigned byte = 0; byte < 8; ++byte) {
                const unsigned shift = byte*8;
                if (((varying[static_cast<size_t>(col)] >> shift) & 255) == 0) continue;
                {
                    ReleasedGIL released;
                    std::array<size_t,256> positions{};
                    for (const auto index : order) ++positions[(values[index] >> shift) & 255];
                    size_t accumulated = 0;
                    for (auto& position : positions) {
                        const size_t count = position;
                        position = accumulated;
                        accumulated += count;
                    }
                    for (const auto index : order)
                        scratch[positions[(values[index] >> shift) & 255]++] = index;
                    order.swap(scratch);
                }
                checkpoint(check_cancel);
            }
            {
                ReleasedGIL released;
                size_t start = 0;
                while (start < order.size()) {
                    size_t finish = start+1;
                    while (finish < order.size() && values[order[finish]] == values[order[start]]) ++finish;
                    // All average ranks are integer/half-integer <=1M and are
                    // therefore represented exactly by binary64.
                    const double average = static_cast<double>(start+finish+1)/2.;
                    for (size_t i = start; i < finish; ++i)
                        store_rank(output,order[i],col,n,average);
                    start = finish;
                }
            }
            checkpoint(check_cancel);
        }
        return result.release();
    } catch (const PythonError&) { return nullptr; }
      catch (const std::bad_alloc&) { return PyErr_NoMemory(); }
      catch (const std::length_error&) { return PyErr_NoMemory(); }
}

PyObject* workspace_info(PyObject*, PyObject*) {
    return Py_BuildValue("{sK,sK,sK,sK,sK,sK,sK,sK,sK,sK,sK,sK,sK}",
        "cpp_live_requested_bytes",static_cast<unsigned long long>(cpp_workspace.live.load()),
        "cpp_peak_requested_bytes",static_cast<unsigned long long>(cpp_workspace.peak.load()),
        "cpp_total_requested_bytes",static_cast<unsigned long long>(cpp_workspace.allocated.load()),
        "cpp_allocations",static_cast<unsigned long long>(cpp_workspace.allocations.load()),
        "cpp_allocation_failures",static_cast<unsigned long long>(cpp_workspace.failures.load()),
        "cpp_largest_requested_allocation",static_cast<unsigned long long>(cpp_workspace.attempted_peak.load()),
        "python_output_live_in_kernel_bytes",static_cast<unsigned long long>(python_output.live.load()),
        "python_output_peak_in_kernel_bytes",static_cast<unsigned long long>(python_output.peak.load()),
        "python_output_total_requested_bytes",static_cast<unsigned long long>(python_output.allocated.load()),
        "python_output_allocations",static_cast<unsigned long long>(python_output.allocations.load()),
        "python_output_allocation_failures",static_cast<unsigned long long>(python_output.failures.load()),
        "python_output_largest_requested_allocation",static_cast<unsigned long long>(python_output.attempted_peak.load()),
        "radix_histogram_stack_bytes_per_active_pass",static_cast<unsigned long long>(256*sizeof(size_t)));
}

PyMethodDef methods[] = {
    {"rank_matrix",rank_matrix,METH_VARARGS,
     "Average ranks of native float64/int64/uint64 columns as immutable F-order binary64 bytes."},
    {"workspace_info",workspace_info,METH_NOARGS,"Always-on native requested bytes; output transfer and stack separately labelled."},
    {nullptr,nullptr,0,nullptr}
};
PyModuleDef definition = {PyModuleDef_HEAD_INIT,"_spearman_rank",nullptr,-1,methods,nullptr,nullptr,nullptr,nullptr};
} // namespace

PyMODINIT_FUNC PyInit__spearman_rank() {
    PyObject* module = PyModule_Create(&definition);
    if (!module) return nullptr;
    if (PyModule_AddIntConstant(module,"ABI_VERSION",1) < 0) { Py_DECREF(module); return nullptr; }
    return module;
}
