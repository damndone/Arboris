"""CLI boundary for the structural outbound judge packet.

Live CLI review is disabled. A temporary working directory and read-only
options do not establish host-file containment.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from . import judge

CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex")
GROK = Path.home() / ".grok" / "bin" / "grok"

SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["insufficient_evidence"]}},
    "required": ["status"],
    "additionalProperties": False,
}


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


def run(backend: str, packet: judge.OutboundPacket, record_dir: Path, *, timeout_s: float = 600) -> dict[str, Any]:
    """Validate typed evidence and gate the transport before launching a CLI."""
    prompt = judge.OUTBOUND_SYSTEM + "\n\n" + judge.outbound_prompt(packet)
    judge.require_outbound_approval()

    record_dir = record_dir.resolve()
    record_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="judge-outbound-") as empty:
        scratch = Path(empty)
        prompt_file, schema_file, out_file = (scratch / name for name in ("prompt.txt", "schema.json", "result.json"))
        argv = command(backend, scratch, prompt_file, schema_file, out_file)
        prompt_file.write_text(prompt, encoding="utf-8")
        schema_file.write_text(json.dumps(SCHEMA, indent=1), encoding="utf-8")
        (record_dir / f"{backend}.prompt.txt").write_text(prompt, encoding="utf-8")
        (record_dir / f"{backend}.command.txt").write_text(shlex.join(argv), encoding="utf-8")
        started = time.monotonic()
        completed = subprocess.run(argv, input=prompt if backend == "codex" else None,
                                   capture_output=True, text=True, timeout=timeout_s, cwd=empty)
        elapsed = round(time.monotonic() - started, 1)
        text = out_file.read_text(encoding="utf-8") if backend == "codex" and out_file.exists() else completed.stdout
    (record_dir / f"{backend}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (record_dir / f"{backend}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return {"protocol": judge.OUTBOUND_PROTOCOL, "status": "unscored",
                "reason": f"exit {completed.returncode}", "elapsed_s": elapsed}
    if backend == "grok":
        envelope = json.loads(text)
        text = envelope.get("text") or json.dumps(envelope.get("structured_output") or {})
    return {**judge.outbound_result(text), "elapsed_s": elapsed}
