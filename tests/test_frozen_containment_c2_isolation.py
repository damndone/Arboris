"""C2 policy work must not dilute C1's source-only boundary."""

from __future__ import annotations

import inspect

import workbench.frozen_containment as c1
import workbench.frozen_containment_c2 as c2


def test_c1_does_not_import_or_expose_c2_execution() -> None:
    source = inspect.getsource(c1)
    assert "frozen_containment_c2" not in source
    assert not hasattr(c1.FrozenContainmentService, "execute_c2_request")
    assert not hasattr(c1.FrozenContainmentService, "admit_host")


def test_c2_policy_module_has_no_execution_or_c1_receipt_surface() -> None:
    source = inspect.getsource(c2)
    assert "import workbench.frozen_containment" not in source
    assert "from .frozen_containment" not in source
    assert "Popen(" not in source
    assert "subprocess" not in source
    assert not hasattr(c2, "C2ContainmentExecutor")
    assert not any("receipt" in name.casefold() for name in dir(c2) if not name.startswith("_"))
