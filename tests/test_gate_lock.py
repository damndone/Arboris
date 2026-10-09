"""Real subprocess contention tests; no production gate stages are executed."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

HELPER = Path(__file__).parents[1] / "scripts/gate_lock.py"


def start(lock, body, cwd, *, helper=HELPER):
    cwd.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["TMPDIR"] = str(cwd)
    code = (
        "import runpy,sys; m=runpy.run_path(sys.argv[1]); "
        "sys.exit(m['run_locked']([sys.executable,'-c',sys.argv[3]], "
        "lock_path=sys.argv[2]))"
    )
    return subprocess.Popen([sys.executable, "-c", code, str(helper), str(lock), body],
                            cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def wait_file(path, process):
    deadline = time.monotonic() + 5
    while not path.exists() and process.poll() is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert path.exists(), process.communicate(timeout=2)


def test_lock_helper_exists():
    assert HELPER.is_file(), "atomic gate lock helper has not been implemented"


def test_distinct_checkouts_and_tmpdirs_reject_before_command(tmp_path):
    lock, ready, release = [tmp_path / name for name in ("lock", "ready", "release")]
    copy = tmp_path / "gate_lock.py"
    copy.write_text(HELPER.read_text())
    body = f"from pathlib import Path; import time; Path({str(ready)!r}).touch();\nwhile not Path({str(release)!r}).exists(): time.sleep(.01)"
    holder = start(lock, body, tmp_path / "one")
    try:
        wait_file(ready, holder)
        loser = start(lock, "print('BODY RAN')", tmp_path / "two", helper=copy)
        out, err = loser.communicate(timeout=5)
        assert loser.returncode == 3
        assert "BODY RAN" not in out
        assert "REFUSING" in err
    finally:
        release.touch()
        assert holder.wait(timeout=5) == 0
    assert lock.exists(), "the stable lock inode must never be unlinked"
    inode = lock.stat().st_ino
    next_run = start(lock, "pass", tmp_path / "three")
    assert next_run.wait(timeout=5) == 0
    assert lock.stat().st_ino == inode


@pytest.mark.parametrize("exit_code", [0, 7])
def test_exit_and_stale_metadata_do_not_block_or_kill(tmp_path, exit_code):
    lock = tmp_path / "lock"
    lock.write_text(str(os.getpid()))
    process = start(lock, f"raise SystemExit({exit_code})", tmp_path / "one")
    assert process.wait(timeout=5) == exit_code
    next_run = start(lock, "pass", tmp_path / "two")
    assert next_run.wait(timeout=5) == 0


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_signal_holds_lock_until_child_finishes(tmp_path, signum):
    lock, ready, signaled, release = [tmp_path / n for n in ("lock", "ready", "signaled", "release")]
    body = f"""import signal,time
from pathlib import Path
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(sig, lambda *_: Path({str(signaled)!r}).touch())
Path({str(ready)!r}).touch()
while not Path({str(release)!r}).exists(): time.sleep(.01)
"""
    holder = start(lock, body, tmp_path / "one")
    try:
        wait_file(ready, holder)
        holder.send_signal(signum)
        wait_file(signaled, holder)
        loser = start(lock, "print('BODY RAN')", tmp_path / "two")
        out, _ = loser.communicate(timeout=5)
        assert loser.returncode == 3 and not out
    finally:
        release.touch()
        assert holder.wait(timeout=5) == 128 + signum
    next_run = start(lock, "pass", tmp_path / "three")
    assert next_run.wait(timeout=5) == 0


def test_simultaneous_contenders_have_exactly_one_winner(tmp_path):
    lock, release = tmp_path / "lock", tmp_path / "release"
    body = f"from pathlib import Path; import time; print('WINNER',flush=True);\nwhile not Path({str(release)!r}).exists(): time.sleep(.01)"
    processes = [start(lock, body, tmp_path / str(i)) for i in range(6)]
    try:
        deadline = time.monotonic() + 5
        while sum(p.poll() is not None for p in processes) < 5 and time.monotonic() < deadline:
            time.sleep(.01)
        assert sum(p.poll() is None for p in processes) == 1
        assert sum(p.returncode == 3 for p in processes) == 5
    finally:
        release.touch()
        results = [p.communicate(timeout=5) for p in processes]
    assert sum(out.strip() == 'WINNER' for out, _ in results) == 1


def test_signal_keeps_lock_after_leader_exits_until_grandchild_finishes(tmp_path):
    lock, ready, signaled, release = [tmp_path / n for n in ("lock", "ready", "signaled", "release")]
    grandchild = f"""import signal,time
from pathlib import Path
signal.signal(signal.SIGTERM, lambda *_: Path({str(signaled)!r}).touch())
Path({str(ready)!r}).touch()
while not Path({str(release)!r}).exists(): time.sleep(.01)
"""
    body = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{grandchild!r}]); time.sleep(60)"
    holder = start(lock, body, tmp_path / "one")
    try:
        wait_file(ready, holder)
        holder.terminate()
        wait_file(signaled, holder)
        # The direct child has default TERM handling, but its child delays exit.
        loser = start(lock, "print('BODY RAN')", tmp_path / "two")
        out, _ = loser.communicate(timeout=5)
        assert loser.returncode == 3 and not out
        assert holder.poll() is None
    finally:
        release.touch()
        assert holder.wait(timeout=5) == 128 + signal.SIGTERM
    next_run = start(lock, "pass", tmp_path / "three")
    assert next_run.wait(timeout=5) == 0
