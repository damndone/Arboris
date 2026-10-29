// Canonical-v1 numeric-list kernel used by workbench.canonical.
// Keep Python's repr, arbitrary-precision str, and dictionary equality/hash.
// std::to_chars/iostream floating formatting cannot establish byte equivalence.
// No input buffer/list copy: the GIL stays held while exact list/tuple items are
// read. Memory: O(distinct values) Python dictionary/text cache plus O(JSON bytes)
// final Python Unicode. Assembly writes directly into that result; no whole-output
// std::string or result copy is allocated. This is not zero-copy,
// streaming, a cancellable worker, or an end-to-end performance result.
// Do not call Python signal handlers inside the loops: they could resize the
// borrowed list while its fixed count/items are being read. The synchronous
// entry point keeps the GIL and has no bounded cancellation-latency guarantee.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef ANALYSIS_SAMPLE_SOURCE_SHA256
#define ANALYSIS_SAMPLE_SOURCE_SHA256 ""
#endif

struct Decref {
    void operator()(PyObject* value) const { Py_XDECREF(value); }
};
using Owned = std::unique_ptr<PyObject, Decref>;

static PyObject* nonfinite_error(PyObject* module) {
    Owned error(PyObject_GetAttrString(module, "CanonicalJSONError"));
    if (error) {
        PyErr_SetString(error.get(), "canonical JSON does not allow NaN or Infinity");
    }
    return nullptr;
}

static PyObject* format_float(PyObject* value) {
    const double number = PyFloat_AS_DOUBLE(value);
    if (number == 0.0) {
        return PyUnicode_FromString("0");
    }
    Owned representation(PyObject_Repr(value));
    if (!representation) return nullptr;
    const char* raw = PyUnicode_AsUTF8(representation.get());
    if (!raw) return nullptr;
    std::string text(raw);
    const bool negative = text.front() == '-';
    if (negative) text.erase(0, 1);
    const auto exponent_at = text.find('e');
    const int exponent = exponent_at == std::string::npos
        ? 0 : std::stoi(text.substr(exponent_at + 1));
    const std::string mantissa = text.substr(0, exponent_at);
    const auto dot_at = mantissa.find('.');
    const int integer_length = static_cast<int>(
        dot_at == std::string::npos ? mantissa.size() : dot_at);
    std::string digits = mantissa;
    if (dot_at != std::string::npos) digits.erase(dot_at, 1);
    const int position = integer_length + exponent;
    std::string rendered;
    const double magnitude = std::fabs(number);
    if (1e-6 <= magnitude && magnitude < 1e21) {
        if (position <= 0) {
            rendered = "0." + std::string(-position, '0') + digits;
        } else if (position >= static_cast<int>(digits.size())) {
            rendered = digits + std::string(position - digits.size(), '0');
        } else {
            rendered = digits.substr(0, position) + "." + digits.substr(position);
        }
        if (rendered.find('.') != std::string::npos) {
            while (rendered.back() == '0') rendered.pop_back();
            if (rendered.back() == '.') rendered.pop_back();
        }
    } else {
        rendered = digits.substr(0, 1);
        std::string trailing = digits.substr(1);
        while (!trailing.empty() && trailing.back() == '0') trailing.pop_back();
        if (!trailing.empty()) rendered += "." + trailing;
        const int power = position - 1;
        rendered += "e" + std::string(power >= 0 ? "+" : "") + std::to_string(power);
    }
    if (negative) rendered.insert(0, "-");
    return PyUnicode_FromStringAndSize(rendered.data(), static_cast<Py_ssize_t>(rendered.size()));
}

static PyObject* encode_impl(PyObject* module, PyObject* values) {
    if (!PyList_CheckExact(values) && !PyTuple_CheckExact(values)) {
        PyErr_SetString(PyExc_TypeError, "native canonical numbers requires an exact list or tuple");
        return nullptr;
    }
    // Allocate the GC-capable cache before borrowing the fixed sequence view.
    // Subsequent exact-number formatting produces only untracked text objects.
    Owned cache(PyDict_New());
    if (!cache) return nullptr;
    const bool is_list = PyList_CheckExact(values);
    const Py_ssize_t count = is_list ? PyList_GET_SIZE(values) : PyTuple_GET_SIZE(values);
    const auto item_at = [values, is_list](Py_ssize_t index) {
        return is_list ? PyList_GET_ITEM(values, index) : PyTuple_GET_ITEM(values, index);
    };
    // Match _numeric_list's exact-type boundary before invoking numeric APIs.
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* item = item_at(index);
        if (!PyLong_CheckExact(item) && !PyFloat_CheckExact(item)) {
            PyErr_SetString(PyExc_TypeError, "native canonical numbers requires exact int or float items");
            return nullptr;
        }
    }
    // _normalize validates all(math.isfinite, values) before formatting. This
    // intentionally retains its OverflowError on integers beyond double range.
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* item = item_at(index);
        const double number = PyFloat_CheckExact(item) ? PyFloat_AS_DOUBLE(item) : PyLong_AsDouble(item);
        if (PyErr_Occurred()) return nullptr;
        if (!std::isfinite(number)) return nonfinite_error(module);
    }
    // Retain the original dict equality/cache order (including equal int/float
    // keys), but allocate the final ASCII Unicode exactly once. This avoids the
    // pilot's whole std::string output + Unicode copy at peak residency.
    Py_ssize_t total = 2;
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* item = item_at(index);
        PyObject* encoded = PyDict_GetItemWithError(cache.get(), item);
        if (!encoded) {
            if (PyErr_Occurred()) return nullptr;
            Owned fresh(PyLong_CheckExact(item) ? PyObject_Str(item) : format_float(item));
            if (!fresh || PyDict_SetItem(cache.get(), item, fresh.get()) < 0) return nullptr;
            encoded = fresh.get();  // cache owns a reference after insertion.
        }
        const Py_ssize_t length = PyUnicode_GET_LENGTH(encoded);
        const Py_ssize_t separator = index != 0;
        if (length > PY_SSIZE_T_MAX - total - separator) return PyErr_NoMemory();
        total += length + separator;
    }
    Owned output(PyUnicode_New(total, 127));
    if (!output) return nullptr;
    Py_UCS1* destination = PyUnicode_1BYTE_DATA(output.get());
    *destination++ = '[';
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* encoded = PyDict_GetItemWithError(cache.get(), item_at(index));
        if (!encoded) return nullptr;
        const Py_ssize_t length = PyUnicode_GET_LENGTH(encoded);
        if (index) *destination++ = ',';
        std::memcpy(destination, PyUnicode_1BYTE_DATA(encoded), static_cast<size_t>(length));
        destination += length;
    }
    *destination = ']';
    return output.release();
}

static PyObject* encode_numbers(PyObject* module, PyObject* values) {
    try {
        return encode_impl(module, values);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    } catch (const std::length_error&) {
        return PyErr_NoMemory();
    }
}

static PyObject* sequence_item(PyObject* values, Py_ssize_t index) {
    return PyList_CheckExact(values) ? PyList_GET_ITEM(values, index) : PyTuple_GET_ITEM(values, index);
}

static Py_ssize_t sequence_size(PyObject* values) {
    return PyList_CheckExact(values) ? PyList_GET_SIZE(values) : PyTuple_GET_SIZE(values);
}

static bool add_size(Py_ssize_t& total, Py_ssize_t size) {
    if (size > PY_SSIZE_T_MAX - total) {
        PyErr_NoMemory();
        return false;
    }
    total += size;
    return true;
}

static bool decimal_sequence_size(PyObject* values, Py_ssize_t& size) {
    const Py_ssize_t count = sequence_size(values);
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* item = sequence_item(values, index);
        if (!PyUnicode_CheckExact(item) || !PyUnicode_IS_ASCII(item)) return false;
        const Py_ssize_t length = PyUnicode_GET_LENGTH(item);
        if (!length) return false;
        const Py_UCS1* data = PyUnicode_1BYTE_DATA(item);
        for (Py_ssize_t offset = 0; offset < length; ++offset) {
            if (data[offset] < '0' || data[offset] > '9') return false;
        }
        if (!add_size(size, length) || !add_size(size, 2) || (index && !add_size(size, 1))) return false;
    }
    return true;
}

static PyObject* analysis_sample_impl(PyObject* row_set, PyObject* row_order) {
    if ((!PyList_CheckExact(row_set) && !PyTuple_CheckExact(row_set)) ||
        (!PyList_CheckExact(row_order) && !PyTuple_CheckExact(row_order))) Py_RETURN_NONE;
    Py_ssize_t set_size = 0, order_size = 0;
    if (!decimal_sequence_size(row_set, set_size) ||
        (row_set != row_order && !decimal_sequence_size(row_order, order_size))) {
        if (PyErr_Occurred()) return nullptr;
        Py_RETURN_NONE;
    }
    if (row_set == row_order) order_size = set_size;
    static constexpr char prefix[] = "{\"fingerprint_type\":\"analysis_sample_v1\",\"value\":{\"row_order\":[";
    static constexpr char middle[] = "],\"row_set\":[";
    static constexpr char suffix[] = "]}}";
    Py_ssize_t total = sizeof(prefix) - 1 + sizeof(middle) - 1 + sizeof(suffix) - 1;
    if (!add_size(total, order_size) || !add_size(total, set_size)) return nullptr;

    // The arguments own the exact outer containers and their immutable strings.
    // Keep the GIL throughout. After validation there are no Python callbacks,
    // signal checks, or GC-tracked allocations: vector storage uses the C++
    // allocator and the final PyBytes is untracked. A GC finalizer therefore
    // cannot resize a borrowed input list during these reads. No GIL release or
    // bounded cancellation-latency claim is made for this explicit candidate.
    std::vector<PyObject*> sorted;
    const Py_ssize_t count = sequence_size(row_set);
    sorted.reserve(static_cast<size_t>(count));
    for (Py_ssize_t index = 0; index < count; ++index) sorted.push_back(sequence_item(row_set, index));
    std::sort(sorted.begin(), sorted.end(), [](PyObject* left, PyObject* right) {
        const Py_ssize_t a = PyUnicode_GET_LENGTH(left), b = PyUnicode_GET_LENGTH(right);
        const int comparison = std::memcmp(PyUnicode_1BYTE_DATA(left), PyUnicode_1BYTE_DATA(right),
                                           static_cast<size_t>(std::min(a, b)));
        return comparison < 0 || (comparison == 0 && a < b);
    });
    Owned output(PyBytes_FromStringAndSize(nullptr, total));
    if (!output) return nullptr;
    char* destination = PyBytes_AS_STRING(output.get());
    const auto literal = [&destination](const char* data, size_t length) {
        std::memcpy(destination, data, length);
        destination += length;
    };
    const auto item = [&destination](PyObject* value, bool separator) {
        if (separator) *destination++ = ',';
        *destination++ = '"';
        const Py_ssize_t length = PyUnicode_GET_LENGTH(value);
        std::memcpy(destination, PyUnicode_1BYTE_DATA(value), static_cast<size_t>(length));
        destination += length;
        *destination++ = '"';
    };
    literal(prefix, sizeof(prefix) - 1);
    const Py_ssize_t order_count = sequence_size(row_order);
    for (Py_ssize_t index = 0; index < order_count; ++index) item(sequence_item(row_order, index), index != 0);
    literal(middle, sizeof(middle) - 1);
    for (size_t index = 0; index < sorted.size(); ++index) item(sorted[index], index != 0);
    literal(suffix, sizeof(suffix) - 1);
    return output.release();
}

static PyObject* encode_analysis_sample_v1(PyObject*, PyObject* arguments) {
    PyObject* row_set;
    PyObject* row_order;
    if (!PyArg_ParseTuple(arguments, "OO:encode_analysis_sample_v1", &row_set, &row_order)) return nullptr;
    try {
        return analysis_sample_impl(row_set, row_order);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    } catch (const std::length_error&) {
        return PyErr_NoMemory();
    }
}

static PyMethodDef methods[] = {
    {"encode_numbers", encode_numbers, METH_O,
     "Encode exact int/float list/tuple using the existing canonical-v1 bytes."},
    {"encode_analysis_sample_v1", encode_analysis_sample_v1, METH_VARARGS,
     "Explicit unmeasured analysis_sample_v1 bytes for exact decimal-string sequences, else None."},
    {nullptr, nullptr, 0, nullptr}
};

static PyModuleDef definition = {
    PyModuleDef_HEAD_INIT, "_canonical_numbers",
    "Canonical-v1 exact numeric-sequence encoding kernel.",
    -1, methods, nullptr, nullptr, nullptr, nullptr
};

PyMODINIT_FUNC PyInit__canonical_numbers() {
    Owned module(PyModule_Create(&definition));
    if (!module) return nullptr;
    if (PyModule_AddIntConstant(module.get(), "ABI_VERSION", 1) < 0) return nullptr;
    if (PyModule_AddIntConstant(module.get(), "ANALYSIS_SAMPLE_ABI_VERSION", 1) < 0) return nullptr;
    if (PyModule_AddStringConstant(module.get(), "ANALYSIS_SAMPLE_SOURCE_SHA256", ANALYSIS_SAMPLE_SOURCE_SHA256) < 0) return nullptr;
    Owned canonical(PyImport_ImportModule("workbench.canonical"));
    if (!canonical) return nullptr;
    Owned error(PyObject_GetAttrString(canonical.get(), "CanonicalJSONError"));
    if (!error || PyModule_AddObjectRef(module.get(), "CanonicalJSONError", error.get()) < 0) return nullptr;
    return module.release();
}
