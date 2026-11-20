#pragma once

namespace cart {

constexpr std::size_t max_rows = 100'000;
constexpr std::size_t max_columns = 64;
constexpr std::size_t max_values = 1'000'000;
constexpr std::size_t max_depth = 10;
constexpr std::size_t max_nodes = (1u << (max_depth + 1)) - 1;
constexpr std::size_t work_budget = 100'000'000;

enum Field : std::size_t { feature, threshold, left, right, depth, samples, positives, probability, gain, stride };
enum class Status { ok, invalid_data, invalid_labels, single_class, invalid_tree, numerical, interrupted };

using Count = unsigned long long;
using Wide = unsigned __int128;

struct Node {
    double fields[stride];
};

static_assert(sizeof(Node) == stride * sizeof(double));

struct Counts {
    std::size_t rows;
    std::size_t positive;
};

struct Cost {
    Count numerator;
    Count denominator;
};

Cost child_cost(Counts left, Counts right) {
    const Count l = left.rows, r = right.rows, lp = left.positive, rp = right.positive;
    return {lp * (l - lp) * r + rp * (r - rp) * l, l * r};
}

Wide improvement(Counts parent, Cost cost) {
    const Wide before = Wide(parent.positive) * (parent.rows - parent.positive) * cost.denominator;
    const Wide after = Wide(cost.numerator) * parent.rows;
    return before > after ? before - after : 0;
}

double split_gain(Counts parent, Cost cost, Wide delta) {
    return 2.0 * static_cast<double>(delta) / static_cast<double>(Wide(parent.rows) * parent.rows * cost.denominator);
}

double leaf_probability(Counts counts) {
    return static_cast<double>(counts.positive + 1) / static_cast<double>(counts.rows + 2);
}

double midpoint(double lower, double upper) {
    const double distance = upper - lower;
    const double cut = std::isfinite(distance) ? lower + 0.5 * distance : 0.5 * lower + 0.5 * upper;
    const double result = lower <= cut && cut < upper ? cut : lower;
    return result == 0.0 ? 0.0 : result;
}

Status finite_design(const char* values, std::size_t count, Checkpoint& checkpoint) {
    for (std::size_t index = 0; index < count; ++index) {
        if (index % 4096 == 0 && !checkpoint.poll()) {
            return Status::interrupted;
        }
        if (!std::isfinite(at(values, index))) {
            return Status::invalid_data;
        }
    }
    return Status::ok;
}

struct Entry {
    double value;
    std::size_t row;
};

struct Split {
    Cost cost{0, 0};
    Counts left{0, 0};
    Wide improvement = 0;
    std::size_t feature = 0;
    double threshold = 0.0;
};

struct AllFeatures {
    std::size_t operator()(std::size_t columns, std::size_t* selected) const {
        for (std::size_t i = 0; i < columns; ++i) {
            selected[i] = i;
        }
        return columns;
    }
};

struct Trainer {
    const char* design;
    const char* labels;
    std::size_t columns;
    std::size_t depth_limit;
    std::size_t minimum_leaf;
    Checkpoint& checkpoint;
    std::vector<std::size_t> rows;
    std::vector<Entry> ordered;
    std::vector<Node> nodes;

    template <class Features>
    Status find_split(std::size_t first, Counts parent, Split& best, Features& features) {
        const auto count = parent.rows;
        std::size_t selected[max_columns];
        const auto candidates = features(columns, selected);
        for (std::size_t candidate = 0; candidate < candidates; ++candidate) {
            const auto column = selected[candidate];
            for (std::size_t i = 0; i < count; ++i) {
                if (i % 4096 == 0 && !checkpoint.poll()) {
                    return Status::interrupted;
                }
                const auto row = rows[first + i];
                ordered[i] = {at(design, row * columns + column), row};
            }
            std::sort(ordered.begin(), ordered.begin() + count, [](const Entry& a, const Entry& b) {
                return a.value < b.value || (a.value == b.value && a.row < b.row);
            });
            std::size_t positive_left = 0;
            for (std::size_t i = 0; i + 1 < count; ++i) {
                if (i % 4096 == 0 && !checkpoint.poll()) {
                    return Status::interrupted;
                }
                positive_left += at(labels, ordered[i].row) == 1.0;
                const Counts left_counts{i + 1, positive_left};
                const Counts right_counts{count - left_counts.rows, parent.positive - positive_left};
                if (left_counts.rows < minimum_leaf || right_counts.rows < minimum_leaf
                    || ordered[i].value == ordered[i + 1].value) {
                    continue;
                }
                const Cost cost = child_cost(left_counts, right_counts);
                const Wide delta = improvement(parent, cost);
                // Exact comparisons retain the first candidate in predictor and threshold order on ties.
                if (delta && (!best.cost.denominator
                    || Wide(cost.numerator) * best.cost.denominator < Wide(best.cost.numerator) * cost.denominator)) {
                    best = {cost, left_counts, delta, column, midpoint(ordered[i].value, ordered[i + 1].value)};
                }
            }
        }
        return Status::ok;
    }

    template <class Features>
    Status grow(std::size_t first, Counts counts, std::size_t level, Features& features) {
        if (!checkpoint.poll()) {
            return Status::interrupted;
        }
        const std::size_t node = nodes.size();
        nodes.push_back({{-1.0, 0.0, -1.0, -1.0, static_cast<double>(level), static_cast<double>(counts.rows),
                          static_cast<double>(counts.positive), leaf_probability(counts), 0.0}});
        if (level == depth_limit || counts.rows < 2 * minimum_leaf
            || counts.positive == 0 || counts.positive == counts.rows) {
            return Status::ok;
        }
        Split split;
        const Status found = find_split(first, counts, split, features);
        if (found != Status::ok || !split.cost.denominator) {
            return found;
        }
        const auto begin = rows.begin() + first;
        const auto middle = std::partition(begin, begin + counts.rows, [&](std::size_t row) {
            return at(design, row * columns + split.feature) <= split.threshold;
        });
        if (middle != begin + split.left.rows) {
            return Status::numerical;
        }
        const std::size_t left_id = nodes.size();
        const Status grown_left = grow(first, split.left, level + 1, features);
        if (grown_left != Status::ok) {
            return grown_left;
        }
        const std::size_t right_id = nodes.size();
        const Status grown_right = grow(first + split.left.rows,
                                        {counts.rows - split.left.rows, counts.positive - split.left.positive}, level + 1, features);
        if (grown_right != Status::ok) {
            return grown_right;
        }
        auto& fields = nodes[node].fields;
        fields[feature] = static_cast<double>(split.feature);
        fields[threshold] = split.threshold;
        fields[left] = static_cast<double>(left_id);
        fields[right] = static_cast<double>(right_id);
        fields[gain] = split_gain(counts, split.cost, split.improvement);
        return Status::ok;
    }

    Status prepare(std::size_t count, std::size_t& positive) {
        const Status checked = finite_design(design, count * columns, checkpoint);
        if (checked != Status::ok) {
            return checked;
        }
        rows.resize(count);
        positive = 0;
        for (std::size_t i = 0; i < count; ++i) {
            if (i % 4096 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            const double label = at(labels, i);
            if (label != 0.0 && label != 1.0) {
                return Status::invalid_labels;
            }
            positive += label == 1.0;
            rows[i] = i;
        }
        if (positive == 0 || positive == count) {
            return Status::single_class;
        }
        ordered.resize(count);
        nodes.reserve(std::min(2 * (count / minimum_leaf) - 1, (std::size_t{1} << (depth_limit + 1)) - 1));
        return Status::ok;
    }

    template <class Draw, class Features>
    Status run_sample(Draw draw, Features& features) {
        std::size_t positive = 0;
        for (std::size_t i = 0; i < rows.size(); ++i) {
            if (i % 4096 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            rows[i] = draw(i);
            positive += at(labels, rows[i]) == 1.0;
        }
        nodes.clear();
        const auto status = grow(0, {rows.size(), positive}, 0, features);
        if (status != Status::ok) {
            return status;
        }
        return checkpoint.poll() ? Status::ok : Status::interrupted;
    }

    Status run(std::size_t count) {
        std::size_t positives = 0;
        const auto status = prepare(count, positives);
        if (status != Status::ok) {
            return status;
        }
        AllFeatures features;
        const auto grown = grow(0, {count, positives}, 0, features);
        return grown == Status::ok && !checkpoint.poll() ? Status::interrupted : grown;
    }
};

bool integer_in(double value, std::size_t low, std::size_t high) {
    return value >= static_cast<double>(low) && value <= static_cast<double>(high) && value == std::floor(value);
}

struct Tree {
    const char* packed;
    std::size_t nodes;
    std::size_t columns;
    Checkpoint& checkpoint;

    double field(std::size_t node, Field value) const {
        return at(packed, node * stride + value);
    }

    Status visit(std::size_t node, std::size_t level, std::size_t& end, Counts& counts) const {
        if (node >= nodes || level > max_depth) {
            return Status::invalid_tree;
        }
        if (node % 128 == 0 && !checkpoint.poll()) {
            return Status::interrupted;
        }
        const double samples_value = field(node, samples);
        const double positive_value = field(node, positives);
        if (field(node, depth) != static_cast<double>(level) || !integer_in(samples_value, 1, max_rows)
            || !integer_in(positive_value, 0, static_cast<std::size_t>(samples_value))) {
            return Status::invalid_tree;
        }
        counts = {static_cast<std::size_t>(samples_value), static_cast<std::size_t>(positive_value)};
        if (field(node, probability) != leaf_probability(counts)) {
            return Status::invalid_tree;
        }
        const double column = field(node, feature);
        const double l = field(node, left), r = field(node, right);
        const double cut = field(node, threshold), node_gain = field(node, gain);
        if (column == -1.0) {
            end = node + 1;
            return l == -1.0 && r == -1.0 && cut == 0.0 && node_gain == 0.0 ? Status::ok : Status::invalid_tree;
        }
        if (!integer_in(column, 0, columns - 1) || !std::isfinite(cut) || level == max_depth
            || l != static_cast<double>(node + 1) || !integer_in(r, node + 2, nodes - 1)) {
            return Status::invalid_tree;
        }
        Counts left_counts{}, right_counts{};
        std::size_t after_left = 0;
        const auto left_status = visit(node + 1, level + 1, after_left, left_counts);
        if (left_status != Status::ok) {
            return left_status;
        }
        if (r != static_cast<double>(after_left)) {
            return Status::invalid_tree;
        }
        const auto right_status = visit(after_left, level + 1, end, right_counts);
        if (right_status != Status::ok) {
            return right_status;
        }
        if (left_counts.rows + right_counts.rows != counts.rows
            || left_counts.positive + right_counts.positive != counts.positive) {
            return Status::invalid_tree;
        }
        const Cost cost = child_cost(left_counts, right_counts);
        const Wide delta = improvement(counts, cost);
        return delta && node_gain == split_gain(counts, cost, delta) ? Status::ok : Status::invalid_tree;
    }

    Status validate(bool allow_pure = false) const {
        std::size_t end = 0;
        Counts root{};
        const auto checked = visit(0, 0, end, root);
        if (checked != Status::ok) {
            return checked;
        }
        const bool both_classes = root.positive > 0 && root.positive < root.rows;
        return end == nodes && (allow_pure || both_classes) ? Status::ok : Status::invalid_tree;
    }

    double predict_row(const char* design, std::size_t row) const {
        std::size_t node = 0;
        while (field(node, feature) != -1.0) {
            const auto column = static_cast<std::size_t>(field(node, feature));
            const auto direction = at(design, row * columns + column) <= field(node, threshold) ? left : right;
            node = static_cast<std::size_t>(field(node, direction));
        }
        return field(node, probability);
    }

    Status score(const char* design, std::vector<double>& output) const {
        const auto valid = validate();
        if (valid != Status::ok) {
            return valid;
        }
        const auto finite = finite_design(design, output.size() * columns, checkpoint);
        if (finite != Status::ok) {
            return finite;
        }
        for (std::size_t row = 0; row < output.size(); ++row) {
            if (row % 512 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            output[row] = predict_row(design, row);
        }
        return checkpoint.poll() ? Status::ok : Status::interrupted;
    }
};

PyObject* failure(Status status) {
    switch (status) {
    case Status::invalid_data:
        PyErr_SetString(PyExc_ValueError, "CART_INVALID_DATA: native predictors must be finite");
        break;
    case Status::invalid_labels:
        PyErr_SetString(PyExc_ValueError, "CART_INVALID_LABELS: native labels must be exactly 0 or 1");
        break;
    case Status::single_class:
        PyErr_SetString(PyExc_ValueError, "CART_TRAIN_SINGLE_CLASS: training must contain both 0 and 1");
        break;
    case Status::invalid_tree:
        PyErr_SetString(PyExc_ValueError, "CART_INVALID_TREE: the node table is inconsistent");
        break;
    case Status::numerical:
        PyErr_SetString(PyExc_ValueError, "CART_NUMERICAL_RANGE: the split threshold did not reproduce its training partition");
        break;
    case Status::ok:
    case Status::interrupted:
        break;
    }
    return nullptr;
}

bool valid_shape(std::size_t rows, std::size_t columns, std::size_t extra) {
    return rows <= max_rows && columns <= max_columns && rows * (columns + extra) <= max_values;
}

std::size_t sort_levels(std::size_t rows) {
    std::size_t levels = 1;
    for (auto remaining = rows - 1; remaining > 0; remaining >>= 1) {
        ++levels;
    }
    return levels;
}

PyObject* fit(PyObject*, PyObject* args) {
    PyObject* design;
    PyObject* labels;
    PyObject* callback = Py_None;
    Py_ssize_t rows_arg, columns_arg, depth_arg, minimum_arg;
    if (!PyArg_ParseTuple(args, "O!O!nnnn|O:fit_cart", &PyBytes_Type, &design, &PyBytes_Type, &labels,
                          &rows_arg, &columns_arg, &depth_arg, &minimum_arg, &callback)) {
        return nullptr;
    }
    if (rows_arg < 2 || columns_arg < 1 || minimum_arg < 1 || minimum_arg > rows_arg || depth_arg < 1) {
        PyErr_SetString(PyExc_ValueError, "CART_INVALID_DATA: native shape, depth, or minimum leaf is invalid");
        return nullptr;
    }
    const auto rows = static_cast<std::size_t>(rows_arg), columns = static_cast<std::size_t>(columns_arg);
    const auto depth = static_cast<std::size_t>(depth_arg);
    if (!valid_shape(rows, columns, 1) || depth > max_depth
        || rows * columns * depth * sort_levels(rows) > work_budget) {
        PyErr_SetString(PyExc_ValueError, "CART_WORK_LIMIT: training shape or depth exceeds the native work budget");
        return nullptr;
    }
    if (PyBytes_GET_SIZE(design) != static_cast<Py_ssize_t>(rows * columns * sizeof(double))
        || PyBytes_GET_SIZE(labels) != static_cast<Py_ssize_t>(rows * sizeof(double))) {
        PyErr_SetString(PyExc_ValueError, "CART_INVALID_DATA: native buffers do not match the declared training shape");
        return nullptr;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "CART checkpoint must be callable");
        return nullptr;
    }
    try {
        const char* x = PyBytes_AS_STRING(design);
        const char* y = PyBytes_AS_STRING(labels);
        std::vector<Node> nodes;
        Status status;
        {
            Checkpoint checkpoint(callback);
            Trainer trainer{x, y, columns, depth, static_cast<std::size_t>(minimum_arg), checkpoint, {}, {}, {}};
            status = trainer.run(rows);
            nodes = std::move(trainer.nodes);
        }
        if (status == Status::ok) {
            return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(nodes.data()), nodes.size() * sizeof(Node));
        }
        return failure(status);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

PyObject* predict(PyObject*, PyObject* args) {
    PyObject* design;
    PyObject* nodes;
    PyObject* callback = Py_None;
    Py_ssize_t rows_arg, columns_arg;
    if (!PyArg_ParseTuple(args, "O!nnO!|O:predict_cart", &PyBytes_Type, &design, &rows_arg, &columns_arg,
                          &PyBytes_Type, &nodes, &callback)) {
        return nullptr;
    }
    if (rows_arg < 1 || columns_arg < 1) {
        PyErr_SetString(PyExc_ValueError, "CART_INVALID_DATA: native prediction shape must be positive");
        return nullptr;
    }
    const auto rows = static_cast<std::size_t>(rows_arg), columns = static_cast<std::size_t>(columns_arg);
    if (!valid_shape(rows, columns, 0)) {
        PyErr_SetString(PyExc_ValueError, "CART_WORK_LIMIT: prediction shape exceeds the native work budget");
        return nullptr;
    }
    if (PyBytes_GET_SIZE(design) != static_cast<Py_ssize_t>(rows * columns * sizeof(double))) {
        PyErr_SetString(PyExc_ValueError, "CART_INVALID_DATA: native buffers do not match the declared prediction shape");
        return nullptr;
    }
    const auto bytes = static_cast<std::size_t>(PyBytes_GET_SIZE(nodes));
    if (bytes == 0 || bytes % sizeof(Node) != 0 || bytes / sizeof(Node) > max_nodes) {
        PyErr_SetString(PyExc_ValueError, "CART_INVALID_TREE: node buffer size is invalid");
        return nullptr;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "CART checkpoint must be callable");
        return nullptr;
    }
    try {
        const char* x = PyBytes_AS_STRING(design);
        const char* packed = PyBytes_AS_STRING(nodes);
        std::vector<double> output(rows);
        Status status;
        {
            Checkpoint checkpoint(callback);
            const Tree tree{packed, bytes / sizeof(Node), columns, checkpoint};
            status = tree.score(x, output);
        }
        if (status == Status::ok) {
            return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(output.data()), rows * sizeof(double));
        }
        return failure(status);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

}  // namespace cart
