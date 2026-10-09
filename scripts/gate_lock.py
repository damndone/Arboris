"""Host-wide gate exclusion. Metadata is diagnostic; flock alone owns the lock."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

# Deliberately independent of the checkout, user environment and TMPDIR.
# Never unlink this file: every contender must lock the same inode.
LOCK_PATH = Path("/tmp/workbench-gate.lock")
BODY_MARKER = "# WORKBENCH_GATE_BODY\n"


def run_locked(command: list[str], *, lock_path: Path | str = LOCK_PATH) -> int:
    """Supervise a process group under one stable lock (path injectable by tests)."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("REFUSING: another gate is already running. Wait for it to finish.", file=sys.stderr)
            return 3
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({"pid": os.getpid(), "cwd": os.getcwd()}).encode())
        received = 0
        child = None

        def forward(signum, _frame):
            nonlocal received
            received = received or signum
            if child is not None:
                try:
                    os.killpg(child.pid, signum)
                except ProcessLookupError:
                    pass

        signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
        previous = {sig: signal.signal(sig, forward) for sig in signals}
        try:
            # The shell inherits the descriptor too, so a killed supervisor
            # cannot drop exclusion while its shell is still running.
            child = subprocess.Popen(command, start_new_session=True, pass_fds=(fd,))
            if received:
                forward(received, None)
            status = child.wait()
            # A shell can exit before children which are still unwinding a
            # signal handler. Keep exclusion until its entire group is gone.
            while True:
                try:
                    os.killpg(child.pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(.02)
            return 128 + received if received else (128 - status if status < 0 else status)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    finally:
        os.close(fd)


def main() -> int:
    gate = Path(__file__).with_name("gate.sh")
    body = gate.read_text().split(BODY_MARKER, 1)[1]
    return run_locked(["bash", "-c", body, str(gate), *sys.argv[1:]])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print(f"REFUSING: gate lock or command unavailable: {exc}", file=sys.stderr)
        raise SystemExit(3)
