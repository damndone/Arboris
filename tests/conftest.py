"""Suite-wide isolation."""

from __future__ import annotations

import os

import pytest

# Retained evaluation sources are evidence copies, never part of the suite. The
# Lane E harness writes its own write-once evidence and needs real Stata, so it
# is collected only when its output directory is named explicitly.
collect_ignore_glob = ["fixtures/eval_v1811/*"]
if not os.environ.get("WB_LANE_E_OUT"):
    collect_ignore_glob.append("eval_v1811/lane_e_*")


@pytest.fixture(autouse=True, scope="session")
def _egress_audit_outside_the_home_directory(tmp_path_factory):
    """Provider calls outside a project scope audit to a user-level log; tests
    must never write to the real one."""

    previous = os.environ.get("WORKBENCH_EGRESS_AUDIT_DIR")
    os.environ["WORKBENCH_EGRESS_AUDIT_DIR"] = str(tmp_path_factory.mktemp("egress-audit"))
    yield
    if previous is None:
        os.environ.pop("WORKBENCH_EGRESS_AUDIT_DIR", None)
    else:
        os.environ["WORKBENCH_EGRESS_AUDIT_DIR"] = previous


@pytest.fixture(autouse=True, scope="session")
def _no_waiting_between_provider_retries():
    """Provider retries back off for seconds in production; tests keep the
    retry behaviour without the wait."""

    from workbench.agent.model import OpenAICompatibleModelAdapter

    previous = OpenAICompatibleModelAdapter.retry_delays_s
    OpenAICompatibleModelAdapter.retry_delays_s = (0.0, 0.0)
    yield
    OpenAICompatibleModelAdapter.retry_delays_s = previous
