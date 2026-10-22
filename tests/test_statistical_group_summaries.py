"""Per-group summaries give bit-identical pairwise effect sizes and Welch tests."""

import random

import pytest

from workbench.statistical_tests import _GroupSummary, _cohens_d_evidence


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_summary_path_matches_the_per_comparison_path(seed):
    rng = random.Random(seed)
    groups = [[rng.gauss(rng.uniform(-5, 5), rng.uniform(0.1, 9)) for _ in range(rng.randint(2, 4000))]
              for _ in range(5)] + [[3.0, 3.0, 3.0], [1.0, 2.0]]
    summaries = [_GroupSummary(values) for values in groups]
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            try:
                expected = _cohens_d_evidence(groups[i], groups[j], test_id="t", labels=("a", "b"))
            except ValueError:
                with pytest.raises(ValueError):
                    _cohens_d_evidence(summaries[i], summaries[j], test_id="t", labels=("a", "b"))
                continue
            assert _cohens_d_evidence(summaries[i], summaries[j], test_id="t", labels=("a", "b")) == expected
