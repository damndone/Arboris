"""Rubric judges that run through the person's own CLI subscriptions.

Two independent judges from different model families -- Codex (ChatGPT
subscription, via the CLI bundled with ChatGPT.app) and Grok Build -- score
the same packets. Neither uses the DeepSeek key, and their disagreement is
measured instead of trusting either one.

Each call is locked down to "read a prompt, return JSON":

* the working directory is an empty scratch folder, so there is nothing to read;
* Codex: ``--ignore-user-config`` (no plugins, MCP servers or the ``notify``
  hook that starts Codex Computer Use), ``--ephemeral``, read-only sandbox,
  computer use, browser use and apps disabled, schema-constrained output;
* Grok: no tools, no web search, no subagents, no plan, schema-constrained.

The exact command line, prompt file and raw output are saved next to the
result so every call can be inspected afterwards.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .judge import RUBRIC

CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")
GROK = Path.home() / ".grok" / "bin" / "grok"

SCHEMA = {
    "type": "object",
    "properties": {
        key: {
            "type": "object",
            "properties": {"score": {"type": "integer", "minimum": 1, "maximum": 5}, "reason": {"type": "string"}},
            "required": ["score", "reason"],
            "additionalProperties": False,
        }
        for key in RUBRIC
    },
    "required": list(RUBRIC),
    "additionalProperties": False,
}

INSTRUCTION = (
    "You are grading one statistical analysis. Do not run commands or read files: everything you need is in "
    "this message. Reply with the JSON object only.\n\n"
)


def command(backend: str, workdir: Path, prompt_file: Path, schema_file: Path, out_file: Path) -> list[str]:
    if backend == "codex":
        return [str(CODEX), "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
                "-s", "read-only", "--disable", "computer_use", "--disable", "browser_use", "--disable", "apps",
                "-C", str(workdir), "--output-schema", str(schema_file), "-o", str(out_file), "-"]
    if backend == "grok":
        return [str(GROK), "--prompt-file", str(prompt_file), "--json-schema", json.dumps(SCHEMA),
                "--cwd", str(workdir), "--tools", "", "--disable-web-search", "--no-subagents", "--no-plan",
                "--output-format", "json"]
    raise ValueError(f"unknown judge backend: {backend}")


def run(backend: str, prompt: str, record_dir: Path, *, timeout_s: float = 600) -> dict[str, Any]:
    """Run one judge call; keep the command, prompt and raw output in ``record_dir``."""

    record_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = record_dir / f"{backend}.prompt.txt"
    prompt_file.write_text(INSTRUCTION + prompt, encoding="utf-8")
    schema_file = record_dir / "schema.json"
    schema_file.write_text(json.dumps(SCHEMA, indent=1), encoding="utf-8")
    out_file = record_dir / f"{backend}.last_message.json"
    with tempfile.TemporaryDirectory(prefix="judge-empty-") as empty:
        argv = command(backend, Path(empty), prompt_file, schema_file, out_file)
        (record_dir / f"{backend}.command.txt").write_text(shlex.join(argv), encoding="utf-8")
        started = time.monotonic()
        completed = subprocess.run(argv, input=prompt_file.read_text(encoding="utf-8") if backend == "codex" else None,
                                   capture_output=True, text=True, timeout=timeout_s, cwd=empty)
        elapsed = round(time.monotonic() - started, 1)
    (record_dir / f"{backend}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (record_dir / f"{backend}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return {"error": f"exit {completed.returncode}", "elapsed_s": elapsed}
    text = out_file.read_text(encoding="utf-8") if backend == "codex" and out_file.exists() else completed.stdout
    if backend == "grok":
        envelope = json.loads(text)
        text = envelope.get("text") or json.dumps(envelope.get("structured_output") or {})
    scores = json.loads(text)
    return {"scores": {k: {"score": int(v["score"]), "reason": v["reason"]} for k, v in scores.items()},
            "elapsed_s": elapsed}
