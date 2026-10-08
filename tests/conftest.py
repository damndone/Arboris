"""Suite-wide isolation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Retained evaluation sources are evidence copies, never part of the suite. The
# Lane E harness writes its own write-once evidence and needs real Stata, so it
# is collected only when its output directory is named explicitly.
collect_ignore_glob = ["fixtures/eval_v1811/*"]
if not os.environ.get("WB_LANE_E_OUT"):
    collect_ignore_glob.append("eval_v1811/lane_e_*")


# Subprocesses (CLIs, scripts, cold interpreters) import this checkout's
# backend, never the worktree the shared virtualenv's editable install happens
# to name (tests/test_subprocess_imports_this_checkout.py).
_BACKEND = str(Path(__file__).resolve().parents[1] / "backend")
os.environ["PYTHONPATH"] = os.pathsep.join(
    [_BACKEND, *(part for part in os.environ.get("PYTHONPATH", "").split(os.pathsep) if part and part != _BACKEND)]
)

# TestClient addresses the app as "http://testserver". The local request guard
# admits only loopback host names by default; tests/test_local_api_security.py
# removes this allowance to check the shipped defaults.
os.environ.setdefault("WORKBENCH_ALLOWED_HOSTS", "testserver")

# Every declared response type is enforced strictly in tests
# (tests/response_contracts.py); production serves responses unvalidated.
# Every FastAPI app a test builds (the Workbench app and the ad-hoc apps that
# mount a single router) gets the validator as its outermost layer.
from response_contracts import VIOLATIONS as _CONTRACT_VIOLATIONS, install_on_every_app

install_on_every_app()


@pytest.fixture(autouse=True)
def _responses_match_their_declared_types():
    _CONTRACT_VIOLATIONS.clear()
    yield
    if _CONTRACT_VIOLATIONS:
        found = list(dict.fromkeys(_CONTRACT_VIOLATIONS))
        _CONTRACT_VIOLATIONS.clear()
        pytest.fail("response contract violated:\n" + "\n".join(found[:200]), pytrace=False)


# Opt-in: record real JSON responses per route (tests/response_recorder.py).
if os.environ.get("WORKBENCH_RECORD_RESPONSES"):
    from response_recorder import ResponseRecorder
    from workbench.app import app as _recorded_app

    _recorded_app.add_middleware(ResponseRecorder, directory=os.environ["WORKBENCH_RECORD_RESPONSES"])


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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Evidence a failing test wrote into local/test-evidence is always kept."""

    outcome = yield
    if outcome.get_result().failed:
        from evidence_retention import STORE

        STORE.test_failed(item.nodeid)


def pytest_sessionfinish(session, exitstatus):
    """Keep the newest runs of each evidence category this session wrote
    (tests/evidence_retention.py)."""

    from evidence_retention import STORE

    STORE.prune()
    coverage = os.environ.get("WORKBENCH_CONTRACT_COVERAGE")
    if coverage:
        from response_contracts import VALIDATED

        Path(coverage).write_text("\n".join(sorted(VALIDATED)) + "\n", encoding="utf-8")
