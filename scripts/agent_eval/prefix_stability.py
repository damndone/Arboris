"""How much of each replayed request a prompt cache could reuse: within a task and across tasks.

Reads the replayed_requests.jsonl lines a replay writes (scripts/agent_eval/recorder.py, one line
per request: the tools' and each message's SHA-256) and reports
- per task, whether every request extends the previous one byte for byte (append-only), and where not;
- across tasks, how many distinct leading prefixes there are of 1, 2, ... messages, and their size.

Run: .venv/bin/python scripts/agent_eval/prefix_stability.py <replay out folder> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _requests(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def report(folder: Path) -> dict:
    tasks = {}
    first_requests = []
    for path in sorted(folder.glob("qrdata40/ask/*/tasks/*/replayed_requests.jsonl")):
        requests = _requests(path)
        if not requests:
            continue
        breaks = []
        for index, (earlier, later) in enumerate(zip(requests, requests[1:]), start=1):
            old = [message["sha256"] for message in earlier["messages"]]
            new = [message["sha256"] for message in later["messages"]]
            if new[: len(old)] != old or later["tools_sha256"] != earlier["tools_sha256"]:
                shared = next((k for k, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
                breaks.append({"request": index, "shared_messages": shared, "of": len(old),
                               "tools_changed": later["tools_sha256"] != earlier["tools_sha256"]})
        tasks[path.parts[-4]] = {"requests": len(requests), "breaks": breaks}
        first_requests.append(requests[0])
    across = []
    for k in range(1, 9):
        heads = {(request["tools_sha256"], tuple(message["sha256"] for message in request["messages"][:k]))
                 for request in first_requests if len(request["messages"]) >= k}
        chars = sorted(sum(message["chars"] for message in request["messages"][:k]) for request in first_requests)
        roles = sorted({request["messages"][k - 1]["role"] for request in first_requests if len(request["messages"]) >= k})
        across.append({"leading_messages": k, "distinct": len(heads), "tasks": len(first_requests),
                       "median_chars": chars[len(chars) // 2] if chars else 0, "roles": roles})
    return {"tasks": tasks,
            "transitions": sum(max(task["requests"] - 1, 0) for task in tasks.values()),
            "breaks": sum(len(task["breaks"]) for task in tasks.values()),
            "distinct_tools": len({request["tools_sha256"] for request in first_requests}),
            "across_tasks": across}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = report(args.folder)
    if args.json:
        args.json.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"tasks {len(result['tasks'])}, request transitions {result['transitions']}, prefix breaks {result['breaks']}, "
          f"distinct tool definitions {result['distinct_tools']}")
    for row in result["across_tasks"]:
        print(f"first {row['leading_messages']} message(s): {row['distinct']} distinct over {row['tasks']} tasks, "
              f"median {row['median_chars']} chars, roles {row['roles']}")


if __name__ == "__main__":
    main()
