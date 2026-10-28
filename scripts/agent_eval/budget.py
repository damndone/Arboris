"""Native-CNY peak-price cap; retain the user's M4 USD table for comparison."""
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import json
import shutil
import time
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


class TaskStop(BaseException):
    """Bypass product retry handlers and end this task only; the round goes on.

    Free route (2026-10-22): models that stalled repeatedly on one task (WorkBuddy
    Hy3 and Step-5, no first byte for 90 s on large contexts) ended the whole round
    under a per-round count, so one slow task voided the rest.
    """


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
        if any(type(usage.get(field)) is not int or usage[field] < 0
               for field in ('prompt_tokens', 'completion_tokens')):
            self.stop('free route reported missing or invalid token usage; stopping before any further call')
            raise BudgetStop(self.state['reason'])
        with self._change() as state:
            state["calls"] += 1
            state["prompt_tokens"] += usage['prompt_tokens']
            state["completion_tokens"] += usage['completion_tokens']

    def refused(self, status, body):
        """A response without usage: say why, from the provider's own message.

        off4b (2026-10-22): a 429 frequency limit was reported as "credit None",
        hiding that the route was exhausted until its reset time.
        """
        try:
            message = str(json.loads(body)["error"]["message"])
        except (ValueError, KeyError, TypeError):
            message = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
        message = " ".join(message.split())[:300]
        what = "rate-limited (HTTP 429)" if status == 429 else f"refused the call (HTTP {status})"
        self.stop(f"free route {what}: {message}")
        raise BudgetStop(self.state["reason"])

    def unreachable(self, error):
        """No connection to the gateway: stop the round now (off4: the first task spent all
        its nudges in seconds on ConnectError while the gateway was down)."""
        self.stop(f"free route gateway {self._identity[1]} unreachable ({error}); no request was sent")
        raise BudgetStop(self.state["reason"])

    def tolerate_transport_interruption(self, error: str, task: str | None = None) -> bool:
        """Recorder hook: preserve the interruption and refuse unknown-usage retry.

        The user-approved 2026-10-27 protocol stops the entire round at the first
        unknown usage. A free catalog entry cannot establish an interrupted
        request's actual usage or bill; the prior three-interruption allowance
        is no longer an authorized policy.
        """
        with self._change() as state:
            state.setdefault("transport_interruptions", []).append({"task": task, "error": error})
            state.update(stopped=True, reason=f'unknown usage after free-route {error}; no further call authorized')
        raise BudgetStop(self.state['reason'])

    def resume_storage_stop(self):
        with self._change() as state:
            if state["stopped"] and str(state["reason"]).startswith("storage threshold"):
                state.update(stopped=False, reason=None)


NVIDIA_PROVIDER_ID = "nvidia-nemotron-free"
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


class NvidiaFreeEndpointGuard(FreeRouteGuard):
    """Explicit free-listed endpoint authorization, not a zero-cost billing claim.

    Request reservations and start times survive both modes/process restarts.
    Missing billing metadata remains unknown; missing token usage stops the round.
    """

    _change = RoundBudget._change

    def __init__(self, path, *, provider_id, base_url, model, round_kind):
        if (provider_id, base_url, model) != (NVIDIA_PROVIDER_ID, NVIDIA_BASE_URL, NVIDIA_MODEL):
            raise ValueError("NVIDIA evaluation requires the exact authorized provider, base URL and Ultra model")
        if round_kind not in {"dev8", "qrdata40"}:
            raise ValueError("NVIDIA evaluation supports only dev8 or qrdata40")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock")
        self._identity = (provider_id, base_url)
        self.round_kind = round_kind
        self.request_limit = 240 if round_kind == "dev8" else 1200
        with self._change() as state:
            expected = {"schema": "nvidia-free-endpoint/v1", "provider_id": provider_id,
                "base_url": base_url, "model": model, "round_kind": round_kind,
                "request_limit": self.request_limit, "output_token_limit": 32768,
                "min_start_interval_s": 2}
            if any(state.get(key) != value for key, value in expected.items()):
                raise ValueError("NVIDIA ledger configuration changed; use a separate round ledger")

    @property
    def state(self):
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"schema": "nvidia-free-endpoint/v1", "provider_id": NVIDIA_PROVIDER_ID,
            "base_url": NVIDIA_BASE_URL, "model": NVIDIA_MODEL, "round_kind": self.round_kind,
            "request_limit": self.request_limit, "output_token_limit": 32768, "min_start_interval_s": 2,
            "requests": 0, "calls": 0, "last_start": None, "reservations": {}, "charges": [],
            "prompt_tokens": 0, "completion_tokens": 0, "stopped": False, "reason": None,
            "billing_status": "unknown; free-listed endpoint is not billing certification"}

    def check_request(self, request):
        if str(request.url) != NVIDIA_BASE_URL + "/chat/completions":
            self.stop("NVIDIA actual request URL differs from the authorized endpoint; no fallback allowed")
            raise BudgetStop(self.state["reason"])

    def check_response(self, status, body):
        if status != 200:
            self.refused(status, body)
        payloads = [body]
        payloads.extend(line[5:].strip() for line in body.splitlines() if line.startswith(b"data:"))
        for raw in payloads:
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict) and "error" in payload:
                error = payload["error"]
                code = error.get("code") if isinstance(error, dict) else None
                code_label = f" ({code})" if type(code) in (int, str) else ""
                usage_note = "usage unknown" if not isinstance(payload.get("usage"), dict) else "usage not settled"
                self.stop(f"NVIDIA provider error{code_label} in HTTP 200 response; {usage_note}; no further request authorized")
                raise BudgetStop(self.state["reason"])

    def reserve(self, body):
        if shutil.disk_usage(self.path.parent).free < 5_000_000_000:
            self.stop("storage threshold: less than 5 GB free before NVIDIA request")
            raise BudgetStop(self.state["reason"])
        try:
            request = json.loads(body)
            if not isinstance(request, dict) or request.get("model") != NVIDIA_MODEL:
                raise ValueError("unauthorized actual request model")
            output = request.get("max_tokens", request.get("max_completion_tokens"))
            for field in ("max_tokens", "max_completion_tokens"):
                if field in request and (type(request[field]) is not int or not 0 < request[field] <= 32768):
                    raise ValueError("unbounded actual output token limit")
        except (ValueError, TypeError) as exc:
            self.stop(f"NVIDIA request rejected: {exc}")
            raise BudgetStop(self.state["reason"])
        key = uuid4().hex
        refused = False
        with self._change() as state:
            reason = state["reason"] if state["stopped"] else None
            if not reason and state["reservations"]:
                reason = "NVIDIA unsettled request; parallel calls or unknown-usage restart forbidden"
            if not reason and state["requests"] >= self.request_limit:
                reason = "NVIDIA durable round request limit reached"
            if reason:
                state.update(stopped=True, reason=reason)
                refused = True
            else:
                if state["last_start"] is not None:
                    time.sleep(max(0, state["last_start"] + 2 - time.time()))
                state["last_start"] = time.time()
                state["requests"] += 1
                state["reservations"][key] = {"started_at": state["last_start"], "output_bound": output,
                    "output_limit": "provider_default_unverified" if output is None else output}
        if refused:
            raise BudgetStop(self.state["reason"])
        return key

    def settle(self, key, usage):
        reason = None
        if not isinstance(usage, dict) or any(type(usage.get(field)) is not int or usage[field] < 0
                for field in ("prompt_tokens", "completion_tokens")):
            reason = "NVIDIA missing or invalid token usage; unknown usage stops the round"
        elif "credit" in usage and (type(usage["credit"]) not in (int, float) or usage["credit"] != 0):
            reason = f"NVIDIA reported credit {usage['credit']!r}; no further request authorized"
        with self._change() as state:
            reservation = state["reservations"].get(key)
            if not reason and (reservation is None or (reservation["output_bound"] is not None
                    and usage["completion_tokens"] > reservation["output_bound"])):
                reason = "NVIDIA usage exceeds reserved output bound or has no reservation"
            if reason:
                state.update(stopped=True, reason=reason)
            else:
                state["reservations"].pop(key)
                state["calls"] += 1
                state["prompt_tokens"] += usage["prompt_tokens"]
                state["completion_tokens"] += usage["completion_tokens"]
                state["charges"].append({"key": key, "usage": usage,
                    "billing_status": "reported zero credit" if "credit" in usage else "unknown; credit not reported"})
        if reason:
            raise BudgetStop(reason)

    def unreachable(self, error):
        self.stop(f"NVIDIA endpoint connection failed ({error}); stop the round; billing remains unknown")
        raise BudgetStop(self.state["reason"])

    def resume_storage_stop(self):
        raise BudgetStop("NVIDIA storage floor cannot be bypassed for this round")
