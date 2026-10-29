"""Native-CNY peak-price cap; retain the user's M4 USD table for comparison."""
from contextlib import contextmanager
import asyncio
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


class NvidiaOverloadRetry(BaseException):
    """Consumed only by the explicitly installed evaluation stream wrapper."""

    def __init__(self, ticket, delay_s):
        self.ticket, self.delay_s = ticket, delay_s
        super().__init__(f"authorized NVIDIA overload retry after {delay_s}s")


class NvidiaOverloadRecovery(FreeRouteGuard):
    """One durable retry allowance shared by the authorized dev8 and QRData40 rounds."""

    _change = RoundBudget._change

    def __init__(self, path, *, unanswered_read_errors=False, unanswered_protocol_errors=False,
                 complete_http_500_errors=False):
        self.unanswered_read_errors = unanswered_read_errors
        self.unanswered_protocol_errors = unanswered_protocol_errors
        self.complete_http_500_errors = complete_http_500_errors
        if unanswered_protocol_errors and not unanswered_read_errors:
            raise ValueError("protocol recovery requires the explicit unanswered-read recovery policy")
        if complete_http_500_errors and not unanswered_protocol_errors:
            raise ValueError("complete HTTP500 recovery requires the explicit v3 recovery policies")
        self.schema = "nvidia-overload-recovery/v4" if complete_http_500_errors else "nvidia-overload-recovery/v3" if unanswered_protocol_errors else "nvidia-overload-recovery/v2" if unanswered_read_errors else "nvidia-overload-recovery/v1"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock")
        with self._change() as state:
            expected = {"schema": self.schema, "provider_id": NVIDIA_PROVIDER_ID,
                "base_url": NVIDIA_BASE_URL, "model": NVIDIA_MODEL, "retry_limit": 10,
                "per_request_retry_limit": 2, "delays_s": [60, 120]}
            if unanswered_read_errors:
                expected["unanswered_read_errors"] = True
            if unanswered_protocol_errors:
                expected["unanswered_protocol_errors"] = True
            if complete_http_500_errors:
                expected["complete_http_500_errors"] = True
            if any(state.get(key) != value for key, value in expected.items()):
                raise ValueError("NVIDIA shared overload recovery configuration changed")

    @property
    def state(self):
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"schema": self.schema, "provider_id": NVIDIA_PROVIDER_ID,
            "base_url": NVIDIA_BASE_URL, "model": NVIDIA_MODEL, "retry_limit": 10,
            "per_request_retry_limit": 2, "delays_s": [60, 120], "retries": 0,
            "request_retries": {}, "tickets": {}, "pending": None, "manual_restarts": {},
            "stopped": False, "reason": None,
            **({"unanswered_read_errors": True} if self.unanswered_read_errors else {}),
            **({"unanswered_protocol_errors": True} if self.unanswered_protocol_errors else {}),
            **({"complete_http_500_errors": True} if self.complete_http_500_errors else {})}

    def record_manual_restart(self, *, source_path, reason):
        """Charge the explicitly approved task restart once, without settling any request."""
        identity = hashlib.sha256(json.dumps([str(source_path), reason]).encode()).hexdigest()
        refused = None
        with self._change() as state:
            if identity in state["manual_restarts"]:
                return
            if state["stopped"] or state["retries"] >= 10 or state["pending"]:
                refused = "NVIDIA shared recovery allowance cannot authorize a manual restart"
                state.update(stopped=True, reason=refused)
            else:
                state["retries"] += 1
                state["manual_restarts"][identity] = {"kind": "manual_task_restart",
                    "source_path": str(source_path), "reason": reason, "at": time.time()}
        if refused:
            raise BudgetStop(refused)

    def claim(self, request_sha256, *, round_ledger, reservation):
        refused, ticket, delay = None, uuid4().hex, None
        with self._change() as state:
            count = state["request_retries"].get(request_sha256, 0)
            if state["stopped"]:
                refused = state["reason"]
            elif state["pending"]:
                refused = "NVIDIA pending recovery ticket forbids parallel recovery"
            elif state["retries"] >= 10:
                refused = "NVIDIA shared recovery retry limit reached"
            elif count >= 2:
                refused = "NVIDIA per-request overload retry limit reached"
            if refused:
                state.update(stopped=True, reason=refused)
            else:
                delay = [60, 120][count]
                state["retries"] += 1
                state["request_retries"][request_sha256] = count + 1
                state["tickets"][ticket] = {"request_sha256": request_sha256,
                    "round_ledger": str(round_ledger), "reservation": reservation,
                    "delay_s": delay, "ready_at": time.time() + delay, "status": "waiting"}
                state["pending"] = ticket
        if refused:
            raise BudgetStop(refused)
        return NvidiaOverloadRetry(ticket, delay)

    def ready(self, ticket):
        refused = None
        with self._change() as state:
            entry = state["tickets"].get(ticket)
            if (state["stopped"] or state["pending"] != ticket or entry is None
                    or entry["status"] != "waiting" or time.time() < entry["ready_at"]):
                refused = "NVIDIA pending recovery ticket cannot resume"
                state.update(stopped=True, reason=refused)
            else:
                entry["status"] = "ready"
        if refused:
            raise BudgetStop(refused)

    def before_send(self, request_sha256, ticket):
        refused = None
        with self._change() as state:
            if state["stopped"]:
                refused = state["reason"]
            elif state["pending"]:
                entry = state["tickets"][state["pending"]]
                if (ticket != state["pending"] or entry["status"] != "ready"
                        or entry["request_sha256"] != request_sha256):
                    refused = "NVIDIA pending recovery requires its original sender and payload; restart refused"
                else:
                    entry["status"] = "sent"
                    state["pending"] = None
            if refused:
                state.update(stopped=True, reason=refused)
        if refused:
            raise BudgetStop(refused)


class NvidiaFreeEndpointGuard(FreeRouteGuard):
    """Explicit free-listed endpoint authorization, not a zero-cost billing claim.

    Request reservations and start times survive both modes/process restarts.
    Missing billing metadata remains unknown; missing token usage stops the round.
    """

    _change = RoundBudget._change

    def __init__(self, path, *, provider_id, base_url, model, round_kind, overload_recovery_ledger=None,
                 recover_unanswered_read_errors=False, allow_low_space_this_round=False,
                 recover_unanswered_protocol_errors=False, skip_incomplete_stream_task=False,
                 recover_complete_http_500_errors=False, shared_serial_ledger=None):
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
        self.overload_recovery = None
        self.serial_coordinator = None
        self.recover_unanswered_read_errors = recover_unanswered_read_errors
        self.recover_unanswered_protocol_errors = recover_unanswered_protocol_errors
        self.recover_complete_http_500_errors = recover_complete_http_500_errors
        self.allow_low_space_this_round = allow_low_space_this_round
        self.skip_incomplete_stream_task = skip_incomplete_stream_task
        self._retry_ticket = None
        if recover_unanswered_read_errors and overload_recovery_ledger is None:
            raise ValueError("unanswered ReadError recovery requires its explicit shared recovery ledger")
        if recover_unanswered_protocol_errors and not recover_unanswered_read_errors:
            raise ValueError("protocol recovery requires the explicit unanswered-read recovery policy")
        if recover_complete_http_500_errors and not recover_unanswered_protocol_errors:
            raise ValueError("complete HTTP500 recovery requires the explicit v3 recovery policies")
        if overload_recovery_ledger is not None:
            if self.path.resolve() == Path(overload_recovery_ledger).resolve():
                raise ValueError("NVIDIA request and recovery ledgers must be separate")
            self.overload_recovery = NvidiaOverloadRecovery(overload_recovery_ledger,
                unanswered_read_errors=recover_unanswered_read_errors,
                unanswered_protocol_errors=recover_unanswered_protocol_errors,
                complete_http_500_errors=recover_complete_http_500_errors)
        with self._change() as state:
            if state.get("allow_low_space_this_round", False) != allow_low_space_this_round:
                raise ValueError("NVIDIA ledger storage policy changed; use a separate round ledger")
            state["allow_low_space_this_round"] = allow_low_space_this_round
            if state.get("skip_incomplete_stream_task", False) != skip_incomplete_stream_task:
                raise ValueError("NVIDIA incomplete-stream policy changed; use a separate round ledger")
            state["skip_incomplete_stream_task"] = skip_incomplete_stream_task
            expected = {"schema": "nvidia-free-endpoint/v1", "provider_id": provider_id,
                "base_url": base_url, "model": model, "round_kind": round_kind,
                "request_limit": self.request_limit, "output_token_limit": 32768,
                "min_start_interval_s": 2}
            if any(state.get(key) != value for key, value in expected.items()):
                raise ValueError("NVIDIA ledger configuration changed; use a separate round ledger")
            recovery_path = str(Path(overload_recovery_ledger).resolve()) if overload_recovery_ledger is not None else None
            bound_path = state.get("overload_recovery_ledger")
            if bound_path is not None and bound_path != recovery_path:
                raise ValueError("NVIDIA round requires its original overload recovery ledger")
            if recovery_path is not None:
                state["overload_recovery_ledger"] = recovery_path
            serial_path = str(Path(shared_serial_ledger).resolve()) if shared_serial_ledger is not None else None
            if state.get("shared_serial_ledger") not in (None, serial_path):
                raise ValueError("NVIDIA round requires its original shared serial ledger")
            if serial_path is not None:
                if serial_path in {str(self.path.resolve()), recovery_path}:
                    raise ValueError("NVIDIA serial, request and recovery ledgers must be separate")
                state["shared_serial_ledger"] = serial_path
        if shared_serial_ledger is not None:
            from .nvidia_serial import NvidiaSerialCoordinator
            self.serial_coordinator = NvidiaSerialCoordinator(shared_serial_ledger)

    @property
    def stopped(self):
        return self.state["stopped"] or self.serial_coordinator is not None and self.serial_coordinator.stopped

    @property
    def serial_queue_wait_s(self):
        return self.serial_coordinator.wait_s if self.serial_coordinator is not None else 0.0

    def stop(self, reason):
        super().stop(reason)
        if self.serial_coordinator is not None:
            self.serial_coordinator.stop(reason)

    async def wait_for_request_slot(self, abort_event=None):
        if self.serial_coordinator is not None:
            try:
                await self.serial_coordinator.acquire(abort_event)
            except BudgetStop as exc:
                self.stop(str(exc))
                raise

    def close_request_slot(self):
        if self.serial_coordinator is not None:
            pending = self.overload_recovery is not None and self.overload_recovery.state["pending"]
            self.serial_coordinator.release(preserve_unknown=bool(self.state["reservations"] or pending))

    def tolerate_transport_interruption(self, error, task=None):
        try:
            return super().tolerate_transport_interruption(error, task)
        except BudgetStop as exc:
            if self.serial_coordinator is not None:
                self.serial_coordinator.stop(str(exc))
            raise

    @property
    def state(self):
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"schema": "nvidia-free-endpoint/v1", "provider_id": NVIDIA_PROVIDER_ID,
            "base_url": NVIDIA_BASE_URL, "model": NVIDIA_MODEL, "round_kind": self.round_kind,
            "request_limit": self.request_limit, "output_token_limit": 32768, "min_start_interval_s": 2,
            "requests": 0, "calls": 0, "last_start": None, "reservations": {}, "charges": [],
            "allow_low_space_this_round": self.allow_low_space_this_round,
            "skip_incomplete_stream_task": self.skip_incomplete_stream_task,
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
        if self.serial_coordinator is not None and not self.serial_coordinator.held:
            self.stop("NVIDIA actual request has no shared serial HTTP lease")
            raise BudgetStop(self.state["reason"])
        if self.serial_coordinator is not None and self.serial_coordinator.stopped:
            self.stop(self.serial_coordinator.state["reason"])
            raise BudgetStop(self.state["reason"])
        if not self.allow_low_space_this_round and shutil.disk_usage(self.path.parent).free < 5_000_000_000:
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
        request_sha256 = hashlib.sha256(body).hexdigest()
        if self.overload_recovery is not None:
            try:
                self.overload_recovery.before_send(request_sha256, self._retry_ticket)
                self._retry_ticket = None
            except BudgetStop as exc:
                self.stop(str(exc))
                raise
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
                if self.serial_coordinator is not None:
                    try:
                        self.serial_coordinator.record_start(reservation=key, round_ledger=self.path,
                            request_sha256=request_sha256)
                    except BudgetStop as exc:
                        state.update(stopped=True, reason=str(exc))
                        refused = True
                elif state["last_start"] is not None:
                    time.sleep(max(0, state["last_start"] + 2 - time.time()))
                if not refused:
                    state["last_start"] = time.time()
                    state["requests"] += 1
                    state["reservations"][key] = {"started_at": state["last_start"], "output_bound": output,
                        "output_limit": "provider_default_unverified" if output is None else output,
                        "request_sha256": request_sha256}
        if refused:
            self.stop(self.state["reason"])
            raise BudgetStop(self.state["reason"])
        return key

    def recover_complete_http_error(self, status, raw, key):
        """Called only after recorder read the complete body, never on interruption."""
        if not self.recover_complete_http_500_errors or self.overload_recovery is None or status != 500:
            return
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return
        if payload != {"error": {"message": "Failed to generate completions",
                "type": "Internal Server Error", "code": 500}}:
            return
        # bool/float equality must not turn an unobserved envelope into the
        # approved integer-coded provider failure.
        if type(payload["error"]["code"]) is not int:
            return
        self._recover_unknown(raw, key,
            "user-authorized complete error-only HTTP 500 recovery; usage and billing remain unknown")

    def recover_overload(self, status, raw, key):
        if self.overload_recovery is None or status != 200:
            return
        # Only the complete, actually observed error-only SSE shape is eligible.
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) != 2 or not lines[0].startswith(b"data:") or lines[1] != b"data: [DONE]":
            return
        try:
            payload = json.loads(lines[0][5:])
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict) or set(payload) != {"error"}:
            return
        error = payload["error"]
        if (not isinstance(error, dict) or type(error.get("code")) is not int
                or error != {"message": "Service temporarily overloaded", "type": "service_unavailable", "code": 503}):
            return
        self._recover_unknown(raw, key, "user-authorized complete error-only SSE 503 recovery; usage and billing remain unknown")

    def end_incomplete_stream_task(self, *, status, content_type, raw, key, task):
        if not self.skip_incomplete_stream_task or status != 200 or "text/event-stream" not in content_type:
            return
        public_output = False
        for line in raw.splitlines():
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                return
            try:
                payload = json.loads(data)
            except ValueError:
                return
            if not isinstance(payload, dict) or payload.get("usage") is not None or "error" in payload:
                return
            choices = payload.get("choices")
            if not isinstance(choices, list):
                return
            for choice in choices:
                if not isinstance(choice, dict) or choice.get("finish_reason") is not None:
                    return
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    return
                content = delta.get("content")
                public_output = public_output or isinstance(content, str) and bool(content.strip())
        if not public_output:
            return
        reason = "NVIDIA incomplete stream: task failed; unknown usage retained; no retry"
        with self._change() as state:
            reservation = state["reservations"].pop(key)
            state.setdefault("accepted_unknown_requests", []).append({"key": key, "reservation": reservation,
                "request_sha256": reservation["request_sha256"], "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "reason": reason, "task": task, "retry_ticket": None})
        self.close_request_slot()
        raise TaskStop(reason)

    def recover_unanswered_transport_error(self, *, response, raw, sent, error, key):
        from httpx import ReadError, RemoteProtocolError
        if (not self.recover_unanswered_read_errors or self.overload_recovery is None
                or response is not None or raw or not sent):
            return
        if not (isinstance(error, ReadError)
                or self.recover_unanswered_protocol_errors and isinstance(error, RemoteProtocolError)):
            return
        self._recover_unknown(raw, key, f"user-authorized unanswered {type(error).__name__} recovery; usage and billing remain unknown")

    def _recover_unknown(self, raw, key, reason):
        state = self.state
        reservation = state["reservations"].get(key)
        if state["stopped"] or reservation is None or not reservation.get("request_sha256"):
            self.stop("NVIDIA recovery has no active authorized request reservation")
            raise BudgetStop(self.state["reason"])
        try:
            retry = self.overload_recovery.claim(reservation["request_sha256"], round_ledger=self.path, reservation=key)
        except BudgetStop as exc:
            self.stop(str(exc))
            raise
        with self._change() as state:
            original = state["reservations"].pop(key)
            state.setdefault("accepted_unknown_requests", []).append({"key": key, "reservation": original,
                "request_sha256": original["request_sha256"], "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "reason": reason,
                "retry_ticket": retry.ticket})
        raise retry

    async def wait_for_retry(self, retry):
        try:
            await asyncio.sleep(retry.delay_s)
            self.overload_recovery.ready(retry.ticket)
            self._retry_ticket = retry.ticket
        except BaseException:
            reason = "NVIDIA overload recovery wait interrupted; no further request authorized"
            self.stop(reason)
            self.overload_recovery.stop(reason)
            raise

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
            self.stop(reason)
            raise BudgetStop(reason)
        self.close_request_slot()

    def unreachable(self, error):
        self.stop(f"NVIDIA endpoint connection failed ({error}); stop the round; billing remains unknown")
        raise BudgetStop(self.state["reason"])

    def resume_storage_stop(self):
        raise BudgetStop("NVIDIA storage floor cannot be bypassed for this round")
