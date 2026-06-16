import json
import numpy as np
import pandas as pd
import pytest

CLUSTERED = json.load(open("tests/fixtures/cs_did/aggte_clustered.json"))
UNCLUSTERED = json.load(open("tests/fixtures/cs_did/aggte.json"))


def test_clustered_oracle_present_and_differs():
    for m in ("dr", "ipw", "reg"):
        assert CLUSTERED[m]["n"] == 60 and CLUSTERED[m]["n_clusters"] == 20
        c = CLUSTERED[m]["dynamic"]["overall_se"]
        u = UNCLUSTERED[m]["dynamic"]["overall_se"]
        assert c is not None and abs(c - u) > 1e-6  # clustering changed the SE
