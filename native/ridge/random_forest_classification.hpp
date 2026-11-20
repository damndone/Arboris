#pragma once

namespace random_forest_classification {

using cart::Status;
using random_forest::max_trees;
using random_forest::node_budget;
using random_forest::per_tree_nodes;
using random_forest::Random;
using random_forest::SampleFeatures;
using random_forest::Specification;
using random_forest::TreeSlice;

constexpr double model_tag = 4001.0;
constexpr std::size_t header_width = 9;
constexpr std::size_t tree_evidence = 2;

struct Forest {
    std::array<TreeSlice, max_trees> trees;
    std::size_t size;

    Status read(const char* packed, std::size_t bytes, std::size_t columns, Checkpoint& checkpoint) {
        const auto length = bytes / sizeof(double);
        if (bytes % sizeof(double) != 0 || length < header_width + tree_evidence + cart::stride
            || length > header_width + max_trees * tree_evidence + node_budget * cart::stride
            || at(packed, 0) != model_tag) {
            return Status::invalid_tree;
        }
        Specification spec{};
        if (!random_forest::read_specification(packed + sizeof(double), columns, spec)
            || !cart::integer_in(at(packed, 8), 1, spec.rows - 1)) {
            return Status::invalid_tree;
        }
        const auto original_positive = static_cast<std::size_t>(at(packed, 8));
        size = spec.trees;
        std::size_t offset = header_width + tree_evidence * size;
        if (offset > length) {
            return Status::invalid_tree;
        }
        std::size_t total_nodes = 0;
        for (std::size_t i = 0; i < size; ++i) {
            const auto evidence = header_width + tree_evidence * i;
            const double raw_nodes = at(packed, evidence), raw_distinct = at(packed, evidence + 1);
            if (!cart::integer_in(raw_nodes, 1, per_tree_nodes(spec)) || !cart::integer_in(raw_distinct, 1, spec.rows)) {
                return Status::invalid_tree;
            }
            const auto nodes = static_cast<std::size_t>(raw_nodes);
            total_nodes += nodes;
            if (total_nodes > node_budget || nodes > (length - offset) / cart::stride) {
                return Status::invalid_tree;
            }
            const char* table = packed + offset * sizeof(double);
            const cart::Tree tree{table, nodes, columns, checkpoint};
            const auto checked = tree.validate(true);
            if (checked != Status::ok) {
                return checked;
            }
            if (tree.field(0, cart::samples) != static_cast<double>(spec.rows)) {
                return Status::invalid_tree;
            }
            const auto positives = static_cast<std::size_t>(tree.field(0, cart::positives));
            const auto negatives = spec.rows - positives;
            const std::size_t fewest = static_cast<std::size_t>(positives > 0) + static_cast<std::size_t>(negatives > 0);
            const auto most = std::min(positives, original_positive) + std::min(negatives, spec.rows - original_positive);
            if (!cart::integer_in(raw_distinct, fewest, most)) {
                return Status::invalid_tree;
            }
            for (std::size_t node = 0; node < nodes; ++node) {
                if (tree.field(node, cart::depth) > static_cast<double>(spec.depth)
                    || (tree.field(node, cart::feature) == -1.0
                        && tree.field(node, cart::samples) < static_cast<double>(spec.minimum_leaf))) {
                    return Status::invalid_tree;
                }
            }
            trees[i] = {table, nodes};
            offset += nodes * cart::stride;
        }
        return offset == length ? Status::ok : Status::invalid_tree;
    }

    Status score(const char* design, std::size_t columns, std::vector<double>& output, Checkpoint& checkpoint) const {
        const auto finite = cart::finite_design(design, output.size() * columns, checkpoint);
        if (finite != Status::ok) {
            return finite;
        }
        for (std::size_t row = 0; row < output.size(); ++row) {
            if (row % 256 == 0 && !checkpoint.poll()) {
                return Status::interrupted;
            }
            Sum total;
            for (std::size_t i = 0; i < size; ++i) {
                const cart::Tree tree{trees[i].table, trees[i].size, columns, checkpoint};
                total.add(tree.predict_row(design, row));
            }
            output[row] = total.value() / static_cast<double>(size);
        }
        return checkpoint.poll() ? Status::ok : Status::interrupted;
    }
};

PyObject* raise_failure(Status status) {
    switch (status) {
    case Status::invalid_data:
        PyErr_SetString(PyExc_ValueError, "FOREST_CLASSIFICATION_INVALID_DATA: native predictors must be finite");
        break;
    case Status::invalid_labels:
        PyErr_SetString(PyExc_ValueError, "FOREST_CLASSIFICATION_INVALID_LABELS: native labels must be exactly 0 or 1");
        break;
    case Status::single_class:
        PyErr_SetString(PyExc_ValueError, "FOREST_CLASSIFICATION_TRAIN_SINGLE_CLASS: training must contain both 0 and 1");
        break;
    case Status::invalid_tree:
        PyErr_SetString(PyExc_ValueError, "FOREST_CLASSIFICATION_INVALID_TREE: forest metadata or nodes are inconsistent");
        break;
    case Status::numerical:
        PyErr_SetString(PyExc_ValueError, "FOREST_CLASSIFICATION_NUMERICAL_RANGE: a tree split could not be reproduced");
        break;
    case Status::ok:
    case Status::interrupted:
        break;
    }
    return nullptr;
}

PyObject* fit(PyObject*, PyObject* args) {
    random_forest::TrainingArguments input{};
    if (!random_forest::training_arguments(args, "O!O!nnnnnnO|O:fit_random_forest_classification",
                                           "FOREST_CLASSIFICATION", input)) {
        return nullptr;
    }
    const auto spec = input.spec;
    try {
        std::vector<cart::Node> nodes;
        nodes.reserve(std::min(node_budget, spec.trees * per_tree_nodes(spec)));
        std::array<double, max_trees * tree_evidence> evidence{};
        Status status;
        bool limit = false;
        std::size_t original_positive = 0;
        {
            Checkpoint checkpoint(input.callback);
            cart::Trainer trainer{input.design, input.outcome, input.columns, spec.depth, spec.minimum_leaf,
                                  checkpoint, {}, {}, {}};
            status = trainer.prepare(spec.rows, original_positive);
            std::vector<std::uint8_t> seen(spec.rows, 0);
            Random forest{spec.seed};
            for (std::size_t i = 0; i < spec.trees && status == Status::ok; ++i) {
                Random bootstrap{forest.next()};
                SampleFeatures candidates{spec.features, Random{forest.next()}};
                const auto stamp = static_cast<std::uint8_t>(i + 1);
                std::size_t distinct = 0;
                const auto draw = [&](std::size_t) {
                    const auto row = bootstrap.index(spec.rows);
                    if (seen[row] != stamp) {
                        seen[row] = stamp;
                        ++distinct;
                    }
                    return row;
                };
                status = trainer.run_sample(draw, candidates);
                if (status != Status::ok) {
                    break;
                }
                if (trainer.nodes.size() > node_budget - nodes.size()) {
                    limit = true;
                    break;
                }
                evidence[tree_evidence * i] = static_cast<double>(trainer.nodes.size());
                evidence[tree_evidence * i + 1] = static_cast<double>(distinct);
                nodes.insert(nodes.end(), trainer.nodes.begin(), trainer.nodes.end());
            }
        }
        if (status != Status::ok) {
            return raise_failure(status);
        }
        if (limit) {
            PyErr_SetString(PyExc_ValueError, "FOREST_CLASSIFICATION_WORK_LIMIT: fitted forest exceeds its total node budget");
            return nullptr;
        }
        const double header[header_width]{
            model_tag, static_cast<double>(spec.trees), static_cast<double>(spec.rows), static_cast<double>(spec.depth),
            static_cast<double>(spec.minimum_leaf), static_cast<double>(spec.features), static_cast<double>(spec.seed),
            static_cast<double>(input.columns), static_cast<double>(original_positive),
        };
        const auto evidence_bytes = spec.trees * tree_evidence * sizeof(double);
        const auto bytes = sizeof(header) + evidence_bytes + nodes.size() * sizeof(cart::Node);
        PyObject* packed = PyBytes_FromStringAndSize(nullptr, static_cast<Py_ssize_t>(bytes));
        if (packed) {
            char* destination = PyBytes_AS_STRING(packed);
            std::memcpy(destination, header, sizeof(header));
            std::memcpy(destination + sizeof(header), evidence.data(), evidence_bytes);
            std::memcpy(destination + sizeof(header) + evidence_bytes, nodes.data(), nodes.size() * sizeof(cart::Node));
        }
        return packed;
    } catch (const random_forest::ExhaustedRandomDraw&) {
        PyErr_SetString(PyExc_ValueError, "FOREST_CLASSIFICATION_RANDOM_RANGE: a bounded unbiased draw could not be generated");
        return nullptr;
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    }
}

PyObject* predict(PyObject*, PyObject* args) {
    random_forest::ScoringArguments input{};
    if (!random_forest::scoring_arguments(args, "O!nnO!|O:predict_random_forest_classification",
                                          "FOREST_CLASSIFICATION", input)) {
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
