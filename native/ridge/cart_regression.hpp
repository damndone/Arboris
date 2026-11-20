#pragma once

namespace cart_regression {

using cart::Status;
enum Field : std::size_t { feature, threshold, left, right, depth, count, mean, mse, gain, stride };

struct Node {
    double fields[stride];
};

static_assert(sizeof(Node) == stride * sizeof(double));
constexpr double epsilon = std::numeric_limits<double>::epsilon();

struct CenteredScale {
    int exponent;
    double anchor;
    double span;

    CenteredScale(double lower, double upper) {
        std::frexp(std::max(std::abs(lower), std::abs(upper)), &exponent);
        const double lo = std::scalbn(lower, -exponent), hi = std::scalbn(upper, -exponent);
        const bool close = (lo > 0.0 && lo >= 0.5 * hi) || (hi < 0.0 && hi <= 0.5 * lo);
        anchor = close ? lo : 0.0;
        span = hi - lo;
    }

    bool difference(double value, double& result) const {
        const double scaled = std::scalbn(value, -exponent);
        if (value != 0.0 && std::abs(scaled) < std::numeric_limits<double>::min()
            && std::scalbn(scaled, exponent) != value) {
            return false;
        }
        result = scaled - anchor;
        return true;
    }

    bool raw_mean(double total, std::size_t size, double& result) const {
        if (anchor == 0.0) {
            int total_exponent;
            const double total_fraction = std::frexp(total, &total_exponent);
            result = std::scalbn(total_fraction / static_cast<double>(size), exponent + total_exponent);
        } else {
            result = std::scalbn(anchor + total / static_cast<double>(size), exponent);
        }
        return std::isfinite(result) && (result != 0.0 || (anchor == 0.0 && total == 0.0));
    }
};

using cart::AllFeatures;

struct Moments {
    double mean;
    double mse;
    double resolution;
    int exponent;
};

struct Split {
    double score = 0.0;
    double threshold = 0.0;
    std::size_t feature = 0;
    std::size_t left_count = 0;
};

struct Trainer {
    const char* design;
    const char* target;
    std::size_t columns;
    std::size_t depth_limit;
    std::size_t minimum_leaf;
    Checkpoint& checkpoint;
    std::vector<std::size_t> rows;
    std::vector<double> centered;
    std::vector<cart::Entry> ordered;
    std::vector<double> suffix;
    std::vector<Node> nodes;

    Status summarize(std::size_t first, std::size_t size, Moments& result) {
        double lower = at(target, rows[first]), upper = lower;
        for (std::size_t i = 1; i < size; ++i) {
            if (i % 4096 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            const double value = at(target, rows[first + i]);
            lower = std::min(lower, value);
            upper = std::max(upper, value);
        }
        if (lower == upper) {
            result = {lower == 0.0 ? 0.0 : lower, 0.0, 0.0, 0};
            return Status::ok;
        }
        const CenteredScale scale(lower, upper);
        Sum total;
        for (std::size_t i = 0; i < size; ++i) {
            if (i % 4096 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            const auto row = rows[first + i];
            if (!scale.difference(at(target, row), centered[row])) {
                return Status::numerical;
            }
            total.add(centered[row]);
        }
        const double total_value = total.value();
        const double centered_mean = total_value / static_cast<double>(size);
        double raw_mean;
        if (!scale.raw_mean(total_value, size, raw_mean)) {
            return Status::numerical;
        }
        Sum residual_squares;
        for (std::size_t i = 0; i < size; ++i) {
            if (i % 4096 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            const double residual = centered[rows[first + i]] - centered_mean;
            residual_squares.add(residual * residual);
        }
        const double raw_mse = std::scalbn(residual_squares.value() / static_cast<double>(size), 2 * scale.exponent);
        if (!std::isfinite(raw_mse) || raw_mse <= 0.0) {
            return Status::numerical;
        }
        result = {raw_mean == 0.0 ? 0.0 : raw_mean, raw_mse, 16.0 * epsilon * scale.span, scale.exponent};
        return Status::ok;
    }

    template <class Features>
    Status find_split(std::size_t first, std::size_t size, double resolution, Split& best, Features& features) {
        std::size_t selected[cart::max_columns];
        const std::size_t candidates = features(columns, selected);
        for (std::size_t candidate = 0; candidate < candidates; ++candidate) {
            const std::size_t column = selected[candidate];
            for (std::size_t i = 0; i < size; ++i) {
                if (i % 4096 == 0 && !checkpoint.poll()) {
                    return Status::interrupted;
                }
                const auto row = rows[first + i];
                ordered[i] = {at(design, row * columns + column), row};
            }
            std::sort(ordered.begin(), ordered.begin() + size, [](const cart::Entry& a, const cart::Entry& b) {
                return a.value < b.value || (a.value == b.value && a.row < b.row);
            });
            Sum right_sum;
            for (std::size_t i = size; i > 0; --i) {
                if ((size - i) % 4096 == 0 && !checkpoint.poll()) {
                    return Status::interrupted;
                }
                right_sum.add(centered[ordered[i - 1].row]);
                suffix[i - 1] = right_sum.value();
            }
            Sum left_sum;
            for (std::size_t i = 1; i < size; ++i) {
                if ((i - 1) % 4096 == 0 && !checkpoint.poll()) {
                    return Status::interrupted;
                }
                left_sum.add(centered[ordered[i - 1].row]);
                const std::size_t other = size - i;
                if (i < minimum_leaf || other < minimum_leaf || ordered[i - 1].value == ordered[i].value) {
                    continue;
                }
                const double weight = static_cast<double>(i) * static_cast<double>(other)
                    / (static_cast<double>(size) * static_cast<double>(size));
                const double difference = left_sum.value() / static_cast<double>(i) - suffix[i] / static_cast<double>(other);
                const double score = std::sqrt(weight) * std::abs(difference);
                if (score > best.score + resolution) {
                    best = {score, cart::midpoint(ordered[i - 1].value, ordered[i].value), column, i};
                }
            }
        }
        return Status::ok;
    }

    template <class Features>
    Status grow(std::size_t first, std::size_t size, std::size_t level, Features& features) {
        if (!checkpoint.poll()) {
            return Status::interrupted;
        }
        Moments moments{};
        const auto summarized = summarize(first, size, moments);
        if (summarized != Status::ok) {
            return summarized;
        }
        const std::size_t node = nodes.size();
        nodes.push_back({{-1.0, 0.0, -1.0, -1.0, static_cast<double>(level), static_cast<double>(size),
                          moments.mean, moments.mse, 0.0}});
        if (level == depth_limit || size < 2 * minimum_leaf || moments.mse == 0.0) {
            return Status::ok;
        }
        Split best;
        const auto found = find_split(first, size, moments.resolution, best, features);
        if (found != Status::ok || best.left_count == 0) {
            return found;
        }
        const double raw_gain = std::scalbn(best.score * best.score, 2 * moments.exponent);
        if (!std::isfinite(raw_gain) || raw_gain <= 0.0) {
            return Status::numerical;
        }
        const auto start = rows.begin() + first;
        const auto middle = std::partition(start, start + size, [&](std::size_t row) {
            return at(design, row * columns + best.feature) <= best.threshold;
        });
        if (middle != start + best.left_count) {
            return Status::numerical;
        }
        const auto left_node = nodes.size();
        const auto left_status = grow(first, best.left_count, level + 1, features);
        if (left_status != Status::ok) {
            return left_status;
        }
        const auto right_node = nodes.size();
        const auto right_status = grow(first + best.left_count, size - best.left_count, level + 1, features);
        if (right_status != Status::ok) {
            return right_status;
        }
        auto& fields = nodes[node].fields;
        fields[feature] = static_cast<double>(best.feature);
        fields[threshold] = best.threshold;
        fields[left] = static_cast<double>(left_node);
        fields[right] = static_cast<double>(right_node);
        fields[gain] = raw_gain;
        return Status::ok;
    }

    Status prepare(std::size_t size) {
        const auto finite = cart::finite_design(design, size * columns, checkpoint);
        if (finite != Status::ok) {
            return finite;
        }
        rows.resize(size);
        for (std::size_t row = 0; row < size; ++row) {
            if (row % 4096 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            if (!std::isfinite(at(target, row))) {
                return Status::invalid_data;
            }
        }
        centered.resize(size);
        ordered.resize(size);
        suffix.resize(size);
        nodes.reserve(std::min(2 * (size / minimum_leaf) - 1, (std::size_t{1} << (depth_limit + 1)) - 1));
        return Status::ok;
    }

    template <class Draw, class Features>
    Status run_sample(Draw draw, Features& features) {
        for (std::size_t row = 0; row < rows.size(); ++row) {
            if (row % 4096 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            rows[row] = draw(row);
        }
        nodes.clear();
        const auto grown = grow(0, rows.size(), 0, features);
        return grown == Status::ok && !checkpoint.poll() ? Status::interrupted : grown;
    }

    Status run(std::size_t size) {
        const auto prepared = prepare(size);
        if (prepared != Status::ok) {
            return prepared;
        }
        AllFeatures features;
        return run_sample([](std::size_t row) { return row; }, features);
    }
};

struct Receipt {
    std::size_t rows;
    double mean;
    double mse;
};

bool consistent(double parent, double left, double right, double weight, double gain) {
    const double scale = std::max({std::abs(parent), std::abs(left), std::abs(right), gain});
    if (scale == 0.0) {
        return true;
    }
    const double expected = weight * (left / scale) + (1.0 - weight) * (right / scale) + gain / scale;
    const double roundoff = 32.0 * epsilon + (4.0 * std::numeric_limits<double>::denorm_min()) / scale;
    return std::abs(parent / scale - expected) <= roundoff;
}

struct Tree {
    const char* packed;
    std::size_t nodes;
    std::size_t columns;
    Checkpoint& checkpoint;

    double field(std::size_t node, Field value) const {
        return at(packed, node * stride + value);
    }

    Status visit(std::size_t node, std::size_t level, std::size_t& end, Receipt& receipt) const {
        if (node >= nodes || level > cart::max_depth) {
            return Status::invalid_tree;
        }
        if (node % 128 == 0 && !checkpoint.poll()) {
            return Status::interrupted;
        }
        const double rows = field(node, count), node_mean = field(node, mean), node_mse = field(node, mse);
        if (!cart::integer_in(rows, 1, cart::max_rows) || field(node, depth) != static_cast<double>(level)
            || !std::isfinite(node_mean) || !std::isfinite(node_mse) || node_mse < 0.0) {
            return Status::invalid_tree;
        }
        receipt = {static_cast<std::size_t>(rows), node_mean, node_mse};
        const double column = field(node, feature), cut = field(node, threshold), node_gain = field(node, gain);
        const double left_id = field(node, left), right_id = field(node, right);
        if (column == -1.0) {
            end = node + 1;
            return left_id == -1.0 && right_id == -1.0 && cut == 0.0 && node_gain == 0.0
                ? Status::ok : Status::invalid_tree;
        }
        if (!cart::integer_in(column, 0, columns - 1) || !std::isfinite(cut) || level == cart::max_depth
            || left_id != static_cast<double>(node + 1) || !cart::integer_in(right_id, node + 2, nodes - 1)
            || !std::isfinite(node_gain) || node_gain <= 0.0 || node_mse == 0.0) {
            return Status::invalid_tree;
        }
        Receipt l{}, r{};
        std::size_t after_left;
        const auto left_status = visit(node + 1, level + 1, after_left, l);
        if (left_status != Status::ok) {
            return left_status;
        }
        if (right_id != static_cast<double>(after_left)) {
            return Status::invalid_tree;
        }
        const auto right_status = visit(after_left, level + 1, end, r);
        if (right_status != Status::ok) {
            return right_status;
        }
        const double weight = static_cast<double>(l.rows) / rows;
        if (l.rows + r.rows != receipt.rows || !consistent(node_mean, l.mean, r.mean, weight, 0.0)
            || !consistent(node_mse, l.mse, r.mse, weight, node_gain)) {
            return Status::invalid_tree;
        }
        return Status::ok;
    }

    Status validate() const {
        std::size_t end;
        Receipt root{};
        const auto visited = visit(0, 0, end, root);
        if (visited != Status::ok) {
            return visited;
        }
        return end == nodes && root.rows >= 2 ? Status::ok : Status::invalid_tree;
    }

    double predict_row(const char* design, std::size_t row) const {
        std::size_t node = 0;
        while (field(node, feature) != -1.0) {
            const auto column = static_cast<std::size_t>(field(node, feature));
            const auto direction = at(design, row * columns + column) <= field(node, threshold) ? left : right;
            node = static_cast<std::size_t>(field(node, direction));
        }
        return field(node, mean);
    }

    Status score(const char* design, std::vector<double>& output) const {
        const auto validated = validate();
        if (validated != Status::ok) {
            return validated;
        }
        const auto finite = cart::finite_design(design, output.size() * columns, checkpoint);
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

PyObject* raise_failure(Status status) {
    if (status == Status::invalid_data) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_INVALID_DATA: native predictors and outcome must be finite");
    } else if (status == Status::invalid_tree) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_INVALID_TREE: the node table is inconsistent");
    } else if (status == Status::numerical) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_NUMERICAL_RANGE: native split or raw moments exceeded binary64 range");
    }
    return nullptr;
}

PyObject* fit(PyObject*, PyObject* args) {
    PyObject* design;
    PyObject* target;
    PyObject* callback = Py_None;
    Py_ssize_t rows_arg, columns_arg, depth_arg, minimum_arg;
    if (!PyArg_ParseTuple(args, "O!O!nnnn|O:fit_cart_regression", &PyBytes_Type, &design, &PyBytes_Type, &target,
                          &rows_arg, &columns_arg, &depth_arg, &minimum_arg, &callback)) {
        return nullptr;
    }
    if (rows_arg < 2 || columns_arg < 1 || minimum_arg < 1 || minimum_arg > rows_arg || depth_arg < 1) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_INVALID_DATA: native shape, depth, or minimum leaf is invalid");
        return nullptr;
    }
    const auto rows = static_cast<std::size_t>(rows_arg), columns = static_cast<std::size_t>(columns_arg);
    const auto depth = static_cast<std::size_t>(depth_arg);
    if (!cart::valid_shape(rows, columns, 1) || depth > cart::max_depth
        || rows * columns * depth * cart::sort_levels(rows) > cart::work_budget) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_WORK_LIMIT: training exceeds the native work budget");
        return nullptr;
    }
    if (PyBytes_GET_SIZE(design) != static_cast<Py_ssize_t>(rows * columns * sizeof(double))
        || PyBytes_GET_SIZE(target) != static_cast<Py_ssize_t>(rows * sizeof(double))) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_INVALID_DATA: native buffers do not match the declared training shape");
        return nullptr;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "CART regression checkpoint must be callable");
        return nullptr;
    }
    try {
        const char* x = PyBytes_AS_STRING(design);
        const char* y = PyBytes_AS_STRING(target);
        std::vector<Node> nodes;
        Status status;
        {
            Checkpoint checkpoint(callback);
            Trainer trainer{x, y, columns, depth, static_cast<std::size_t>(minimum_arg), checkpoint, {}, {}, {}, {}, {}};
            status = trainer.run(rows);
            nodes = std::move(trainer.nodes);
        }
        if (status == Status::ok) {
            return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(nodes.data()), nodes.size() * sizeof(Node));
        }
        return raise_failure(status);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

PyObject* predict(PyObject*, PyObject* args) {
    PyObject* design;
    PyObject* packed;
    PyObject* callback = Py_None;
    Py_ssize_t rows_arg, columns_arg;
    if (!PyArg_ParseTuple(args, "O!nnO!|O:predict_cart_regression", &PyBytes_Type, &design, &rows_arg, &columns_arg,
                          &PyBytes_Type, &packed, &callback)) {
        return nullptr;
    }
    if (rows_arg < 1 || columns_arg < 1) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_INVALID_DATA: native prediction shape must be positive");
        return nullptr;
    }
    const auto rows = static_cast<std::size_t>(rows_arg), columns = static_cast<std::size_t>(columns_arg);
    if (!cart::valid_shape(rows, columns, 0)) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_WORK_LIMIT: prediction exceeds the native work budget");
        return nullptr;
    }
    if (PyBytes_GET_SIZE(design) != static_cast<Py_ssize_t>(rows * columns * sizeof(double))) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_INVALID_DATA: native buffers do not match the declared prediction shape");
        return nullptr;
    }
    const auto bytes = static_cast<std::size_t>(PyBytes_GET_SIZE(packed));
    if (bytes == 0 || bytes % sizeof(Node) != 0 || bytes / sizeof(Node) > cart::max_nodes) {
        PyErr_SetString(PyExc_ValueError, "CART_REGRESSION_INVALID_TREE: node buffer size is invalid");
        return nullptr;
    }
    if (callback != Py_None && !PyCallable_Check(callback)) {
        PyErr_SetString(PyExc_TypeError, "CART regression checkpoint must be callable");
        return nullptr;
    }
    try {
        const char* x = PyBytes_AS_STRING(design);
        const char* nodes = PyBytes_AS_STRING(packed);
        std::vector<double> output(rows);
        Status status;
        {
            Checkpoint checkpoint(callback);
            const Tree tree{nodes, bytes / sizeof(Node), columns, checkpoint};
            status = tree.score(x, output);
        }
        if (status == Status::ok) {
            return PyBytes_FromStringAndSize(reinterpret_cast<const char*>(output.data()), rows * sizeof(double));
        }
        return raise_failure(status);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

}
