#pragma once

namespace random_forest {

using cart::Status;
using cart_regression::Node;

constexpr std::size_t max_trees = 32;
constexpr std::size_t node_budget = 8191;
constexpr auto max_seed = std::numeric_limits<std::uint32_t>::max();
constexpr std::size_t header_width = 8;

struct ExhaustedRandomDraw {};

struct Random {
    std::uint64_t state;

    std::uint64_t next() {
        std::uint64_t mixed = (state += UINT64_C(0x9e3779b97f4a7c15));
        mixed = (mixed ^ (mixed >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
        mixed = (mixed ^ (mixed >> 27)) * UINT64_C(0x94d049bb133111eb);
        return mixed ^ (mixed >> 31);
    }

    std::size_t index(std::size_t bound) {
        const auto modulus = static_cast<std::uint64_t>(bound);
        const auto cutoff = (std::uint64_t{0} - modulus) % modulus;
        for (int retry = 0; retry < 16; ++retry) {
            const auto word = next();
            if (word >= cutoff) {
                return static_cast<std::size_t>(word % modulus);
            }
        }
        throw ExhaustedRandomDraw{};
    }
};

struct SampleFeatures {
    std::size_t count;
    Random random;

    std::size_t operator()(std::size_t columns, std::size_t* selected) {
        cart_regression::AllFeatures{}(columns, selected);
        if (count < columns) {
            for (std::size_t i = 0; i < count; ++i) {
                std::swap(selected[i], selected[i + random.index(columns - i)]);
            }
            std::sort(selected, selected + count);
        }
        return count;
    }
};

struct Specification {
    std::size_t trees;
    std::size_t rows;
    std::size_t depth;
    std::size_t minimum_leaf;
    std::size_t features;
    std::uint32_t seed;
};

bool within_budget(Specification spec, std::size_t columns) {
    if (spec.trees > max_trees || spec.depth > cart::max_depth || !cart::valid_shape(spec.rows, columns, 1)) {
        return false;
    }
    const std::size_t tree_work = spec.rows * spec.depth * (spec.features * cart::sort_levels(spec.rows) + 1);
    return spec.trees <= cart::work_budget / tree_work;
}

std::size_t per_tree_nodes(Specification spec) {
    return std::min(2 * (spec.rows / spec.minimum_leaf) - 1, (std::size_t{1} << (spec.depth + 1)) - 1);
}

template <class Value>
Status average(std::size_t size, Value at_index, double& result, Checkpoint* checkpoint = nullptr) {
    double minimum = at_index(0), maximum = minimum;
    for (std::size_t i = 1; i < size; ++i) {
        if (checkpoint && i % 4096 == 0 && !checkpoint->poll()) {
            return Status::interrupted;
        }
        const double value = at_index(i);
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
    }
    if (minimum == maximum) {
        result = minimum == 0.0 ? 0.0 : minimum;
        return Status::ok;
    }
    const cart_regression::CenteredScale scale(minimum, maximum);
    Sum total;
    for (std::size_t i = 0; i < size; ++i) {
        if (checkpoint && i % 4096 == 0 && !checkpoint->poll()) {
            return Status::interrupted;
        }
        double value;
        if (!scale.difference(at_index(i), value)) {
            return Status::numerical;
        }
        total.add(value);
    }
    return scale.raw_mean(total.value(), size, result) ? Status::ok : Status::numerical;
}

bool read_specification(const char* packed, std::size_t columns, Specification& spec) {
    const auto in = [&](std::size_t index, std::size_t low, std::size_t high) {
        return cart::integer_in(at(packed, index), low, high);
    };
    if (!in(0, 1, max_trees) || !in(1, 2, cart::max_rows) || !in(2, 1, cart::max_depth)
        || !in(3, 1, static_cast<std::size_t>(at(packed, 1))) || !in(4, 1, columns)
        || !in(5, 0, max_seed) || !in(6, columns, columns)) {
        return false;
    }
    spec = {
        static_cast<std::size_t>(at(packed, 0)), static_cast<std::size_t>(at(packed, 1)),
        static_cast<std::size_t>(at(packed, 2)), static_cast<std::size_t>(at(packed, 3)),
        static_cast<std::size_t>(at(packed, 4)), static_cast<std::uint32_t>(at(packed, 5)),
    };
    return within_budget(spec, columns);
}

struct TreeSlice {
    const char* table;
    std::size_t size;
};

struct Forest {
    std::array<TreeSlice, max_trees> trees;
    std::size_t size;

    Status read(const char* packed, std::size_t bytes, std::size_t columns, Checkpoint& checkpoint) {
        const auto length = bytes / sizeof(double);
        if (bytes % sizeof(double) != 0 || length < header_width + 1 + cart_regression::stride
            || length > header_width + max_trees + node_budget * cart_regression::stride) {
            return Status::invalid_tree;
        }
        Specification spec{};
        if (!read_specification(packed, columns, spec) || !std::isfinite(at(packed, 7))) {
            return Status::invalid_tree;
        }
        size = spec.trees;
        std::size_t offset = header_width + size;
        if (offset > length) {
            return Status::invalid_tree;
        }
        std::size_t total_nodes = 0;
        for (std::size_t i = 0; i < size; ++i) {
            if (!cart::integer_in(at(packed, header_width + i), 1, per_tree_nodes(spec))) {
                return Status::invalid_tree;
            }
            const auto nodes = static_cast<std::size_t>(at(packed, header_width + i));
            total_nodes += nodes;
            if (total_nodes > node_budget || nodes > (length - offset) / cart_regression::stride) {
                return Status::invalid_tree;
            }
            const char* table = packed + offset * sizeof(double);
            const cart_regression::Tree tree{table, nodes, columns, checkpoint};
            const auto valid = tree.validate();
            if (valid != Status::ok) {
                return valid;
            }
            if (tree.field(0, cart_regression::count) != static_cast<double>(spec.rows)) {
                return Status::invalid_tree;
            }
            for (std::size_t node = 0; node < nodes; ++node) {
                if (tree.field(node, cart_regression::depth) > static_cast<double>(spec.depth)
                    || (tree.field(node, cart_regression::feature) == -1.0
                        && tree.field(node, cart_regression::count) < static_cast<double>(spec.minimum_leaf))) {
                    return Status::invalid_tree;
                }
            }
            trees[i] = {table, nodes};
            offset += nodes * cart_regression::stride;
        }
        return offset == length ? Status::ok : Status::invalid_tree;
    }

    Status score(const char* design, std::size_t columns, std::vector<double>& output, Checkpoint& checkpoint) const {
        const auto finite = cart::finite_design(design, output.size() * columns, checkpoint);
        if (finite != Status::ok) {
            return finite;
        }
        std::array<double, max_trees> leaves;
        for (std::size_t row = 0; row < output.size(); ++row) {
            if (row % 256 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            for (std::size_t i = 0; i < size; ++i) {
                const cart_regression::Tree tree{trees[i].table, trees[i].size, columns, checkpoint};
                leaves[i] = tree.predict_row(design, row);
            }
            const auto result = average(size, [&](std::size_t i) { return leaves[i]; }, output[row]);
            if (result != Status::ok) {
                return result;
            }
        }
        return checkpoint.poll() ? Status::ok : Status::interrupted;
    }
};

PyObject* raise_failure(Status status) {
    if (status == Status::invalid_data) {
        PyErr_SetString(PyExc_ValueError, "RANDOM_FOREST_INVALID_DATA: predictors and training outcome must be finite");
    } else if (status == Status::invalid_tree) {
        PyErr_SetString(PyExc_ValueError, "RANDOM_FOREST_INVALID_TREE: forest metadata or tree nodes are inconsistent");
    } else if (status == Status::numerical) {
        PyErr_SetString(PyExc_ValueError, "RANDOM_FOREST_NUMERICAL_RANGE: native tree or aggregate exceeded binary64 range");
    }
    return nullptr;
}

struct TrainingArguments {
    const char* design;
    const char* outcome;
    PyObject* callback;
    Specification spec;
    std::size_t columns;
};

bool training_arguments(PyObject* args, const char* signature, const char* prefix, TrainingArguments& result) {
    PyObject* design;
    PyObject* outcome;
    PyObject* seed_arg;
    PyObject* callback = Py_None;
    Py_ssize_t rows, columns, trees, depth, minimum_leaf, features;
    if (!PyArg_ParseTuple(args, signature,
                          &PyBytes_Type, &design, &PyBytes_Type, &outcome, &rows, &columns, &trees, &depth,
                          &minimum_leaf, &features, &seed_arg, &callback)) {
        return false;
    }
    const auto seed = PyLong_CheckExact(seed_arg) ? PyLong_AsUnsignedLongLong(seed_arg) : UINT64_MAX;
    bool boolean_option = false;
    for (Py_ssize_t index = 2; index <= 7; ++index) {
        boolean_option |= PyBool_Check(PyTuple_GET_ITEM(args, index));
    }
    if (rows < 2 || columns < 1 || trees < 1 || depth < 1 || minimum_leaf < 1 || minimum_leaf > rows
        || features < 1 || features > columns || boolean_option || seed > max_seed || PyErr_Occurred()) {
        PyErr_Clear();
        PyErr_Format(PyExc_ValueError, "%s_INVALID_OPTIONS: shape, seed, or forest options are invalid", prefix);
        return false;
    }
    const Specification spec{
        static_cast<std::size_t>(trees), static_cast<std::size_t>(rows), static_cast<std::size_t>(depth),
        static_cast<std::size_t>(minimum_leaf), static_cast<std::size_t>(features), static_cast<std::uint32_t>(seed),
    };
    const auto width = static_cast<std::size_t>(columns);
    if (!within_budget(spec, width)) {
        PyErr_Format(PyExc_ValueError, "%s_WORK_LIMIT: the requested forest exceeds the native work budget", prefix);
        return false;
    }
    if (PyBytes_GET_SIZE(design) != static_cast<Py_ssize_t>(spec.rows * width * sizeof(double))
        || PyBytes_GET_SIZE(outcome) != static_cast<Py_ssize_t>(spec.rows * sizeof(double))) {
        PyErr_Format(PyExc_ValueError, "%s_INVALID_DATA: buffers do not match the declared training shape", prefix);
        return false;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "Random forest checkpoint must be callable");
        return false;
    }
    result = {PyBytes_AS_STRING(design), PyBytes_AS_STRING(outcome), callback, spec, width};
    return true;
}

PyObject* fit(PyObject*, PyObject* args) {
    TrainingArguments input{};
    if (!training_arguments(args, "O!O!nnnnnnO|O:fit_random_forest_regression", "RANDOM_FOREST", input)) {
        return nullptr;
    }
    const auto spec = input.spec;
    const auto width = input.columns;
    try {
        const char* x = input.design;
        const char* y = input.outcome;
        std::vector<Node> nodes;
        nodes.reserve(std::min(node_budget, spec.trees * per_tree_nodes(spec)));
        std::array<double, max_trees> sizes{};
        Status status;
        bool limit = false;
        double baseline = 0.0;
        {
            Checkpoint checkpoint(input.callback);
            cart_regression::Trainer trainer{x, y, width, spec.depth, spec.minimum_leaf, checkpoint, {}, {}, {}, {}, {}};
            status = trainer.prepare(spec.rows);
            if (status == Status::ok) {
                status = average(spec.rows, [&](std::size_t i) { return at(y, i); }, baseline, &checkpoint);
            }
            Random forest{spec.seed};
            for (std::size_t i = 0; i < spec.trees && status == Status::ok; ++i) {
                Random bootstrap{forest.next()};
                SampleFeatures candidates{spec.features, Random{forest.next()}};
                status = trainer.run_sample([&](std::size_t) { return bootstrap.index(spec.rows); }, candidates);
                if (status != Status::ok) {
                    break;
                }
                if (trainer.nodes.size() > node_budget - nodes.size()) {
                    limit = true;
                    break;
                }
                sizes[i] = static_cast<double>(trainer.nodes.size());
                nodes.insert(nodes.end(), trainer.nodes.begin(), trainer.nodes.end());
            }
        }
        if (status != Status::ok) {
            return raise_failure(status);
        }
        if (limit) {
            PyErr_SetString(PyExc_ValueError, "RANDOM_FOREST_WORK_LIMIT: fitted forest exceeds its total node budget");
            return nullptr;
        }
        const double header[header_width]{
            static_cast<double>(spec.trees), static_cast<double>(spec.rows), static_cast<double>(spec.depth),
            static_cast<double>(spec.minimum_leaf), static_cast<double>(spec.features), static_cast<double>(spec.seed),
            static_cast<double>(width), baseline,
        };
        const auto bytes = sizeof(header) + spec.trees * sizeof(double) + nodes.size() * sizeof(Node);
        PyObject* packed = PyBytes_FromStringAndSize(nullptr, static_cast<Py_ssize_t>(bytes));
        if (packed) {
            char* destination = PyBytes_AS_STRING(packed);
            std::memcpy(destination, header, sizeof(header));
            std::memcpy(destination + sizeof(header), sizes.data(), spec.trees * sizeof(double));
            std::memcpy(destination + sizeof(header) + spec.trees * sizeof(double), nodes.data(), nodes.size() * sizeof(Node));
        }
        return packed;
    } catch (const ExhaustedRandomDraw&) {
        PyErr_SetString(PyExc_ValueError, "RANDOM_FOREST_RANDOM_RANGE: a bounded unbiased draw could not be generated");
        return nullptr;
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

struct ScoringArguments {
    const char* design;
    const char* packed;
    std::size_t rows;
    std::size_t columns;
    std::size_t bytes;
    PyObject* callback;
};

bool scoring_arguments(PyObject* args, const char* signature, const char* prefix, ScoringArguments& result) {
    PyObject* design;
    PyObject* packed;
    PyObject* callback = Py_None;
    Py_ssize_t rows, columns;
    if (!PyArg_ParseTuple(args, signature, &PyBytes_Type, &design, &rows, &columns,
                          &PyBytes_Type, &packed, &callback)) {
        return false;
    }
    if (rows < 1 || columns < 1) {
        PyErr_Format(PyExc_ValueError, "%s_INVALID_DATA: prediction shape must be positive", prefix);
        return false;
    }
    const auto count = static_cast<std::size_t>(rows), width = static_cast<std::size_t>(columns);
    if (!cart::valid_shape(count, width, 0)) {
        PyErr_Format(PyExc_ValueError, "%s_WORK_LIMIT: prediction exceeds the native shape limit", prefix);
        return false;
    }
    if (PyBytes_GET_SIZE(design) != static_cast<Py_ssize_t>(count * width * sizeof(double))) {
        PyErr_Format(PyExc_ValueError, "%s_INVALID_DATA: prediction buffer does not match its declared shape", prefix);
        return false;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "Random forest checkpoint must be callable");
        return false;
    }
    result = {PyBytes_AS_STRING(design), PyBytes_AS_STRING(packed), count, width,
              static_cast<std::size_t>(PyBytes_GET_SIZE(packed)), callback};
    return true;
}

PyObject* predict(PyObject*, PyObject* args) {
    ScoringArguments input{};
    if (!scoring_arguments(args, "O!nnO!|O:predict_random_forest_regression", "RANDOM_FOREST", input)) {
        return nullptr;
    }
    try {
        std::vector<double> output(input.rows);
        Status status;
        {
            Checkpoint checkpoint(input.callback);
            Forest forest{};
            status = forest.read(input.packed, input.bytes, input.columns, checkpoint);
            if (status == Status::ok) {
                status = forest.score(input.design, input.columns, output, checkpoint);
            }
        }
        if (status == Status::ok) {
            return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(output.data()), input.rows * sizeof(double));
        }
        return raise_failure(status);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

}
