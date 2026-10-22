"""Native-CNY peak-price cap; retain the user's M4 USD table for comparison."""
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

MISS = Decimal("0.14") / 1_000_000
HIT = Decimal("0.0028") / 1_000_000
OUTPUT = Decimal("0.28") / 1_000_000
# Historical comparison only: NOT a guaranteed CNY billing bound.
CNY_PER_USD = Decimal("8")
CNY_MISS = Decimal("2") / 1_000_000
CNY_HIT = Decimal("0.04") / 1_000_000
CNY_OUTPUT = Decimal("8") / 1_000_000
QUOTE = "deepseek-flash-cny-peak-2026-10-21"
# https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
# https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/


class BudgetStop(BaseException):
    """Bypass product retry handlers and stop the entire paid evaluation round."""


def cost_usd(usage):
    if not isinstance(usage, dict):
        raise ValueError("missing usage")
    prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
    hit = usage.get("prompt_cache_hit_tokens", 0)
    if any(type(v) is not int or v < 0 for v in (prompt, output, hit)) or hit > prompt:
        raise ValueError("invalid usage")
    miss = usage.get("prompt_cache_miss_tokens", prompt - hit)
    if type(miss) is not int or miss < 0 or miss + hit != prompt:
        raise ValueError("inconsistent usage")
    return miss * MISS + hit * HIT + output * OUTPUT


def cost_cny_upper(usage):
    cost_usd(usage)  # Validate the original external usage with the same definitions.
    hit = usage.get("prompt_cache_hit_tokens", 0)
    return ((usage["prompt_tokens"] - hit) * CNY_MISS + hit * CNY_HIT
            + usage["completion_tokens"] * CNY_OUTPUT)


class RoundBudget:
    def __init__(self, path, *, cap_cny, context_tokens):
        self.path = Path(path)
        self.cap = Decimal(str(cap_cny))
        self.context_tokens = context_tokens
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock")
        with self._change() as state:
            if Decimal(state["cap_cny"]) != self.cap or state["context_tokens"] != context_tokens:
                raise ValueError("round budget configuration changed")
            if state["schema"] == 1:
                if state["reservations"]:
                    raise ValueError("unsettled old reservations need billing reconciliation before migration")
                original = self.path.read_bytes()
                backup = self.path.with_suffix(".v1.json")
                if backup.exists():
                    if backup.read_bytes() != original:
                        raise ValueError("prior ledger backup differs")
                else:
                    with backup.open("xb") as stream:
                        stream.write(original)
                for charge in state["charges"]:
                    charge["cost_cny_upper"] = str(cost_cny_upper(charge["usage"]))
                state.update(schema=2, quote=QUOTE,
                    spent_cny_upper=str(sum((cost_cny_upper(c["usage"]) for c in state["charges"]), Decimal(0))),
                    prior_ledger_sha256=hashlib.sha256(original).hexdigest())
            if state["quote"] != QUOTE:
                raise ValueError("round tariff quote changed")

    @contextmanager
    def _change(self):
        with self.lock:
            state = self.state
            yield state
            temp = self.path.with_suffix(".tmp")
            with temp.open("w") as stream:
                json.dump(state, stream, indent=2)
                stream.flush()
                import os
                os.fsync(stream.fileno())
            temp.replace(self.path)

    @property
    def state(self):
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"schema": 2, "cap_cny": str(self.cap), "context_tokens": self.context_tokens,
            "quote": QUOTE, "m4_comparison_cny_factor": str(CNY_PER_USD),
            "spent_usd": "0", "spent_cny_upper": "0",
            "reservations": {}, "charges": [], "stopped": False, "reason": None}

    @property
    def spent_usd(self):
        return Decimal(self.state["spent_usd"])

    @property
    def stopped(self):
        return self.state["stopped"]

    def stop(self, reason):
        with self._change() as state:
            state.update(stopped=True, reason=reason)

    def resume_storage_stop(self):
        """Apply the user's one-round storage exception without resetting spending."""
        with self._change() as state:
            if not state["stopped"]:
                return
            if (not str(state["reason"]).startswith("storage threshold")
                    or state["reservations"]
                    or Decimal(state["spent_cny_upper"]) >= self.cap):
                raise BudgetStop("storage exception cannot release a financial stop")
            state["storage_exception"] = {"previous_reason": state["reason"]}
            state.update(stopped=False, reason=None)

    def reserve(self, body):
        request = json.loads(body)
        # Observe documented server defaults; do not override the request.
        # All prompt bytes plus framing are reserved at the native peak miss price.
        effort = request.get("reasoning_effort", "high")
        disabled = effort == "none" or (request.get("thinking") or {}).get("type") == "disabled"
        default_output = 8192 if disabled else (131072 if effort == "max" else 65536)
        output_bound = request.get("max_tokens")
        if output_bound is None:
            output_bound = default_output
        if type(output_bound) is not int or not 0 < output_bound <= min(self.context_tokens, 393216):
            self.stop("unbounded output request")
            raise BudgetStop("unbounded output request")
        ceiling = (len(body) + 2048) * CNY_MISS + output_bound * CNY_OUTPUT
        key = uuid4().hex
        refused = False
        with self._change() as state:
            reserved = sum(map(Decimal, state["reservations"].values()), Decimal(0))
            if state["stopped"] or Decimal(state["spent_cny_upper"]) + reserved + ceiling > self.cap:
                state.update(stopped=True, reason="remaining cap cannot cover the next request's worst case")
                refused = True
            else:
                state["reservations"][key] = str(ceiling)
        if refused:
            raise BudgetStop(self.state["reason"])
        return key

    def release(self, key):
        """Return a reservation whose request never reached the provider (nothing can be billed)."""
        with self._change() as state:
            state["reservations"].pop(key, None)
            state.setdefault("released", []).append(key)

    def settle(self, key, usage):
        try:
            cost = cost_usd(usage)
            cost_cny = cost_cny_upper(usage)
        except ValueError:
            self.stop("unknown usage; keep worst-case reservation and stop")
            raise BudgetStop("unknown usage; cannot safely continue")
        with self._change() as state:
            reserved = Decimal(state["reservations"].pop(key))
            state["spent_usd"] = str(Decimal(state["spent_usd"]) + cost)
            state["spent_cny_upper"] = str(Decimal(state["spent_cny_upper"]) + cost_cny)
            state["charges"].append({"key": key, "usage": usage, "cost_usd": str(cost), "cost_cny_upper": str(cost_cny)})
            if cost_cny > reserved or Decimal(state["spent_cny_upper"]) >= self.cap:
                state.update(stopped=True, reason="cost bound reached")
        if self.stopped:
            raise BudgetStop(self.state["reason"])


FREE_PROVIDER_ID = "magpie-workbuddy-ai"


class FreeRouteGuard:
    """The budget hook for the free Magpie -> WorkBuddy route: every response must report zero credit.

    Runs on this route carry no CNY cap, so the guard instead proves each call was
    free: the saved free provider is required before the round, and a response with
    a missing or non-zero ``usage.credit`` (a paid fallback, a changed tariff, an
    unreadable usage) stops the whole round, like a budget stop.
    """

    def __init__(self, path, *, provider_id, base_url):
        if provider_id != FREE_PROVIDER_ID:
            raise ValueError(f"the free route requires provider {FREE_PROVIDER_ID!r}, got {provider_id!r}")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock")
        self._identity = (provider_id, base_url)
        with self._change() as state:
            if state["provider_id"] != provider_id or state["base_url"] != base_url:
                raise ValueError("free-route ledger belongs to another provider")

    @contextmanager
    def _change(self):
        with self.lock:
            state = self.state
            yield state
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(state, indent=2))
            temp.replace(self.path)

    @property
    def state(self):
        if self.path.exists():
            return json.loads(self.path.read_text())
        provider_id, base_url = self._identity
        return {"schema": "free-route/v1", "provider_id": provider_id, "base_url": base_url, "calls": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "stopped": False, "reason": None}

    @property
    def stopped(self):
        return self.state["stopped"]

    def stop(self, reason):
        with self._change() as state:
            state.update(stopped=True, reason=reason)

    def reserve(self, body):
        if self.stopped:
            raise BudgetStop(self.state["reason"])
        return uuid4().hex

    def release(self, key):
        return None

    def settle(self, key, usage):
        credit = usage.get("credit") if isinstance(usage, dict) else None
        if type(credit) not in (int, float) or credit != 0:
            self.stop(f"free route reported credit {credit!r}; stopping before any further call")
            raise BudgetStop(self.state["reason"])
        with self._change() as state:
            state["calls"] += 1
            state["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            state["completion_tokens"] += int(usage.get("completion_tokens") or 0)

    def resume_storage_stop(self):
        with self._change() as state:
            if state["stopped"] and str(state["reason"]).startswith("storage threshold"):
                state.update(stopped=False, reason=None)
