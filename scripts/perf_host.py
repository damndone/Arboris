"""Shared benchmark host gate: continuous sampled evidence, failed ps is not idle."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time

BUSY_MARKERS = ('pytest', 'perf_', 'bench_', 'gate.sh', 'vitest', 'agent_eval', 'cargo test', 'cargo bench')
HOST_SAMPLE_SECONDS = .2
HOST_MAX_GAP_SECONDS = 1.


def other_heavy_runs(ignore_pids=()) -> list[str]:
    rows = subprocess.check_output(['ps', '-Ao', 'pid=,ppid=,command='], text=True, timeout=5).splitlines()
    processes = []
    for row in rows:
        pid, parent, command = row.strip().split(None, 2)
        processes.append((int(pid), int(parent), command))
    if not any(pid == os.getpid() for pid, _, _ in processes):
        raise RuntimeError('invalid_process_snapshot: current process missing')
    # The parent is ignored only by PID; excluding all its descendants hides sibling benchmarks.
    descendants = set(ignore_pids)
    while True:
        children = {pid for pid, parent, _ in processes if parent in descendants}
        if children <= descendants:
            break
        descendants.update(children)
    ignored = descendants | {os.getpid(), os.getppid()}
    return [f'{pid} {command}' for pid, _, command in processes
            if pid not in ignored and any(marker in command.partition(r'\012')[0] for marker in BUSY_MARKERS)]


def require_idle() -> float:
    """Fail immediately and visibly; do not silently wait behind another test."""
    busy = other_heavy_runs()
    if busy:
        raise RuntimeError('host_busy: ' + '; '.join(busy)[:1000])
    return 0.


wait_until_idle = require_idle


class monitor_host:
    """Use `with monitor_host(path) as monitor`; inspect monitor.summary after exit.

    Samples bracket the caller's whole block. Only this process, its parent and
    explicitly registered workers and their descendants are excluded. Failed snapshots and gaps above 1s invalidate it.
    This is a sampled occupancy gate, not an OS process-lifecycle audit.
    """
    def __init__(self, evidence: Path, *, interval=HOST_SAMPLE_SECONDS):
        self.evidence, self.interval = Path(evidence), interval
        self.stamps, self.overlap, self.errors = [], set(), []
        self.stop = threading.Event()
        self.workers = set()
        self.lock = threading.RLock()
        self.last_sample_write = None

    def allow_worker(self, pid):
        """Register exactly one measured child; unrelated driver children stay visible."""
        with self.lock:
            self.workers.add(pid)

    def popen(self, *args, **kwargs):
        """Launch/register atomically with sampling so a measured child cannot race ps."""
        with self.lock:
            process = subprocess.Popen(*args, **kwargs)
            self.workers.add(process.pid)
            return process

    def sample(self):
        lock_requested = time.monotonic()
        with self.lock:
            stamp = time.monotonic()
            record = {'monotonic_seconds': stamp, 'lock_wait_seconds': stamp - lock_requested}
            snapshot_started = time.monotonic()
            try:
                record['other_heavy_runs'] = other_heavy_runs(self.workers)
                self.overlap.update(record['other_heavy_runs'])
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                record['error'] = f'{type(exc).__name__}: {exc}'
                self.errors.append(record['error'])
            record['process_snapshot_seconds'] = time.monotonic() - snapshot_started
            self.stamps.append(stamp)
            # JSON encoding/write/flush cannot report its own end in this row.
            # Carry the previous interval; the summary retains the final one.
            if self.last_sample_write is not None:
                record['previous_sample_write'] = self.last_sample_write
            write_started = time.monotonic()
            self.stream.write(json.dumps(record) + '\n')
            self.stream.flush()
            self.last_sample_write = {'sample_monotonic_seconds': stamp,
                                      'started_monotonic_seconds': write_started,
                                      'finished_monotonic_seconds': time.monotonic()}

    def run(self):
        while not self.stop.wait(self.interval):
            self.sample()

    def __enter__(self):
        self.evidence.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.evidence.open('x')
        self.sample()
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.ended = time.monotonic()
        self.stop.set()
        self.thread.join()
        self.sample()
        os.fsync(self.stream.fileno())
        self.stream.close()
        gaps = [b - a for a, b in zip(self.stamps, self.stamps[1:])]
        self.summary = {'evidence': str(self.evidence),
                        'sha256': hashlib.sha256(self.evidence.read_bytes()).hexdigest(),
                        'samples': len(self.stamps), 'overlap': sorted(self.overlap), 'errors': self.errors,
                        'max_gap_seconds': max(gaps, default=math.inf),
                        'worker_started_monotonic': self.started, 'worker_ended_monotonic': self.ended,
                        'covers_worker': self.stamps[0] <= self.started <= self.ended <= self.stamps[-1],
                        'last_sample_write': self.last_sample_write,
                        'method': 'process snapshots throughout measured block', 'interval_seconds': self.interval}
        self.summary['valid'] = (not self.overlap and not self.errors and self.summary['covers_worker']
                                 and self.summary['max_gap_seconds'] <= HOST_MAX_GAP_SECONDS)


def terminate_bounded(process):
    process.terminate()
    try:
        return process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.communicate(timeout=2)  # failure propagates; never an unbounded wait


def monitored_worker(command, evidence: Path, *, cwd=None, env=None, timeout=None):
    with monitor_host(evidence) as monitor:
        process = monitor.popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stdout, stderr = terminate_bounded(process)
            monitor.errors.append(f'worker_timeout: {timeout}s')
        finally:
            if process.poll() is None:
                terminate_bounded(process)
    return process.returncode, stdout, stderr, monitor.summary
