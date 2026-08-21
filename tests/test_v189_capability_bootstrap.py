"""Regression coverage for deterministic capability registry bootstrap."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def test_clean_process_publishes_mice_before_imputation_stage_import() -> None:
    """MICE metadata must not depend on importing its execution stage."""

    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(repo_root / "backend"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MPLCONFIGDIR": "/private/tmp",
        }
    )
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; import sys; "
                "from workbench.engine.capabilities import build_capabilities; "
                "from workbench.engine.imputation_registry import IMPUTATION_REGISTRY; "
                "initial = {"
                "'registry': 'mice' in IMPUTATION_REGISTRY, "
                "'stage_imported': 'workbench.engine.stages.imputation' in sys.modules"
                "}; "
                "from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS; "
                "optional_pack_imported_before_inventory = any("
                "name.startswith('workbench.engine.packs.') and name not in {"
                "'workbench.engine.packs', 'workbench.engine.packs.loader', "
                "'workbench.engine.packs.builtin_declarations'"
                "} for name in sys.modules); "
                "from workbench.agent.capability_contract import capability_inventory, capability_reachability_guard; "
                "inventory = capability_inventory(); "
                "report = capability_reachability_guard(inventory); "
                "print(json.dumps({"
                "'initial': initial, "
                "'manifest': 'mice' in {item['key'] for item in build_capabilities(bootstrap_packs=False)['imputation_methods']}, "
                "'workflow': 'imputation.mice' in WORKFLOW_STEP_SPEC_CONTRACTS, "
                "'inventory': 'imputation.mice' in {item.capability_id for item in inventory}, "
                "'reachable': 'imputation.mice' in {item.capability_id for item in report.reachable}, "
                "'optional_pack_imported_before_inventory': optional_pack_imported_before_inventory"
                "}, sort_keys=True))"
            ),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert probe.returncode == 0, probe.stderr
    result = json.loads(probe.stdout)
    assert result == {
        "initial": {"registry": True, "stage_imported": False},
        "inventory": True,
        "manifest": True,
        "optional_pack_imported_before_inventory": False,
        "reachable": True,
        "workflow": True,
    }
