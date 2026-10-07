"""Run exported Stata / R / Python scripts in one warm interpreter per language.

Starting a fresh interpreter per script dominated the script-export tests:
Stata's Java-backed ``import delimited`` costs ~0.6 s on first use in every
batch process, Python spends ~0.5 s importing pandas and statsmodels, and R
~0.3 s loading survey and friends; together ~4 minutes of the suite. Each
interpreter here is started once per test session and gives every script a
clean slate:

* Stata (console mode): ``clear all``, ``macro drop _all`` and ``discard``, default ``set type``
  and ``varabbrev``, a fresh log at ``<script>.log``, then ``do <script>``.
* R: the script runs in a new environment whose ``commandArgs()`` reports
  ``--file=<script>`` as Rscript would; ``options()``, the working directory
  and the global environment are restored afterwards.
* Python: ``runpy`` in a fresh ``__main__`` namespace with the script's
  directory as cwd and ``sys.path[0]``; process-wide state (cwd, sys.path,
  argv, environment, warnings filters, numpy error/print settings, pandas
  options) is restored afterwards.

One interpreter per language and environment (as a cold process would see it).

Output, exit status and timeouts follow the cold ``subprocess.run`` path.
WORKBENCH_NATIVE_COLD=1 restores one process per script, and
tests/test_script_export_cold_process.py keeps running representative
exports cold so standalone execution stays covered.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path

STATA = Path(os.environ.get("WORKBENCH_STATA", "/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp"))


def cold() -> bool:
    return os.environ.get("WORKBENCH_NATIVE_COLD") == "1"


class _Worker:
    """A long-lived interpreter answering one request at a time over pipes."""

    def __init__(self, command: list[str], env: dict[str, str] | None = None) -> None:
        self.command = command
        self.env = env
        self.process: subprocess.Popen | None = None
        self.lines: queue.Queue = queue.Queue()

    def _start(self) -> None:
        self.process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1, env=self.env)
        self.lines = queue.Queue()
        threading.Thread(target=self._pump, args=(self.process, self.lines), daemon=True).start()

    @staticmethod
    def _pump(process: subprocess.Popen, lines: queue.Queue) -> None:
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    def request(self, text: str, sentinel: str, timeout: float) -> tuple[list[str], int | None]:
        """Send text; collect lines up to the sentinel. Returns (lines, exit code if the worker died)."""
        if self.process is None or self.process.poll() is not None:
            self._start()
        self.process.stdin.write(text)
        self.process.stdin.flush()
        collected: list[str] = []
        while True:
            try:
                line = self.lines.get(timeout=timeout)
            except queue.Empty:
                self.close()
                raise subprocess.TimeoutExpired(self.command, timeout)
            if line is None:
                code = self.process.wait()
                self.process = None
                return collected, code
            if line.strip().startswith(sentinel):
                collected.append(line)
                return collected, None
            collected.append(line)

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.process = None


_R_WORKER = r"""
local({
con <- file("stdin", open = "r")
while (length(request <- readLines(con, n = 1)) > 0) {
  parts <- strsplit(request, "\t", fixed = TRUE)[[1]]
  directory <- parts[[1]]; script <- parts[[2]]; sentinel <- parts[[3]]
  saved_options <- options(); saved_wd <- getwd()
  output <- file(file.path(directory, ".wb_native_output.txt"), open = "wt")
  sink(output); sink(output, type = "message")
  status <- tryCatch({
    setwd(directory)
    env <- new.env(parent = globalenv())
    # What Rscript <script> would report: scripts locate their files from --file=.
    path <- normalizePath(file.path(directory, script))
    env$commandArgs <- function(trailingOnly = FALSE) if (trailingOnly) character(0) else
      c("R", "--no-echo", "--no-restore", paste0("--file=", path))
    sys.source(script, envir = env, keep.source = FALSE)
    0L
  }, error = function(e) {
    message("Error: ", conditionMessage(e))
    1L
  })
  sink(type = "message"); sink(); close(output)
  options(saved_options); setwd(saved_wd)
  # Objects a script assigned globally (<<-) must not reach the next script.
  rm(list = ls(globalenv(), all.names = TRUE), envir = globalenv())
  cat(sentinel, status, "\n", sep = " ")
  flush(stdout())
}
})
"""

_PYTHON_WORKER = r"""
import io, json, os, runpy, sys, traceback, warnings
saved_out, saved_err = os.dup(1), os.dup(2)
for request in sys.stdin:
    request = json.loads(request)
    directory, script = request["directory"], request["script"]
    state = (os.getcwd(), list(sys.path), list(sys.argv), dict(os.environ), list(warnings.filters))
    numpy = sys.modules.get("numpy"); pandas = sys.modules.get("pandas")
    numpy_state = (numpy.geterr(), numpy.get_printoptions()) if numpy else None
    capture = open(os.path.join(directory, ".wb_native_output.txt"), "w")
    sys.stdout.flush(); sys.stderr.flush()
    os.dup2(capture.fileno(), 1); os.dup2(capture.fileno(), 2)
    code = 0
    try:
        os.chdir(directory)
        sys.argv = [script]
        sys.path.insert(0, directory)
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException:
        traceback.print_exc()
        code = 1
    finally:
        sys.stdout.flush(); sys.stderr.flush()
        os.dup2(saved_out, 1); os.dup2(saved_err, 2)
        capture.close()
        cwd, path, argv, environ, filters = state
        os.chdir(cwd); sys.path[:] = path; sys.argv = argv
        os.environ.clear(); os.environ.update(environ); warnings.filters[:] = filters
        numpy = sys.modules.get("numpy")
        if numpy_state and numpy:
            numpy.seterr(**numpy_state[0]); numpy.set_printoptions(**numpy_state[1])
        pandas = sys.modules.get("pandas")
        if pandas:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pandas.reset_option("all")
    sys.stdout.write(request["sentinel"] + " " + str(code) + "\n"); sys.stdout.flush()
"""

_workers: dict[tuple, _Worker] = {}


def _worker(key: tuple, command: list[str], env: dict[str, str] | None = None) -> _Worker:
    if key not in _workers:
        # At most one live interpreter per language: a new environment replaces it.
        for other in [k for k in _workers if k[0] == key[0]]:
            _workers.pop(other).close()
        _workers[key] = _Worker(command, env)
    return _workers[key]


@atexit.register
def _close_all() -> None:
    for worker in _workers.values():
        worker.close()


def _read_output(directory: Path) -> str:
    path = directory / ".wb_native_output.txt"
    text = path.read_text(errors="replace") if path.exists() else ""
    path.unlink(missing_ok=True)
    return text


def describe(language: str, filename: str) -> list[str]:
    """How a script is run, for the evidence a test records."""
    if cold():
        return {"python": [sys.executable, filename], "r": ["Rscript", filename],
                "stata": [str(STATA), "-b", "do", filename]}[language]
    return ["warm-interpreter", language, filename]


def run(language: str, directory: Path, filename: str, *, timeout: float = 90) -> tuple[int, str, str]:
    """Run one exported script; returns (exit code, stdout, stderr) like subprocess.run."""
    directory = Path(directory).resolve()
    if cold():
        commands = {"python": [sys.executable, filename], "r": ["Rscript", filename],
                    "stata": [str(STATA), "-b", "do", filename]}
        result = subprocess.run(commands[language], cwd=directory, text=True, capture_output=True, timeout=timeout)
        return result.returncode, result.stdout, result.stderr
    sentinel = "WB_NATIVE_DONE_" + uuid.uuid4().hex
    # A cold process inherits the caller's environment (tests set PYTHONPATH for
    # scripts that call Workbench helpers), so a warm one is per environment;
    # PYTEST_CURRENT_TEST changes every test and is not part of it.
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")}
    env_key = tuple(sorted(env.items()))
    if language == "stata":
        stem = Path(filename).stem
        worker = _worker(("stata", env_key), [str(STATA), "-q"], env)
        commands = "\n".join([
            "capture log close _all", "clear all", "macro drop _all", "discard", "set type float", "set varabbrev on",
            f'cd "{directory}"', f'log using "{stem}.log", text replace name(wb_native)',
            f"do {filename}", "capture log close wb_native", f'display "{sentinel}"', ""])
        lines, died = worker.request(commands, sentinel, timeout)
        return (died if died is not None else 0), "".join(lines[:-1] if died is None else lines), ""
    if language == "r":
        worker = _worker(("r", env_key), ["Rscript", "-e", _R_WORKER], env)  # same profile as Rscript <script>
        lines, died = worker.request(f"{directory}\t{filename}\t{sentinel}\n", sentinel, timeout)
        output = _read_output(directory)
        if died is not None:
            return died, output, "".join(lines)
        return int(lines[-1].split()[1]), output, ""
    if language == "python":
        worker = _worker(("python", env_key), [sys.executable, "-u", "-c", _PYTHON_WORKER], env)
        lines, died = worker.request(json.dumps({"directory": str(directory), "script": filename,
                                                  "sentinel": sentinel}) + "\n", sentinel, timeout)
        output = _read_output(directory)
        if died is not None:
            return died, output, "".join(lines)
        return int(lines[-1].split()[1]), output, ""
    raise ValueError(f"unknown language {language!r}")
