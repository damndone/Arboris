"""One durable paid-round cap, using the user's archived M4 USD price table."""
from contextlib import contextmanager
from decimal import Decimal
import json
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

MISS = Decimal("0.14") / 1_000_000
HIT = Decimal("0.0028") / 1_000_000
OUTPUT = Decimal("0.28") / 1_000_000
# A conservative accounting multiplier, NOT a current exchange-rate quote.
# Actual CNY billing is separately reconciled from before/after balance.
CNY_PER_USD = Decimal("8")


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
        return {"schema": 1, "cap_cny": str(self.cap), "context_tokens": self.context_tokens,
            "cny_per_usd_accounting_upper": str(CNY_PER_USD), "spent_usd": "0",
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

    def reserve(self, body):
        request = json.loads(body)
        # No request override: absent max_tokens reserves the entire pinned
        # context window. A byte upper bound plus framing is conservative for
        # this UTF-8 tokenizer; all prompt tokens are priced as cache misses.
        output_bound = request.get("max_tokens", self.context_tokens)
        if type(output_bound) is not int or not 0 < output_bound <= self.context_tokens:
            self.stop("unbounded output request")
            raise BudgetStop("unbounded output request")
        ceiling = ((len(body) + 2048) * MISS + output_bound * OUTPUT) * CNY_PER_USD
        key = uuid4().hex
        refused = False
        with self._change() as state:
            reserved = sum(map(Decimal, state["reservations"].values()), Decimal(0))
            if state["stopped"] or Decimal(state["spent_usd"]) * CNY_PER_USD + reserved + ceiling > self.cap:
                state.update(stopped=True, reason="remaining cap cannot cover the next request's worst case")
                refused = True
            else:
                state["reservations"][key] = str(ceiling)
        if refused:
            raise BudgetStop(self.state["reason"])
        return key

    def settle(self, key, usage):
        try:
            cost = cost_usd(usage)
        except ValueError:
            self.stop("unknown usage; keep worst-case reservation and stop")
            raise BudgetStop("unknown usage; cannot safely continue")
        with self._change() as state:
            reserved = Decimal(state["reservations"].pop(key))
            state["spent_usd"] = str(Decimal(state["spent_usd"]) + cost)
            state["charges"].append({"key": key, "usage": usage, "cost_usd": str(cost)})
            if cost * CNY_PER_USD > reserved or Decimal(state["spent_usd"]) * CNY_PER_USD >= self.cap:
                state.update(stopped=True, reason="cost bound reached")
        if self.stopped:
            raise BudgetStop(self.state["reason"])
