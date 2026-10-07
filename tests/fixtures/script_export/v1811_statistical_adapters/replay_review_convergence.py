"""Replay unchanged reviewer cases against producer code, retaining owned evidence."""
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[4]
REVIEW = REPO.parent / "codex-v1811-script-adapters-review"
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "backend"))
from workbench.script_export.exporters import models
from workbench.script_export.render import export_script
assert Path(models.__file__).resolve() == REPO / "backend/workbench/script_export/exporters/models.py"
print("Producer renderer:", models.__file__)


class OwnedEvidence:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            module = item.module
            if module.__name__.endswith("script_statistical_adapters_review_probe"):
                module.REPO = REPO
                module.OUT = Path(__file__).resolve().parent / "review_convergence_replay"


raise SystemExit(pytest.main([
    "-q", str(REVIEW / "tests/eval_v1811/script_statistical_adapters_review_probe.py"),
    "-k", sys.argv[1] if len(sys.argv)>1 else "large_alpha_completed_owner or extreme_finite", "--tb=short", "-s",
], plugins=[OwnedEvidence()]))
