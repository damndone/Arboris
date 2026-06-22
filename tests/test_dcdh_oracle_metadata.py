import json
from pathlib import Path

import pytest

_FIX = Path(__file__).parent / "fixtures" / "dcdh"
_REQUIRED = {"effects", "placebos", "same_switchers", "cluster", "seed", "package_version"}


@pytest.mark.parametrize("name", ["nonabsorbing", "baseline1", "placebo"])
def test_oracle_has_locked_kou_jing_metadata(name):
    """Every dCDH oracle JSON must carry the locked DIDmultiplegtDYN 口径 in its
    metadata so a later package upgrade can't silently drift the validation target."""
    o = json.loads((_FIX / f"dyn_{name}.json").read_text())
    assert "metadata" in o, f"{name} oracle missing metadata block"
    assert _REQUIRED <= set(o["metadata"]), _REQUIRED - set(o["metadata"])
    assert o["metadata"]["same_switchers"] is True
    assert o["metadata"]["cluster"] == "id"
    assert o["metadata"]["effects"] == 3
    assert o["metadata"]["placebos"] == 2


@pytest.mark.parametrize("name", ["nonabsorbing", "baseline1", "placebo"])
def test_oracle_arrays_well_formed(name):
    o = json.loads((_FIX / f"dyn_{name}.json").read_text())
    assert len(o["effect_estimate"]) == len(o["effect_se"]) == len(o["effect_n"]) == 3
    assert len(o["placebo_estimate"]) == len(o["placebo_se"]) == len(o["placebo_n"]) == 2
    assert isinstance(o["overall_estimate"], (int, float))
