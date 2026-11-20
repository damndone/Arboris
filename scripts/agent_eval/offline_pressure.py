"""Exercise a local Workbench under concurrent submissions and offline Agent replays."""
from __future__ import annotations

import argparse
import asyncio
from base64 import urlsafe_b64encode
from contextlib import suppress
import csv
from datetime import UTC, datetime
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import random
import shutil
import signal
import socket
import subprocess
import sys
from threading import Thread
import time

import httpx

ROOT = Path(__file__).resolve().parents[2]
API, UI = "http://127.0.0.1:8036", "http://127.0.0.1:5197"
FLOOR = 5_000_000_000
TERMINAL = {"completed", "blocked", "failed", "cancelled", "interrupted"}
REPLAY = "tests/test_agent_product_replay.py::test_cli_records_and_strictly_replays_actual_analysis_and_reports[plan-and-analysis]"


def utc():
    return datetime.now(UTC).isoformat()


def sampled_rss(roots):
    result = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,rss="], text=True)
    processes = {pid: (ppid, rss) for pid, ppid, rss in (map(int, line.split()) for line in result.splitlines())}
    parents = set(roots.values())
    while True:
        expanded = parents | {pid for pid, (parent, _) in processes.items() if parent in parents}
        if expanded == parents:
            break
        parents = expanded
    return {str(pid): processes[pid][1] for pid in sorted(parents & processes.keys())}


class NoCache(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path in {"/", "/status.json"}:
            super().do_GET()
        else:
            self.send_error(404)


class Pressure:
    def __init__(self, out, max_rss_mib):
        self.out = out
        self.max_rss_mib = max_rss_mib
        self.public = out / "view"
        self.public.mkdir()
        shutil.copyfile(Path(__file__).with_name("pressure_dashboard.html"), self.public / "index.html")
        self.owned = {}
        self.peak_per_pid = {}
        self.state = {"kind": "offline_pressure", "phase": "准备", "result": None,
                      "peak_rss_kib": 0, "rss_kib": {}, "processes": {}, "tasks": [],
                      "error": None, "rss_limit_mib": max_rss_mib}
        self.env = {key: value for key, value in os.environ.items() if key in
                    {"PATH", "HOME", "USER", "TMPDIR", "SYSTEMROOT"}}
        self.env.update(PYTHONPATH=f"{ROOT}/backend:{ROOT}", LC_ALL="en_US.UTF-8", LANG="en_US.UTF-8",
                        WORKBENCH_LLM_CONFIG_PATH=str(out / "offline-provider.json"),
                        WORKBENCH_AGENT_RECOVERY_DIR=str(out / "agent-recovery"),
                        WORKBENCH_EGRESS_AUDIT_DIR=str(out / "egress-audit"),
                        WORKBENCH_ALLOWED_ORIGINS=UI, VITE_API_PROXY_TARGET=API)
        (out / "offline-provider.json").write_text(
            '{"version":1,"active_provider_id":null,"providers":[]}\n', encoding="utf-8")

    def publish(self):
        self.state["updated"] = utc()
        stage = self.public / ".status.tmp"
        stage.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        stage.replace(self.public / "status.json")

    def event(self, task, **fields):
        task.update(fields)
        with (self.out / "events.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": utc(), **task}, ensure_ascii=False) + "\n")
        self.publish()

    def child(self, name, argv, cwd=ROOT):
        with (self.out / f"{name}.log").open("xb") as log:
            process = subprocess.Popen(argv, cwd=cwd, env=self.env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        self.owned[name] = process
        self.state["processes"][name] = process.pid
        return process

    async def monitor(self):
        while True:
            roots = {"observer": os.getpid(), **{name: proc.pid for name, proc in self.owned.items()
                                                   if proc.poll() is None}}
            rss = sampled_rss(roots)
            total = sum(rss.values())
            for pid, value in rss.items():
                self.peak_per_pid[pid] = max(self.peak_per_pid.get(pid, 0), value)
            self.state["rss_kib"] = rss
            self.state["peak_per_pid_kib"] = self.peak_per_pid
            self.state["peak_rss_kib"] = max(self.state["peak_rss_kib"], total)
            free = shutil.disk_usage(self.out).free
            self.state["disk_free_bytes"] = free
            with (self.out / "memory.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"at": utc(), "phase": self.state["phase"], "rss_kib": rss,
                                      "total_rss_kib": total, "roots": roots, "disk_free_bytes": free}) + "\n")
            self.publish()
            if free < FLOOR or total > self.max_rss_mib * 1024:
                raise RuntimeError("压力演练达到内存或磁盘停止门")
            await asyncio.sleep(0.25)

    def task(self, name, phase):
        task = {"name": name, "phase": phase, "status": "waiting"}
        self.state["tasks"].append(task)
        self.event(task)
        return task

    async def submit(self, http, task, project, data, *, invalid=False):
        started = time.monotonic()
        self.event(task, status="running")
        with data.open("rb") as payload:
            submitted = await http.post(f"{API}/runs", data={
                "project_root": project, "mode": "auto", "model_type": "ols",
                "y": "column_not_present" if invalid else "y", "x": "x1",
            }, files={"file": (data.name, payload, "text/csv")})
        if not submitted.is_success:
            status = "capacity" if submitted.status_code == 429 else ("expected_error" if
                     invalid and submitted.status_code == 422 else "error")
            self.event(task, status=status, http=submitted.status_code, detail=submitted.text[:280],
                       elapsed_s=round(time.monotonic() - started, 3))
            return
        run_id = submitted.json()["run_id"]
        slug = urlsafe_b64encode(project.encode()).decode().rstrip("=")
        self.event(task, http=submitted.status_code, run_id=run_id, url=f"{UI}/p/{slug}/graph")
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            response = await http.get(f"{API}/runs", params={"project_root": project})
            response.raise_for_status()
            run = next((row for row in response.json()["runs"] if row["run_id"] == run_id), None)
            if run and run["status"] in TERMINAL:
                status = run["status"]
                detail = await http.get(f"{API}/runs/{run_id}", params={"project_root": project})
                detail.raise_for_status()
                result = detail.json()
                with (self.out / f"{task['name']}-receipt.json").open("x", encoding="utf-8") as evidence:
                    json.dump({"run": run, "issues": result["errors"],
                               "model_families": [row.get("model_type") for row in result["model_results"]]},
                              evidence, ensure_ascii=False, indent=2)
                issues = result["errors"].get("issues", [])
                expected_error = invalid and status == "blocked" and any(
                    item.get("code") == "MODEL_COLUMNS_NOT_FOUND" for item in issues
                )
                detail = "; ".join(str(item.get("code") or item.get("message") or "") for item in issues)[:280]
                self.event(task, status="expected_error" if expected_error else status,
                           terminal=status, detail=detail, elapsed_s=round(time.monotonic() - started, 3))
                return
            await asyncio.sleep(0.15)
        self.event(task, status="error", detail="等待运行终态超过 90 秒", elapsed_s=round(time.monotonic() - started, 3))

    async def burst(self, http, phase, count, data, *, invalid=False):
        self.state["phase"] = phase
        work = []
        for i in range(count):
            name = f"{phase}-{i + 1}"
            response = await http.post(f"{API}/projects", json={"parent": str(self.out), "name": name})
            response.raise_for_status()
            work.append((self.task(name, phase), response.json()["project_root"]))
        await asyncio.gather(*(self.submit(http, task, project, data, invalid=invalid) for task, project in work))
        actual = [task["status"] for task, _ in work]
        expected = ["expected_error"] if invalid else ["completed"] + ["capacity"] * (count - 1)
        if sorted(actual) != sorted(expected):
            raise RuntimeError(f"{phase} expected {expected}, observed {actual}")

    async def replay(self, count):
        phase = f"agent-replay-{count}"
        self.state["phase"] = phase
        running = {}
        for i in range(count):
            name = f"{phase}-{i + 1}"
            task = self.task(name, phase)
            folder = self.out / name
            if folder.exists():
                raise FileExistsError(folder)
            started = time.monotonic()
            proc = self.child(name, [sys.executable, "-m", "pytest", "-q", REPLAY, "--basetemp", str(folder),
                                     "--junitxml", str(self.out / f"{name}.xml")])
            self.event(task, status="running", pid=proc.pid)
            running[name] = task, proc, started
        failures = []
        while running:
            for name, (task, proc, started) in list(running.items()):
                rc = proc.poll()
                if rc is not None:
                    if rc:
                        failures.append(name)
                    self.event(task, status="completed" if rc == 0 else "error", returncode=rc,
                               detail="严格录制回放通过" if rc == 0 else f"查看本地 {name}.log 和 {name}.xml",
                               elapsed_s=round(time.monotonic() - started, 3))
                    del running[name]
                elif time.monotonic() - started > 90:
                    self.event(task, status="error", detail="录制回放超过 90 秒")
                    raise RuntimeError(f"{task['name']} exceeded its deadline")
            await asyncio.sleep(0.1)
        if failures:
            raise RuntimeError(f"严格录制回放失败，日志已保留：{', '.join(failures)}")

    async def ready(self, http, url):
        for _ in range(80):
            try:
                if (await http.get(url, timeout=1)).is_success:
                    return
            except httpx.TransportError:
                pass
            if any(proc.poll() is not None for proc in self.owned.values()):
                raise RuntimeError("Workbench 预览启动失败，查看 backend.log/frontend.log")
            await asyncio.sleep(0.25)
        raise RuntimeError("Workbench 预览未就绪")

    async def exercise(self):
        self.child("backend", [sys.executable, "-m", "uvicorn", "workbench.app:app",
                               "--host", "127.0.0.1", "--port", "8036"])
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as http:
            await self.ready(http, f"{API}/capabilities")
            self.child("frontend", [str(ROOT / "frontend/node_modules/.bin/vite"), "--host", "127.0.0.1",
                                    "--port", "5197", "--strictPort"], ROOT / "frontend")
            await self.ready(http, f"{UI}/api/capabilities")
            await asyncio.sleep(4)
            rng = random.Random(191)
            data = self.out / "synthetic.csv"
            with data.open("x", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["y", "x1", "x2", "x3"])
                for _ in range(60_000):
                    x1, x2, x3, e = (rng.gauss(0, 1) for _ in range(4))
                    writer.writerow([round(val, 8) for val in (2.2 * x1 + e, x1, x2, x3)])
            self.state["input_sha256"] = sha256(data.read_bytes()).hexdigest()
            self.state["input_rows"] = 60_000
            await self.burst(http, "serial", 1, data)
            await self.burst(http, "parallel-4", 4, data)
            await self.burst(http, "parallel-8", 8, data)
            await self.burst(http, "invalid", 1, data, invalid=True)
            await self.burst(http, "recovery", 1, data)
            await self.replay(1)
            await self.replay(4)

    async def run(self, inspect_seconds):
        sampler = asyncio.create_task(self.monitor())
        tests = asyncio.create_task(self.exercise())
        try:
            done, _ = await asyncio.wait({sampler, tests}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            self.state.update(phase="完成", result="passed")
        except (Exception, asyncio.CancelledError) as exc:
            cancelled = isinstance(exc, asyncio.CancelledError)
            reason = "操作者取消测试" if cancelled else f"{type(exc).__name__}: {exc}"[:500]
            self.state.update(phase="中止", result="interrupted" if cancelled else "failed", error=reason)
            for task in self.state["tasks"]:
                if task["status"] == "running":
                    self.event(task, status="interrupted", detail=self.state["error"])
            raise
        finally:
            for task in (tests, sampler):
                task.cancel()
            await asyncio.gather(tests, sampler, return_exceptions=True)
            self.publish()
            (self.out / "summary.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
        if inspect_seconds:
            await asyncio.sleep(inspect_seconds)

    def close(self):
        running = [proc for proc in self.owned.values() if proc.poll() is None]
        for proc in running:
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in running:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--inspect-seconds", type=int, default=0)
    parser.add_argument("--max-rss-mib", type=int, default=4096)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / "local") or out.exists() or args.max_rss_mib <= 0:
        parser.error("a fresh output directory under local/ and a positive RSS ceiling are required")
    if shutil.disk_usage(ROOT).free < FLOOR + 500_000_000:
        parser.error("insufficient disk space for this stress run")
    for port in (5196, 5197, 8036):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                parser.error(f"test port {port} is already in use")
    out.mkdir(parents=True)
    pressure = Pressure(out, args.max_rss_mib)
    pressure.publish()
    server = ThreadingHTTPServer(("127.0.0.1", 5196), partial(NoCache, directory=str(pressure.public)))
    Thread(target=server.serve_forever, daemon=True).start()
    print(f"观测页 http://127.0.0.1:5196/ | 证据 {out}", flush=True)

    async def serve():
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
        try:
            await pressure.run(args.inspect_seconds)
        finally:
            loop.remove_signal_handler(signal.SIGTERM)

    try:
        asyncio.run(serve())
    except (asyncio.CancelledError, KeyboardInterrupt):
        return 130
    finally:
        try:
            pressure.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
