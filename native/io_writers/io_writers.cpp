// Output encoders for workbench.native_io: JSON text, canonical-v1 lists, CSV rows and
// Stata .dta rows. Each one writes the bytes its Python reference writes; anything outside
// the shapes it knows returns None, and the caller runs the reference instead.
// Floats are formatted by PyOS_double_to_string(x, 'r', 0, Py_DTSF_ADD_DOT_0), which is
// float.__repr__ itself, never by std::to_chars. The GIL stays held throughout: inputs are
// read in place and no Python code runs while a borrowed container is being read, except
// the explicit fallback callback of json_safe, which the reference would call too.

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <new>
#include <string>
#include <vector>

namespace {

constexpr int ABI_VERSION = 1;
constexpr int MAX_DEPTH = 400;

struct Decref {
    void operator()(PyObject* value) const { Py_XDECREF(value); }
};
using Owned = std::unique_ptr<PyObject, Decref>;

// Text of a double, cached by bit pattern: data columns repeat values heavily.
// The table is allocated on the first value, sized for the rows it can see, so a wide
// table's non-float columns cost nothing (2026-11-06 risk review, finding 5: 4096 slots
// per column made 1000 boolean columns take about 100 MB more than the reference writer).
template <typename Format>
class TextCache {
  public:
    TextCache() = default;
    explicit TextCache(size_t rows) : rows_(rows) {}

    // Appends Format(value) to out; false (with a Python error set) on failure.
    bool append(double value, std::string& out) {
        if (keys_.empty()) allocate();
        uint64_t bits;
        std::memcpy(&bits, &value, sizeof bits);
        size_t slot = mix(bits) & (keys_.size() - 1);
        while (used_[slot]) {
            if (keys_[slot] == bits) {
                out.append(arena_, spans_[slot].first, spans_[slot].second);
                return true;
            }
            slot = (slot + 1) & (keys_.size() - 1);
        }
        text_.clear();
        if (!Format::format(value, text_)) return false;
        out += text_;
        if (count_ < kLimit) {
            keys_[slot] = bits;
            spans_[slot] = {arena_.size(), text_.size()};
            used_[slot] = 1;
            arena_ += text_;
            if (++count_ * 2 > keys_.size()) grow();
        }
        return true;
    }

  private:
    static constexpr size_t kLimit = 1 << 20;
    static constexpr size_t kInitial = 1 << 12;
    void allocate() {
        size_t size = 16;
        while (size < kInitial && (rows_ == 0 || size < 2 * rows_)) size <<= 1;
        keys_.assign(size, 0);
        spans_.assign(size, {});
        used_.assign(size, 0);
    }
    size_t rows_ = 0;  // 0: unknown, start at kInitial
    static uint64_t mix(uint64_t x) {
        x ^= x >> 33;
        x *= 0xff51afd7ed558ccdULL;
        x ^= x >> 33;
        return x;
    }
    void grow() {
        std::vector<uint64_t> keys(keys_.size() * 2);
        std::vector<std::pair<size_t, size_t>> spans(keys.size());
        std::vector<uint8_t> used(keys.size(), 0);
        for (size_t index = 0; index < keys_.size(); ++index) {
            if (!used_[index]) continue;
            size_t slot = mix(keys_[index]) & (keys.size() - 1);
            while (used[slot]) slot = (slot + 1) & (keys.size() - 1);
            keys[slot] = keys_[index];
            spans[slot] = spans_[index];
            used[slot] = 1;
        }
        keys_.swap(keys);
        spans_.swap(spans);
        used_.swap(used);
    }
    std::vector<uint64_t> keys_;
    std::vector<std::pair<size_t, size_t>> spans_;
    std::vector<uint8_t> used_;
    std::string arena_;
    std::string text_;
    size_t count_ = 0;
};

// float.__repr__.
struct Repr {
    static bool format(double value, std::string& out) {
        char* text = PyOS_double_to_string(value, 'r', 0, Py_DTSF_ADD_DOT_0, nullptr);
        if (!text) return false;
        out += text;
        PyMem_Free(text);
        return true;
    }
};

// canonical._canonical_float of a finite double, from its repr text.
struct CanonicalFloat {
    static bool format(double number, std::string& out) {
        if (number == 0.0) {
            out += '0';
            return true;
        }
        std::string text;
        if (!Repr::format(number, text)) return false;
        for (char& c : text) {
            if (c == 'E') c = 'e';
        }
        const bool negative = text.front() == '-';
        if (negative) text.erase(0, 1);
        const size_t exponent_at = text.find('e');
        const int exponent = exponent_at == std::string::npos ? 0 : std::stoi(text.substr(exponent_at + 1));
        const std::string mantissa = text.substr(0, exponent_at);
        const size_t dot_at = mantissa.find('.');
        const int integer_length = static_cast<int>(dot_at == std::string::npos ? mantissa.size() : dot_at);
        std::string digits = mantissa;
        if (dot_at != std::string::npos) digits.erase(dot_at, 1);
        const int position = integer_length + exponent;
        std::string rendered;
        const double magnitude = std::fabs(number);
        if (1e-6 <= magnitude && magnitude < 1e21) {
            if (position <= 0) {
                rendered = "0." + std::string(static_cast<size_t>(-position), '0') + digits;
            } else if (position >= static_cast<int>(digits.size())) {
                rendered = digits + std::string(static_cast<size_t>(position) - digits.size(), '0');
            } else {
                rendered = digits.substr(0, static_cast<size_t>(position)) + "." +
                           digits.substr(static_cast<size_t>(position));
            }
            if (rendered.find('.') != std::string::npos) {
                while (!rendered.empty() && rendered.back() == '0') rendered.pop_back();
                if (!rendered.empty() && rendered.back() == '.') rendered.pop_back();
            }
            if (rendered.empty()) rendered = "0";
        } else {
            rendered = digits.substr(0, 1);
            std::string trailing = digits.substr(1);
            while (!trailing.empty() && trailing.back() == '0') trailing.pop_back();
            if (!trailing.empty()) rendered += "." + trailing;
            const int power = position - 1;
            rendered += power >= 0 ? "e+" : "e-";
            rendered += std::to_string(power >= 0 ? power : -power);
        }
        if (negative) out += '-';
        out += rendered;
        return true;
    }
};

using ReprCache = TextCache<Repr>;

void append_int64(long long value, std::string& out) {
    char buffer[24];
    char* end = buffer + sizeof buffer;
    char* cursor = end;
    unsigned long long magnitude = value < 0 ? 0ULL - static_cast<unsigned long long>(value)
                                             : static_cast<unsigned long long>(value);
    do {
        *--cursor = static_cast<char>('0' + magnitude % 10);
        magnitude /= 10;
    } while (magnitude);
    if (value < 0) *--cursor = '-';
    out.append(cursor, static_cast<size_t>(end - cursor));
}

void append_uint64(unsigned long long value, std::string& out) {
    char buffer[24];
    char* end = buffer + sizeof buffer;
    char* cursor = end;
    do {
        *--cursor = static_cast<char>('0' + value % 10);
        value /= 10;
    } while (value);
    out.append(cursor, static_cast<size_t>(end - cursor));
}

// str(int): machine integers directly, anything larger through int.__repr__.
bool append_exact_int(PyObject* value, std::string& out) {
    int overflow = 0;
    const long long small = PyLong_AsLongLongAndOverflow(value, &overflow);
    if (!overflow) {
        if (small == -1 && PyErr_Occurred()) return false;
        append_int64(small, out);
        return true;
    }
    Owned text(PyLong_Type.tp_repr(value));
    if (!text) return false;
    Py_ssize_t length;
    const char* data = PyUnicode_AsUTF8AndSize(text.get(), &length);
    if (!data) return false;
    out.append(data, static_cast<size_t>(length));
    return true;
}

PyObject* bytes_of(const std::string& text) {
    return PyBytes_FromStringAndSize(text.data(), static_cast<Py_ssize_t>(text.size()));
}

// ---------------------------------------------------------------- JSON text (json.dumps)

struct JsonOptions {
    bool ensure_ascii;
    bool sort_keys;
    bool allow_nan;
    std::string indent;  // empty: no indentation
    bool indented;
    std::string item_separator;
    std::string key_separator;
};

const char HEX[] = "0123456789abcdef";

void append_escape_u(Py_UCS4 c, std::string& out) {
    out += "\\u";
    out += HEX[(c >> 12) & 0xf];
    out += HEX[(c >> 8) & 0xf];
    out += HEX[(c >> 4) & 0xf];
    out += HEX[c & 0xf];
}

// json's py_encode_basestring(_ascii). Unsupported text (lone surrogates without
// ensure_ascii, which UTF-8 cannot hold) returns false without a Python error.
bool append_json_string(PyObject* text, const JsonOptions& options, std::string& out) {
    const Py_ssize_t length = PyUnicode_GET_LENGTH(text);
    const int kind = PyUnicode_KIND(text);
    const void* data = PyUnicode_DATA(text);
    out += '"';
    if (PyUnicode_IS_ASCII(text)) {
        const Py_UCS1* chars = PyUnicode_1BYTE_DATA(text);
        for (Py_ssize_t index = 0; index < length; ++index) {
            const Py_UCS1 c = chars[index];
            switch (c) {
                case '"': out += "\\\""; break;
                case '\\': out += "\\\\"; break;
                case '\b': out += "\\b"; break;
                case '\f': out += "\\f"; break;
                case '\n': out += "\\n"; break;
                case '\r': out += "\\r"; break;
                case '\t': out += "\\t"; break;
                default:
                    if (c < 0x20 || (options.ensure_ascii && c == 0x7f)) append_escape_u(c, out);
                    else out += static_cast<char>(c);
            }
        }
        out += '"';
        return true;
    }
    for (Py_ssize_t index = 0; index < length; ++index) {
        const Py_UCS4 c = PyUnicode_READ(kind, data, index);
        switch (c) {
            case '"': out += "\\\""; continue;
            case '\\': out += "\\\\"; continue;
            case '\b': out += "\\b"; continue;
            case '\f': out += "\\f"; continue;
            case '\n': out += "\\n"; continue;
            case '\r': out += "\\r"; continue;
            case '\t': out += "\\t"; continue;
            default: break;
        }
        if (c < 0x20) {
            append_escape_u(c, out);
        } else if (options.ensure_ascii) {
            if (c < 0x7f) {
                out += static_cast<char>(c);
            } else if (c >= 0x10000) {
                const Py_UCS4 v = c - 0x10000;
                append_escape_u(0xd800 | ((v >> 10) & 0x3ff), out);
                append_escape_u(0xdc00 | (v & 0x3ff), out);
            } else {
                append_escape_u(c, out);
            }
        } else if (c < 0x80) {
            out += static_cast<char>(c);
        } else if (c < 0x800) {
            out += static_cast<char>(0xc0 | (c >> 6));
            out += static_cast<char>(0x80 | (c & 0x3f));
        } else if (c < 0x10000) {
            if (c >= 0xd800 && c <= 0xdfff) return false;
            out += static_cast<char>(0xe0 | (c >> 12));
            out += static_cast<char>(0x80 | ((c >> 6) & 0x3f));
            out += static_cast<char>(0x80 | (c & 0x3f));
        } else {
            out += static_cast<char>(0xf0 | (c >> 18));
            out += static_cast<char>(0x80 | ((c >> 12) & 0x3f));
            out += static_cast<char>(0x80 | ((c >> 6) & 0x3f));
            out += static_cast<char>(0x80 | (c & 0x3f));
        }
    }
    out += '"';
    return true;
}

enum class Step { ok, unsupported, error };

class JsonWriter {
  public:
    explicit JsonWriter(JsonOptions options) : options_(std::move(options)) {}

    Step write(PyObject* value, int depth) {
        if (value == Py_None) { out_ += "null"; return Step::ok; }
        if (value == Py_True) { out_ += "true"; return Step::ok; }
        if (value == Py_False) { out_ += "false"; return Step::ok; }
        PyTypeObject* type = Py_TYPE(value);
        if (type == &PyUnicode_Type) {
            return append_json_string(value, options_, out_) ? Step::ok : Step::unsupported;
        }
        if (type == &PyLong_Type) return append_exact_int(value, out_) ? Step::ok : Step::error;
        if (type == &PyFloat_Type) return write_float(PyFloat_AS_DOUBLE(value));
        if (depth >= MAX_DEPTH) return Step::unsupported;
        if (type == &PyList_Type || type == &PyTuple_Type) return write_sequence(value, depth);
        if (type == &PyDict_Type) return write_dict(value, depth);
        return Step::unsupported;
    }

    std::string& text() { return out_; }

  private:
    Step write_float(double number) {
        if (std::isfinite(number)) return floats_.append(number, out_) ? Step::ok : Step::error;
        if (!options_.allow_nan) return Step::unsupported;
        out_ += std::isnan(number) ? "NaN" : number > 0 ? "Infinity" : "-Infinity";
        return Step::ok;
    }

    void newline(int level) {
        out_ += '\n';
        for (int index = 0; index < level; ++index) out_ += options_.indent;
    }

    bool enter(PyObject* container) {
        for (PyObject* open : open_) {
            if (open == container) return false;  // json raises "Circular reference detected"
        }
        open_.push_back(container);
        return true;
    }

    Step write_sequence(PyObject* value, int depth) {
        const bool is_list = PyList_CheckExact(value);
        Py_ssize_t count = is_list ? PyList_GET_SIZE(value) : PyTuple_GET_SIZE(value);
        if (count == 0) { out_ += "[]"; return Step::ok; }
        if (!enter(value)) return Step::unsupported;
        out_ += '[';
        for (Py_ssize_t index = 0; index < count; ++index) {
            // A list cannot change size here: no Python code runs while it is written.
            PyObject* item = is_list ? PyList_GET_ITEM(value, index) : PyTuple_GET_ITEM(value, index);
            if (index) out_ += options_.item_separator;
            if (options_.indented) newline(depth + 1);
            const Step step = write(item, depth + 1);
            if (step != Step::ok) return step;
        }
        if (options_.indented) newline(depth);
        out_ += ']';
        open_.pop_back();
        return Step::ok;
    }

    Step write_dict(PyObject* value, int depth) {
        if (PyDict_GET_SIZE(value) == 0) { out_ += "{}"; return Step::ok; }
        if (!enter(value)) return Step::unsupported;
        std::vector<std::pair<PyObject*, PyObject*>> items;
        items.reserve(static_cast<size_t>(PyDict_GET_SIZE(value)));
        Py_ssize_t position = 0;
        PyObject* key;
        PyObject* item;
        while (PyDict_Next(value, &position, &key, &item)) {
            if (!PyUnicode_CheckExact(key)) return Step::unsupported;
            items.emplace_back(key, item);
        }
        if (options_.sort_keys) {
            // Sorting (key, value) pairs of distinct str keys is sorting by code point.
            std::stable_sort(items.begin(), items.end(), [](const auto& left, const auto& right) {
                return PyUnicode_Compare(left.first, right.first) < 0;
            });
        }
        out_ += '{';
        bool first = true;
        for (const auto& [name, entry] : items) {
            if (!first) out_ += options_.item_separator;
            first = false;
            if (options_.indented) newline(depth + 1);
            if (!append_json_string(name, options_, out_)) return Step::unsupported;
            out_ += options_.key_separator;
            const Step step = write(entry, depth + 1);
            if (step != Step::ok) return step;
        }
        if (options_.indented) newline(depth);
        out_ += '}';
        open_.pop_back();
        return Step::ok;
    }

    JsonOptions options_;
    std::string out_;
    ReprCache floats_;
    std::vector<PyObject*> open_;
};

bool text_argument(PyObject* value, std::string& out) {
    if (!PyUnicode_Check(value)) {
        PyErr_SetString(PyExc_TypeError, "expected str");
        return false;
    }
    Py_ssize_t length;
    const char* data = PyUnicode_AsUTF8AndSize(value, &length);
    if (!data) return false;
    out.assign(data, static_cast<size_t>(length));
    return true;
}

// encode_json(obj, indent, sort_keys, ensure_ascii, allow_nan, item_separator, key_separator)
// -> UTF-8 bytes of json.dumps(obj, ...), or None for a shape json.dumps must handle.
PyObject* encode_json(PyObject*, PyObject* args) {
    PyObject* value;
    PyObject* indent;
    int sort_keys, ensure_ascii, allow_nan;
    PyObject* item_separator;
    PyObject* key_separator;
    if (!PyArg_ParseTuple(args, "OOpppUU:encode_json", &value, &indent, &sort_keys, &ensure_ascii, &allow_nan,
                          &item_separator, &key_separator)) {
        return nullptr;
    }
    try {
        JsonOptions options{ensure_ascii != 0, sort_keys != 0, allow_nan != 0, "", indent != Py_None, "", ""};
        if (options.indented && !text_argument(indent, options.indent)) return nullptr;
        if (!text_argument(item_separator, options.item_separator)) return nullptr;
        if (!text_argument(key_separator, options.key_separator)) return nullptr;
        JsonWriter writer(std::move(options));
        const Step step = writer.write(value, 0);
        if (step == Step::error) return nullptr;
        if (step == Step::unsupported) {
            PyErr_Clear();
            Py_RETURN_NONE;
        }
        return bytes_of(writer.text());
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

// ---------------------------------------------------------------- json_safe (model families)

PyObject* json_safe_dict(PyObject* value, PyObject* fallback, int depth);
PyObject* json_safe_list(PyObject* value, PyObject* fallback, int depth);

// The model-family runtime's _json_safe for exact builtins; every other value goes to the
// reference itself (`fallback`), which is what the reference does for it.
PyObject* json_safe_value(PyObject* value, PyObject* fallback, int depth) {
    PyTypeObject* type = Py_TYPE(value);
    if (type == &PyFloat_Type) {
        if (std::isfinite(PyFloat_AS_DOUBLE(value))) return Py_NewRef(value);
        Py_RETURN_NONE;
    }
    if (type == &PyUnicode_Type || type == &PyLong_Type || type == &PyBool_Type || value == Py_None) {
        return Py_NewRef(value);
    }
    if (depth < MAX_DEPTH && (type == &PyDict_Type || type == &PyList_Type)) {
        if (Py_EnterRecursiveCall(" in json_safe")) return nullptr;
        PyObject* result = type == &PyDict_Type ? json_safe_dict(value, fallback, depth)
                                                : json_safe_list(value, fallback, depth);
        Py_LeaveRecursiveCall();
        return result;
    }
    return PyObject_CallOneArg(fallback, value);
}

PyObject* json_safe_dict(PyObject* value, PyObject* fallback, int depth) {
    Owned out(PyDict_New());
    if (!out) return nullptr;
    // Iterate a snapshot: the fallback may run Python code.
    Owned items(PyDict_Items(value));
    if (!items) return nullptr;
    const Py_ssize_t count = PyList_GET_SIZE(items.get());
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* pair = PyList_GET_ITEM(items.get(), index);
        PyObject* key = PyTuple_GET_ITEM(pair, 0);
        Owned name(PyUnicode_CheckExact(key) ? Py_NewRef(key) : PyObject_Str(key));
        if (!name) return nullptr;
        Owned converted(json_safe_value(PyTuple_GET_ITEM(pair, 1), fallback, depth + 1));
        if (!converted || PyDict_SetItem(out.get(), name.get(), converted.get()) < 0) return nullptr;
    }
    return out.release();
}

PyObject* json_safe_list(PyObject* value, PyObject* fallback, int depth) {
    // The fallback may resize the list: read it by index under a size check, like the
    // reference's comprehension, which iterates the live list.
    Owned out(PyList_New(0));
    if (!out) return nullptr;
    for (Py_ssize_t index = 0; index < PyList_GET_SIZE(value); ++index) {
        Owned item(Py_NewRef(PyList_GET_ITEM(value, index)));
        Owned converted(json_safe_value(item.get(), fallback, depth + 1));
        if (!converted || PyList_Append(out.get(), converted.get()) < 0) return nullptr;
    }
    return out.release();
}

PyObject* json_safe(PyObject*, PyObject* args) {
    PyObject* value;
    PyObject* fallback;
    if (!PyArg_ParseTuple(args, "OO:json_safe", &value, &fallback)) return nullptr;
    return json_safe_value(value, fallback, 0);
}

// ---------------------------------------------------------------- canonical-v1 lists

enum ListKind { kOther = 0, kPlainStrings = 1, kFiniteNumbers = 2 };

// Classifies a list/tuple the way canonical._normalize does, answering only the clean
// cases: 1 for _plain_string_list, 2 for an exact int/float list that math.isfinite
// accepts (ints within double range). 0 sends the list to the reference code.
int list_kind(PyObject* values) {
    const bool is_list = PyList_CheckExact(values);
    if (!is_list && !PyTuple_CheckExact(values)) return kOther;
    const Py_ssize_t count = is_list ? PyList_GET_SIZE(values) : PyTuple_GET_SIZE(values);
    if (count == 0) return kOther;
    PyObject* first = is_list ? PyList_GET_ITEM(values, 0) : PyTuple_GET_ITEM(values, 0);
    if (PyUnicode_CheckExact(first)) {
        for (Py_ssize_t index = 0; index < count; ++index) {
            PyObject* item = is_list ? PyList_GET_ITEM(values, index) : PyTuple_GET_ITEM(values, index);
            if (!PyUnicode_CheckExact(item) || !PyUnicode_IS_ASCII(item)) return kOther;
            const Py_UCS1* chars = PyUnicode_1BYTE_DATA(item);
            for (Py_ssize_t offset = 0, length = PyUnicode_GET_LENGTH(item); offset < length; ++offset) {
                const Py_UCS1 c = chars[offset];
                if (c < 0x20 || c > 0x7e || c == '"' || c == '\\') return kOther;
            }
        }
        return kPlainStrings;
    }
    for (Py_ssize_t index = 0; index < count; ++index) {
        PyObject* item = is_list ? PyList_GET_ITEM(values, index) : PyTuple_GET_ITEM(values, index);
        if (PyFloat_CheckExact(item)) {
            if (!std::isfinite(PyFloat_AS_DOUBLE(item))) return kOther;
        } else if (PyLong_CheckExact(item)) {
            int overflow = 0;
            PyLong_AsLongLongAndOverflow(item, &overflow);
            if (overflow) return kOther;  // math.isfinite may raise OverflowError: reference path
        } else {
            return kOther;
        }
    }
    return kFiniteNumbers;
}

PyObject* canonical_list_kind(PyObject*, PyObject* values) {
    return PyLong_FromLong(list_kind(values));
}

// canonical text of a list that is all exact float or all exact int (finite, int64), or of
// a plain-string list; None otherwise (mixed int/float lists keep the reference's cache).
PyObject* canonical_list(PyObject*, PyObject* values) {
    try {
        const int kind = list_kind(values);
        if (kind == kOther) Py_RETURN_NONE;
        const bool is_list = PyList_CheckExact(values);
        const Py_ssize_t count = is_list ? PyList_GET_SIZE(values) : PyTuple_GET_SIZE(values);
        const auto item_at = [values, is_list](Py_ssize_t index) {
            return is_list ? PyList_GET_ITEM(values, index) : PyTuple_GET_ITEM(values, index);
        };
        std::string out;
        if (kind == kPlainStrings) {
            Py_ssize_t total = 2;
            for (Py_ssize_t index = 0; index < count; ++index) total += PyUnicode_GET_LENGTH(item_at(index)) + 3;
            out.reserve(static_cast<size_t>(total));
            out += '[';
            for (Py_ssize_t index = 0; index < count; ++index) {
                PyObject* item = item_at(index);
                if (index) out += ',';
                out += '"';
                out.append(reinterpret_cast<const char*>(PyUnicode_1BYTE_DATA(item)),
                           static_cast<size_t>(PyUnicode_GET_LENGTH(item)));
                out += '"';
            }
            out += ']';
            return PyUnicode_DecodeASCII(out.data(), static_cast<Py_ssize_t>(out.size()), nullptr);
        }
        const bool floats = PyFloat_CheckExact(item_at(0));
        for (Py_ssize_t index = 0; index < count; ++index) {
            if (PyFloat_CheckExact(item_at(index)) != floats) Py_RETURN_NONE;
        }
        out.reserve(static_cast<size_t>(count) * 8 + 2);
        out += '[';
        TextCache<CanonicalFloat> texts;
        for (Py_ssize_t index = 0; index < count; ++index) {
            PyObject* item = item_at(index);
            if (index) out += ',';
            if (floats) {
                if (!texts.append(PyFloat_AS_DOUBLE(item), out)) return nullptr;
            } else {
                append_int64(PyLong_AsLongLong(item), out);
            }
        }
        out += ']';
        return PyUnicode_DecodeASCII(out.data(), static_cast<Py_ssize_t>(out.size()), nullptr);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

// ---------------------------------------------------------------- CSV (pandas to_csv)

struct Column {
    char kind;  // f: float64, i: int64, u: uint64, b: bool, o: objects as csv.writer writes them
    Py_buffer buffer{};
    bool has_buffer = false;
    PyObject* objects = nullptr;  // borrowed list for kind o
};

struct Columns {
    std::vector<Column> items;
    ~Columns() {
        for (Column& column : items) {
            if (column.has_buffer) PyBuffer_Release(&column.buffer);
        }
    }
};

bool read_columns(PyObject* specs, Py_ssize_t rows, Columns& columns, const char* allowed) {
    if (!PyList_CheckExact(specs)) {
        PyErr_SetString(PyExc_TypeError, "columns must be a list");
        return false;
    }
    for (Py_ssize_t index = 0; index < PyList_GET_SIZE(specs); ++index) {
        PyObject* spec = PyList_GET_ITEM(specs, index);
        if (!PyTuple_CheckExact(spec) || PyTuple_GET_SIZE(spec) < 2) {
            PyErr_SetString(PyExc_TypeError, "each column is a (kind, values, ...) tuple");
            return false;
        }
        Py_ssize_t length;
        const char* kind = PyUnicode_AsUTF8AndSize(PyTuple_GET_ITEM(spec, 0), &length);
        if (!kind) return false;
        if (length != 1 || !std::strchr(allowed, kind[0])) {
            PyErr_SetString(PyExc_ValueError, "unknown column kind");
            return false;
        }
        columns.items.emplace_back();
        Column& column = columns.items.back();
        column.kind = kind[0];
        PyObject* values = PyTuple_GET_ITEM(spec, 1);
        if (column.kind == 'o' || column.kind == 's') {
            if (!PyList_CheckExact(values) || PyList_GET_SIZE(values) != rows) {
                PyErr_SetString(PyExc_ValueError, "object column must be a list with one item per row");
                return false;
            }
            column.objects = values;
            continue;
        }
        if (PyObject_GetBuffer(values, &column.buffer, PyBUF_C_CONTIGUOUS) < 0) return false;
        column.has_buffer = true;
        const Py_ssize_t width = column.kind == 'b' ? 1 : column.kind == 'l' ? 4 : 8;
        if (column.buffer.len != rows * width) {
            PyErr_SetString(PyExc_ValueError, "column buffer does not hold one value per row");
            return false;
        }
    }
    return true;
}

// csv.writer QUOTE_MINIMAL with delimiter ',', quotechar '"', doublequote, no escapechar.
void append_csv_field(const char* data, size_t length, const std::string& terminator, std::string& out) {
    bool quote = false;
    for (size_t index = 0; index < length && !quote; ++index) {
        const char c = data[index];
        quote = c == ',' || c == '"' || c == '\n' || c == '\r' || terminator.find(c) != std::string::npos;
    }
    if (!quote) {
        out.append(data, length);
        return;
    }
    out += '"';
    for (size_t index = 0; index < length; ++index) {
        if (data[index] == '"') out += '"';
        out += data[index];
    }
    out += '"';
}

// The text csv.writer writes for one object: None is empty, a float (any float subclass)
// is its repr, anything else its str. Returns false with a Python error set.
bool csv_object_text(PyObject* value, std::string& out) {
    if (value == Py_None) return true;
    if (PyUnicode_CheckExact(value)) {
        Py_ssize_t length;
        const char* data = PyUnicode_AsUTF8AndSize(value, &length);
        if (!data) return false;
        out.append(data, static_cast<size_t>(length));
        return true;
    }
    Owned text(PyFloat_Check(value) ? PyObject_Repr(value) : PyObject_Str(value));
    if (!text) return false;
    Py_ssize_t length;
    const char* data = PyUnicode_AsUTF8AndSize(text.get(), &length);
    if (!data) return false;
    out.append(data, static_cast<size_t>(length));
    return true;
}

// csv_rows(columns, start, stop, rows, lineterminator) -> bytes of rows [start, stop).
// The body pandas.DataFrame.to_csv(index=False) writes with its default dialect.
PyObject* csv_rows(PyObject*, PyObject* args) {
    PyObject* specs;
    Py_ssize_t start, stop, rows;
    PyObject* terminator_object;
    if (!PyArg_ParseTuple(args, "OnnnU:csv_rows", &specs, &start, &stop, &rows, &terminator_object)) return nullptr;
    if (start < 0 || stop < start || stop > rows) {
        PyErr_SetString(PyExc_ValueError, "row range outside the columns");
        return nullptr;
    }
    try {
        std::string terminator;
        if (!text_argument(terminator_object, terminator)) return nullptr;
        Columns columns;
        if (!read_columns(specs, rows, columns, "fiubo")) return nullptr;
        std::vector<ReprCache> reprs(columns.items.size(), ReprCache(static_cast<size_t>(stop - start)));
        std::string out;
        std::string field;
        out.reserve(static_cast<size_t>(stop - start) * (columns.items.size() * 8 + terminator.size()));
        for (Py_ssize_t row = start; row < stop; ++row) {
            const size_t record_start = out.size();
            for (size_t index = 0; index < columns.items.size(); ++index) {
                const Column& column = columns.items[index];
                if (index) out += ',';
                switch (column.kind) {
                    case 'f': {
                        const double number = static_cast<const double*>(column.buffer.buf)[row];
                        if (std::isnan(number)) break;  // na_rep ''
                        if (!reprs[index].append(number, out)) return nullptr;
                        break;
                    }
                    case 'i': append_int64(static_cast<const int64_t*>(column.buffer.buf)[row], out); break;
                    case 'u': append_uint64(static_cast<const uint64_t*>(column.buffer.buf)[row], out); break;
                    case 'b': out += static_cast<const uint8_t*>(column.buffer.buf)[row] ? "True" : "False"; break;
                    default: {
                        field.clear();
                        if (!csv_object_text(PyList_GET_ITEM(column.objects, row), field)) return nullptr;
                        append_csv_field(field.data(), field.size(), terminator, out);
                    }
                }
            }
            if (out.size() == record_start) out += "\"\"";  // a lone empty field is written quoted
            out += terminator;
        }
        return bytes_of(out);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

// ---------------------------------------------------------------- Stata .dta rows (ReadStat)

constexpr uint64_t DTA_MISSING_DOUBLE = 0x7fe0000000000000ULL;
constexpr uint32_t DTA_MISSING_LONG = 0x7fffffe5U;
constexpr double DTA_MAX_DOUBLE = 8.988465674311579e+307;  // 0x7fdfffffffffffff
constexpr int32_t DTA_MAX_LONG = 2147483620;

// utf8_extent(values) -> (longest UTF-8 byte length, its position) over exact str items,
// (-1, -1) when all are None; None if any other item appears or a str is not UTF-8 encodable.
PyObject* utf8_extent(PyObject*, PyObject* values) {
    if (!PyList_CheckExact(values)) {
        PyErr_SetString(PyExc_TypeError, "values must be a list");
        return nullptr;
    }
    Py_ssize_t longest = -1, at = -1;
    for (Py_ssize_t index = 0; index < PyList_GET_SIZE(values); ++index) {
        PyObject* item = PyList_GET_ITEM(values, index);
        if (item == Py_None) continue;
        if (!PyUnicode_CheckExact(item)) Py_RETURN_NONE;
        Py_ssize_t length;
        const char* data = PyUnicode_AsUTF8AndSize(item, &length);
        if (!data) {
            PyErr_Clear();
            Py_RETURN_NONE;
        }
        if (length > longest) {
            longest = length;
            at = index;
        }
    }
    return Py_BuildValue("nn", longest, at);
}

// dta_rows(columns, start, stop, rows) -> the data-section bytes of rows [start, stop):
// d = float64 (NaN is Stata's ".", larger than Stata's maximum raises), l = int32 with a
// bool missing mask (None: none missing), s = list of str/None with its storage width.
PyObject* dta_rows(PyObject*, PyObject* args) {
    PyObject* specs;
    Py_ssize_t start, stop, rows;
    if (!PyArg_ParseTuple(args, "Onnn:dta_rows", &specs, &start, &stop, &rows)) return nullptr;
    if (start < 0 || stop < start || stop > rows) {
        PyErr_SetString(PyExc_ValueError, "row range outside the columns");
        return nullptr;
    }
    try {
        Columns columns;
        if (!read_columns(specs, rows, columns, "dls")) return nullptr;
        std::vector<Py_buffer> masks(columns.items.size());
        std::vector<bool> has_mask(columns.items.size(), false);
        std::vector<size_t> widths(columns.items.size(), 0);
        struct Release {
            std::vector<Py_buffer>& buffers;
            std::vector<bool>& held;
            ~Release() {
                for (size_t index = 0; index < buffers.size(); ++index) {
                    if (held[index]) PyBuffer_Release(&buffers[index]);
                }
            }
        } release{masks, has_mask};
        size_t row_width = 0;
        for (size_t index = 0; index < columns.items.size(); ++index) {
            PyObject* spec = PyList_GET_ITEM(specs, static_cast<Py_ssize_t>(index));
            const char kind = columns.items[index].kind;
            if (kind == 'l' && PyTuple_GET_SIZE(spec) > 2 && PyTuple_GET_ITEM(spec, 2) != Py_None) {
                if (PyObject_GetBuffer(PyTuple_GET_ITEM(spec, 2), &masks[index], PyBUF_C_CONTIGUOUS) < 0) return nullptr;
                has_mask[index] = true;
                if (masks[index].len != rows) {
                    PyErr_SetString(PyExc_ValueError, "missing mask does not hold one flag per row");
                    return nullptr;
                }
            }
            if (kind == 's') {
                if (PyTuple_GET_SIZE(spec) < 3) {
                    PyErr_SetString(PyExc_ValueError, "a string column needs its width");
                    return nullptr;
                }
                const Py_ssize_t width = PyLong_AsSsize_t(PyTuple_GET_ITEM(spec, 2));
                if (width < 1 || width > 2045) {
                    if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "string width outside 1..2045");
                    return nullptr;
                }
                widths[index] = static_cast<size_t>(width);
            } else {
                widths[index] = kind == 'd' ? 8 : 4;
            }
            row_width += widths[index];
        }
        const size_t count = static_cast<size_t>(stop - start);
        Owned output(PyBytes_FromStringAndSize(nullptr, static_cast<Py_ssize_t>(count * row_width)));
        if (!output) return nullptr;
        char* cursor = PyBytes_AS_STRING(output.get());
        std::memset(cursor, 0, count * row_width);
        for (Py_ssize_t row = start; row < stop; ++row) {
            for (size_t index = 0; index < columns.items.size(); ++index) {
                const Column& column = columns.items[index];
                if (column.kind == 'd') {
                    const double number = static_cast<const double*>(column.buffer.buf)[row];
                    if (std::isnan(number)) {
                        std::memcpy(cursor, &DTA_MISSING_DOUBLE, 8);
                    } else if (number > DTA_MAX_DOUBLE) {
                        PyErr_SetString(PyExc_OverflowError, "value above Stata's largest double");
                        return nullptr;
                    } else {
                        std::memcpy(cursor, &number, 8);
                    }
                } else if (column.kind == 'l') {
                    if (has_mask[index] && static_cast<const uint8_t*>(masks[index].buf)[row]) {
                        std::memcpy(cursor, &DTA_MISSING_LONG, 4);
                    } else {
                        const int32_t number = static_cast<const int32_t*>(column.buffer.buf)[row];
                        if (number > DTA_MAX_LONG) {
                            PyErr_SetString(PyExc_OverflowError, "value above Stata's largest long");
                            return nullptr;
                        }
                        std::memcpy(cursor, &number, 4);
                    }
                } else {
                    PyObject* item = PyList_GET_ITEM(column.objects, row);
                    if (item != Py_None) {
                        if (!PyUnicode_CheckExact(item)) {
                            PyErr_SetString(PyExc_TypeError, "string column holds a non-str value");
                            return nullptr;
                        }
                        Py_ssize_t length;
                        const char* data = PyUnicode_AsUTF8AndSize(item, &length);
                        if (!data) return nullptr;
                        if (static_cast<size_t>(length) > widths[index]) {
                            PyErr_SetString(PyExc_ValueError, "string longer than its storage width");
                            return nullptr;
                        }
                        // strncpy: stop at the first NUL; the rest of the field stays zero.
                        const void* nul = std::memchr(data, '\0', static_cast<size_t>(length));
                        const size_t copied = nul ? static_cast<size_t>(static_cast<const char*>(nul) - data)
                                                  : static_cast<size_t>(length);
                        std::memcpy(cursor, data, copied);
                    }
                }
                cursor += widths[index];
            }
        }
        return output.release();
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

PyMethodDef methods[] = {
    {"encode_json", encode_json, METH_VARARGS, "UTF-8 bytes of json.dumps, or None for a shape it must handle."},
    {"json_safe", json_safe, METH_VARARGS, "The model-family _json_safe over exact builtins."},
    {"canonical_list_kind", canonical_list_kind, METH_O, "1 plain strings, 2 finite numbers, 0 reference path."},
    {"canonical_list", canonical_list, METH_O, "Canonical-v1 text of a homogeneous list, or None."},
    {"csv_rows", csv_rows, METH_VARARGS, "CSV body rows as pandas to_csv writes them."},
    {"utf8_extent", utf8_extent, METH_O, "Longest UTF-8 length among str items, or None."},
    {"dta_rows", dta_rows, METH_VARARGS, "Stata .dta data-section rows as ReadStat writes them."},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef definition = {
    PyModuleDef_HEAD_INIT, "_arboris_io", "Byte-identical output encoders.", -1, methods,
    nullptr, nullptr, nullptr, nullptr,
};

}  // namespace

PyMODINIT_FUNC PyInit__arboris_io() {
    Owned module(PyModule_Create(&definition));
    if (!module) return nullptr;
    if (PyModule_AddIntConstant(module.get(), "ABI_VERSION", ABI_VERSION) < 0) return nullptr;
    return module.release();
}
