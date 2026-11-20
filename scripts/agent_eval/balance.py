"""Read the provider account balance in CNY (DeepSeek /user/balance); no model call, no cost."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))


def cny_balance() -> str:
    import httpx

    from workbench.llm.config import load_llm_config

    config = load_llm_config()
    response = httpx.get(config.base_url.rstrip("/") + "/user/balance",
                         headers={"Authorization": "Bearer " + config.api_key}, timeout=20)
    response.raise_for_status()
    # The entries' order is not fixed: pick the currency, never the first entry.
    for entry in response.json().get("balance_infos") or []:
        if entry.get("currency") == "CNY":
            return entry["total_balance"]
    return "unknown"


if __name__ == "__main__":
    print(cny_balance())
