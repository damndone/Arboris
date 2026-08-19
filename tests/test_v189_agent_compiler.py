from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import inspect
import json
import multiprocessing as mp
import os
import pickle
from pathlib import Path
import socket
from threading import Barrier, Lock
import threading
import tempfile
from uuid import uuid4

import pytest

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.agent.authority import (
    HostAuthorityChannelError,
    HostAuthorityServerV1,
    admit_host_authority_fd,
    admit_host_authority_endpoint,
    load_host_authority_config,
)
from workbench.agent.capability_manifest import build_capability_manifest
from workbench.agent.compilation_store import CompilationStore
from workbench.agent.context_compiler import compile_agent_compiler_context
from workbench.agent.failure_contract import CompilationFailure, failure
from workbench.agent.plan_compiler import (
    CompilationRequestV1,
    CompilationResultV1,
    PlanCompiler,
)
import workbench.agent.plan_compiler as plan_compiler_module
import workbench.agent.planning_contracts as planning_contracts_module
from workbench.agent.planning_contracts import (
    AnalysisIntentV1,
    DraftAgentPlanV1,
    HostCompilationRequestV1,
    HostCompilationResultV1,
    _SERVER_SCOPE_AUTHORITY_PROOF,
    ScopeAuthorityResolverV1,
    ServerScopeBindingV1,
)
from workbench.contracts.agent.planning import (
    CompiledWorkflowV1,
    CompilationRecordV1,
    FailureEnvelopeV1 as ContractFailureEnvelopeV1,
    PlanEffectV1,
    PlanRiskLevelV1,
    ServerCompilationRecordReferenceV1,
)
from workbench.contracts.common.contract_ref import ContractRefV1


_TEST_RESERVATION_ROOT: ContextVar[str | None] = ContextVar(
    "test_reservation_root",
    default=None,
)


@pytest.fixture(autouse=True)
def _per_test_reservation_root(tmp_path):
    token = _TEST_RESERVATION_ROOT.set(str(tmp_path))
    try:
        yield
    finally:
        _TEST_RESERVATION_ROOT.reset(token)


def _test_reservation_root() -> str:
    root = _TEST_RESERVATION_ROOT.get()
    if root is None:
        raise AssertionError("compiler test must run inside the reservation-root fixture")
    return root


def _new_test_reservation_root() -> str:
    root = Path(_test_reservation_root()) / f"compiler-{uuid4().hex}"
    root.mkdir()
    return str(root)


class _TestHostCompiler:
    """Non-authoritative test adapter; production code has no local issuer path."""

    def __init__(self, store: CompilationStore) -> None:
        self._store = store
        self._records: dict[tuple[str, str], CompilationRecordV1] = {}

        def resolve(reference: ServerCompilationRecordReferenceV1) -> CompilationRecordV1:
            try:
                return self._records[(reference.record_id, reference.record_digest)]
            except KeyError as exc:
                raise ValueError("test host record is unavailable") from exc

        self._store.record_store.resolve = resolve  # type: ignore[method-assign]

    def compile(self, request: HostCompilationRequestV1) -> HostCompilationResultV1:
        compiled = CompiledWorkflowV1.from_draft(
            request.draft,
            compiler_version="compiler:1.8.9",
            server_execution_identity=f"compile:test:{request.idempotency_key}",
            preview_fingerprint=sha256_canonical(
                {
                    "semantic_plan_hash": request.draft.semantic_plan_hash,
                    "compiler_version": "compiler:1.8.9",
                    "idempotency_key": request.idempotency_key,
                }
            ),
            plan_diff={
                "effect": request.draft.effect.value,
                "data_impact": "read_dataset" if "read_refs" in request.draft.data_impact else "none",
            },
            risk_level=request.draft.risk_level,
            effect=request.draft.effect,
            resource_budget=request.draft.resource_budget,
            contract_snapshot_refs=request.draft.contract_snapshot_refs,
            catalog_snapshot_ref=request.draft.catalog_snapshot_ref,
        )
        created = datetime.now(timezone.utc)
        record = CompilationRecordV1.from_compiled(
            compiled,
            record_id=f"compilation-record:{request.idempotency_key}",
            principal_ref=request.principal_ref,
            session_ref=request.session_ref,
            project_ref=request.project_ref,
            source_commitments=dict(request.source_commitments),
            created_at=created.isoformat(),
            expires_at=(created + timedelta(hours=1)).isoformat(),
        )
        self._records[(record.record_id, record.record_digest)] = record
        reference = ServerCompilationRecordReferenceV1(
            record_id=record.record_id,
            record_digest=record.record_digest,
            semantic_plan_hash=record.semantic_plan_hash,
        )
        return HostCompilationResultV1(
            compiled_plan=compiled,
            record=record,
            reference=reference,
        )


_HOST_PROTOCOL = "workbench-host-authority.v1"
_HOST_CONFIG_SCHEMA = "workbench-host-authority-config.v1"
_HOST_CONFIG_ENV = "WORKBENCH_AGENT_HOST_AUTHORITY_CONFIG"
_TEST_HOST: "_ExternalHostAuthority | None" = None
_HOST_OWNER_PID = os.getpid()


def _host_send(channel: socket.socket, value: dict[str, object]) -> None:
    channel.sendall(canonical_json_v1(value).encode("utf-8") + b"\n")


def _host_read(channel: socket.socket) -> dict[str, object] | None:
    raw = bytearray()
    while True:
        chunk = channel.recv(4096)
        if not chunk:
            return None
        raw.extend(chunk)
        if b"\n" in chunk:
            frame, _separator, _tail = bytes(raw).partition(b"\n")
            value = json.loads(frame.decode("utf-8"))
            if type(value) is not dict:
                raise ValueError("host request must be an object")
            return value


def _external_host_process(
    endpoint_path: str,
    ready_pipe,
    manifest_digest: str,
    natural_language_ids: tuple[str, ...],
    session_ref: str,
    shared_secret_hex: str,
) -> None:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(endpoint_path)
    listener.listen(16)
    endpoint_stat = os.lstat(endpoint_path)
    ready_pipe.send(
        {
            "endpoint_device": int(endpoint_stat.st_dev),
            "endpoint_inode": int(endpoint_stat.st_ino),
        }
    )
    ready_pipe.close()
    shared_secret = bytes.fromhex(shared_secret_hex)
    binding = {
        "scope_ref": "project:alpha",
        "principal_ref": "principal:unknown",
        "session_ref": "session:unknown",
        "project_ref": "project:alpha",
        "binding_id": "binding:test-alpha",
    }
    receipts: dict[str, dict[str, object]] = {}
    selections: dict[str, dict[str, object]] = {}

    def dispatch(operation: object, payload: object) -> dict[str, object]:
        if type(payload) is not dict:
            raise ValueError("host payload must be an object")
        if operation == "session":
            challenge = payload.get("challenge")
            endpoint = payload.get("endpoint")
            owner_pid = payload.get("owner_pid")
            if type(challenge) is not str or type(endpoint) is not dict or type(owner_pid) is not int:
                raise ValueError("host session request is malformed")
            attestation = hmac.new(
                shared_secret,
                canonical_json_v1(
                    {
                        "challenge": challenge,
                        "endpoint": endpoint,
                        "owner_pid": owner_pid,
                        "session_ref": session_ref,
                    }
                ).encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return {"session_ref": session_ref, "attestation": attestation}
        if operation == "bind_scope":
            if {
                payload.get("scope_ref"),
                payload.get("principal_ref"),
                payload.get("session_ref"),
                payload.get("project_ref"),
            } != {
                "project:alpha",
                "principal:unknown",
                "session:unknown",
            }:
                raise ValueError("host scope binding is invalid")
            if payload.get("scope_ref") != "project:alpha" or payload.get("project_ref") != "project:alpha":
                raise ValueError("host scope binding is invalid")
            return dict(binding)
        if operation == "validate_binding":
            if payload.get("binding_id") != binding["binding_id"]:
                raise ValueError("host binding is unknown")
            return dict(binding)
        if operation == "issue_discovery_receipt":
            capability_ids = payload.get("capability_ids")
            if (
                payload.get("binding_id") != binding["binding_id"]
                or payload.get("manifest_digest") != manifest_digest
                or type(capability_ids) is not list
                or any(item not in natural_language_ids for item in capability_ids)
            ):
                raise ValueError("host discovery request is invalid")
            receipt_id = "receipt:test:" + uuid4().hex
            receipts[receipt_id] = {
                "receipt_id": receipt_id,
                "binding_id": binding["binding_id"],
                "scope_ref": binding["scope_ref"],
                "query": payload.get("query"),
                "manifest_digest": manifest_digest,
                "capability_ids": tuple(capability_ids),
                "receipt_digest": payload.get("receipt_digest"),
            }
            return {"receipt_id": receipt_id}
        if operation == "validate_discovery_receipt":
            receipt_id = payload.get("receipt_id")
            if type(receipt_id) is not str or receipt_id not in receipts:
                raise ValueError("host receipt is unknown")
            return dict(receipts[receipt_id])
        if operation == "issue_selection":
            receipt_id = payload.get("receipt_id")
            capability_id = payload.get("capability_id")
            if type(receipt_id) is not str or receipt_id not in receipts:
                raise ValueError("host receipt is unknown")
            receipt = receipts[receipt_id]
            if (
                payload.get("binding_id") != binding["binding_id"]
                or payload.get("manifest_digest") != manifest_digest
                or capability_id not in receipt["capability_ids"]
            ):
                raise ValueError("host selection request is invalid")
            selection_id = "selection:test:" + uuid4().hex
            selections[selection_id] = {
                "selection_id": selection_id,
                "capability_id": capability_id,
                "binding_id": binding["binding_id"],
                "scope_ref": binding["scope_ref"],
                "manifest_digest": manifest_digest,
                "receipt_digest": receipt["receipt_digest"],
            }
            return {"selection_id": selection_id}
        if operation == "validate_selection":
            selection_id = payload.get("selection_id")
            if type(selection_id) is not str or selection_id not in selections:
                raise ValueError("host selection is unknown")
            return dict(selections[selection_id])
        raise ValueError("host operation is unknown")

    def serve_client(channel: socket.socket) -> None:
        try:
            while True:
                request = _host_read(channel)
                if request is None:
                    break
                try:
                    if (
                        request.get("schema_version") != _HOST_PROTOCOL
                        or type(request.get("operation")) is not str
                    ):
                        raise ValueError("host request envelope is invalid")
                    payload = dispatch(request["operation"], request.get("payload"))
                    response = {
                        "schema_version": _HOST_PROTOCOL,
                        "ok": True,
                        "payload": payload,
                    }
                except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                    response = {
                        "schema_version": _HOST_PROTOCOL,
                        "ok": False,
                        "code": "FORGED_AUTHORITY",
                    }
                _host_send(channel, response)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        finally:
            channel.close()

    try:
        while True:
            channel, _address = listener.accept()
            threading.Thread(target=serve_client, args=(channel,), daemon=True).start()
    except OSError:
        return
    finally:
        listener.close()


class _ExternalHostAuthority:
    def __init__(self, manifest) -> None:
        self.directory = tempfile.mkdtemp(prefix="workbench-agent-authority-", dir="/private/tmp")
        self.path = str(Path(self.directory) / "authority.sock")
        self.shared_secret = bytes.fromhex("44" * 32)
        self.session_ref = "session:test-agent-host"
        context = mp.get_context("fork")
        ready_pipe, child_ready_pipe = context.Pipe(False)
        self.process = context.Process(
            target=_external_host_process,
            args=(
                self.path,
                child_ready_pipe,
                manifest.manifest_digest,
                tuple(entry.capability_id for entry in manifest.entries if entry.natural_language_enabled),
                self.session_ref,
                self.shared_secret.hex(),
            ),
            daemon=True,
        )
        self.process.start()
        child_ready_pipe.close()
        if not ready_pipe.poll(5):
            self.process.terminate()
            self.process.join(timeout=5)
            raise RuntimeError("external test host did not publish endpoint identity")
        endpoint_identity = ready_pipe.recv()
        ready_pipe.close()
        self.endpoint_device = int(endpoint_identity["endpoint_device"])
        self.endpoint_inode = int(endpoint_identity["endpoint_inode"])
        self.config_path = str(Path(self.directory) / "authority-config.json")
        Path(self.config_path).write_text(
            json.dumps(
                {
                    "schema_version": _HOST_CONFIG_SCHEMA,
                    "endpoint_path": self.path,
                    "endpoint_device": self.endpoint_device,
                    "endpoint_inode": self.endpoint_inode,
                    "peer_uid": os.getuid(),
                    "peer_pid": self.process.pid,
                    "scope_ref": "project:alpha",
                    "session_ref": self.session_ref,
                    "shared_secret": self.shared_secret.hex(),
                    "purpose_prefix": "agent.",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.chmod(self.config_path, 0o600)
        self._previous_config = os.environ.get(_HOST_CONFIG_ENV)
        os.environ[_HOST_CONFIG_ENV] = self.config_path

    def open_handle(self):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(self.path)
        config = load_host_authority_config()
        return admit_host_authority_endpoint(client, deployment_config=config)

    def config_payload(self, **overrides: object) -> dict[str, object]:
        payload = {
            "schema_version": _HOST_CONFIG_SCHEMA,
            "endpoint_path": self.path,
            "endpoint_device": self.endpoint_device,
            "endpoint_inode": self.endpoint_inode,
            "peer_uid": os.getuid(),
            "peer_pid": self.process.pid,
            "scope_ref": "project:alpha",
            "session_ref": self.session_ref,
            "shared_secret": self.shared_secret.hex(),
            "purpose_prefix": "agent.",
        }
        payload.update(overrides)
        return payload

    def loaded_config(self, **overrides: object):
        path = str(Path(self.directory) / f"authority-config-{uuid4().hex}.json")
        Path(path).write_text(json.dumps(self.config_payload(**overrides), sort_keys=True), encoding="utf-8")
        os.chmod(path, 0o600)
        previous = os.environ.get(_HOST_CONFIG_ENV)
        os.environ[_HOST_CONFIG_ENV] = path
        try:
            return load_host_authority_config(), path, previous
        except BaseException:
            os.unlink(path)
            if previous is None:
                os.environ.pop(_HOST_CONFIG_ENV, None)
            else:
                os.environ[_HOST_CONFIG_ENV] = previous
            raise

    def close(self) -> None:
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        try:
            os.unlink(self.config_path)
        except FileNotFoundError:
            pass
        try:
            os.rmdir(self.directory)
        except OSError:
            pass
        if self._previous_config is None:
            os.environ.pop(_HOST_CONFIG_ENV, None)
        else:
            os.environ[_HOST_CONFIG_ENV] = self._previous_config


def _restore_loaded_config(path: str, previous: str | None) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    if previous is None:
        os.environ.pop(_HOST_CONFIG_ENV, None)
    else:
        os.environ[_HOST_CONFIG_ENV] = previous


def _close_test_host() -> None:
    global _TEST_HOST
    if os.getpid() != _HOST_OWNER_PID:
        return
    if _TEST_HOST is not None:
        _TEST_HOST.close()
        _TEST_HOST = None


atexit.register(_close_test_host)


def _forked_handle_probe(handle, result_queue) -> None:
    try:
        handle.channel_id
    except HostAuthorityChannelError as exc:
        result_queue.put(exc.code)
    except BaseException as exc:  # pragma: no cover - surfaced by assertion
        result_queue.put(f"{type(exc).__name__}:{exc}")
    else:
        result_queue.put("accepted")


def _host_authority(manifest):
    global _TEST_HOST
    if _TEST_HOST is None or not _TEST_HOST.process.is_alive():
        if _TEST_HOST is not None:
            _TEST_HOST.close()
        _TEST_HOST = _ExternalHostAuthority(manifest)
    server = _TEST_HOST
    handle = server.open_handle()
    resolver = ScopeAuthorityResolverV1.from_host_handle(handle)
    return server, handle, resolver


def _ref(kind: str, logical_id: str, digest: str | None = None) -> ContractRefV1:
    return ContractRefV1(
        kind=kind,
        logical_id=logical_id,
        semantic_version="1.0",
        contract_digest=digest or ("a" * 64),
    )


def _draft_and_intent():
    manifest = build_capability_manifest()
    entry = manifest.require("model.rerun")
    plan = DraftAgentPlanV1(
        schema_version="draft-agent-plan.v1",
        intent_ref="intent:model-rerun:1",
        capability_refs=(entry.capability_ref,),
        method_ref="method:model.rerun",
        effect=PlanEffectV1.MODEL_FIT,
        risk_level=PlanRiskLevelV1.MEDIUM,
        resource_budget={"cpu_ms": 1000, "memory_mb": 128},
        data_impact={"read_refs": ["dataset:source"], "write_mode": "none"},
        output_contract_refs=(_ref("output-contract", "model.rerun.output"),),
        evidence_contract_refs=(_ref("evidence-contract", "model.rerun.evidence"),),
        contract_snapshot_refs=(entry.contract_ref,),
        catalog_snapshot_ref=f"catalog:{manifest.manifest_digest}",
        nodes=(
            {
                "node_id": "fit",
                "capability_ref": f"capability:{entry.capability_id}",
                "read_refs": ["dataset:source"],
                "write_mode": "none",
                "options": {"analysis_mode": "predictive"},
            },
        ),
        connections=(),
        config={"analysis_mode": "predictive", "seed": 7},
        policy_snapshot_ref=entry.policy_snapshot_ref,
        rationale=("rationale:server-compiled-model-plan",),
    )
    intent = AnalysisIntentV1(
        intent_ref=plan.intent_ref,
        scope_ref="project:alpha",
        capability_ids=(entry.capability_id,),
        source_digest="b" * 64,
        contract_digest=manifest.manifest_digest,
    )
    return manifest, plan, intent


def _compiler() -> tuple[PlanCompiler, DraftAgentPlanV1, AnalysisIntentV1]:
    manifest, plan, intent = _draft_and_intent()
    _server, _handle, resolver = _host_authority(manifest)
    store = CompilationStore(reservation_root=_new_test_reservation_root())
    compiler = PlanCompiler(
        manifest=manifest,
        store=store,
        authority_resolver=resolver,
        host_compiler=_TestHostCompiler(store),
    )
    return compiler, plan, intent


def _server_compiler(manifest):
    _server, _handle, resolver = _host_authority(manifest)
    store = CompilationStore(reservation_root=_new_test_reservation_root())
    return PlanCompiler(
        manifest=manifest,
        store=store,
        authority_resolver=resolver,
        host_compiler=_TestHostCompiler(store),
    )


def _data_cast_plan() -> tuple[PlanCompiler, DraftAgentPlanV1, AnalysisIntentV1]:
    compiler, plan, intent = _compiler()
    entry = compiler.manifest.require("data.columns.cast")
    return (
        compiler,
        replace(
            plan,
            capability_refs=(entry.capability_ref,),
            method_ref="method:data.columns.cast",
            effect=PlanEffectV1.WRITE,
            contract_snapshot_refs=(entry.contract_ref,),
            policy_snapshot_ref=entry.policy_snapshot_ref,
        ),
        replace(intent, capability_ids=(entry.capability_id,)),
    )


def _selection(compiler: PlanCompiler, intent: AnalysisIntentV1, *, scope_ref: str = "project:alpha"):
    return compiler.server_selection(
        intent.capability_ids[0],
        scope_ref=scope_ref,
        project_ref=scope_ref,
    )


def _compile(
    compiler: PlanCompiler,
    draft: object,
    intent: AnalysisIntentV1,
    *,
    scope_ref: str = "project:alpha",
    **kwargs: object,
) -> CompilationResultV1:
    return compiler.compile(
        draft,
        intent=intent,
        scope_ref=scope_ref,
        selection=_selection(compiler, intent, scope_ref=scope_ref),
        **kwargs,
    )


def _reserve_in_process(
    root: str,
    idempotency_key: str,
    ready,
    release,
    result_queue,
    hold: bool,
) -> None:
    store = CompilationStore(reservation_root=root)
    try:
        with store.reservation(idempotency_key) as replay:
            result_queue.put("replay" if replay is not None else "owner")
            ready.set()
            if hold:
                release.wait(5)
    except CompilationFailure as exc:
        result_queue.put(exc.code)
        ready.set()
    finally:
        store.close()


def test_plan_compiler_is_server_owned_idempotent_and_replayable() -> None:
    compiler, plan, intent = _compiler()
    request = CompilationRequestV1(
        draft=plan,
        intent=intent,
        scope_ref="project:alpha",
        principal_ref="principal:unknown",
        session_ref="session:unknown",
        project_ref="project:alpha",
        source_commitments={"dataset": "b" * 64},
        selection=_selection(compiler, intent),
    )

    first = compiler.compile(request)
    second = compiler.compile(request)

    assert isinstance(first, CompilationResultV1)
    assert first.record.to_dict() == second.record.to_dict()
    assert first.reference.to_dict() == second.reference.to_dict()
    assert compiler.store.replay(first.idempotency_key) == first
    # The execution identity is host-owned; the local test adapter deliberately
    # uses its own non-production prefix instead of pretending to be the server.
    assert first.record.compiled_workflow.server_execution_identity.startswith("compile:")
    with pytest.raises(TypeError):
        first.record.source_commitments["dataset"] = "c" * 64  # type: ignore[index]


def test_plan_compiler_rejects_unknown_capability_and_operation() -> None:
    compiler, plan, intent = _compiler()

    unknown_capability = replace(
        plan,
        capability_refs=(_ref("capability", "unknown.capability"),),
    )
    with pytest.raises(CompilationFailure) as capability_error:
        _compile(compiler, unknown_capability, intent)
    assert capability_error.value.code == "UNKNOWN_CAPABILITY"

    unknown_operation = replace(plan, method_ref="method:unknown.operation")
    with pytest.raises(CompilationFailure) as operation_error:
        _compile(compiler, unknown_operation, intent)
    assert operation_error.value.code == "UNKNOWN_OPERATION"


def test_plan_compiler_rejects_path_like_cross_scope_and_forged_authority() -> None:
    compiler, plan, intent = _compiler()

    with pytest.raises(CompilationFailure) as path_error:
        compiler.compile(replace(plan, method_ref="method:../escape"), intent=intent, scope_ref="project:alpha")
    assert path_error.value.code == "PATH_LIKE_INPUT"

    with pytest.raises(CompilationFailure) as scope_error:
        _compile(compiler, plan, replace(intent, scope_ref="project:other"))
    assert scope_error.value.code == "CROSS_SCOPE"

    forged = CompiledWorkflowV1.from_draft(
        plan,
        compiler_version="compiler:forged",
        server_execution_identity="compile:forged",
        preview_fingerprint="c" * 64,
        plan_diff={"effect": "model_fit"},
        risk_level=plan.risk_level,
        effect=plan.effect,
        resource_budget=plan.resource_budget,
        contract_snapshot_refs=plan.contract_snapshot_refs,
        catalog_snapshot_ref=plan.catalog_snapshot_ref,
    )
    with pytest.raises(CompilationFailure) as authority_error:
        _compile(compiler, forged, intent)
    assert authority_error.value.code == "FORGED_AUTHORITY"


def test_plan_compiler_rejects_oversized_recursive_and_model_provider_injection() -> None:
    compiler, plan, intent = _compiler()

    oversized = replace(plan, rationale=("rationale:" + "x" * 9000,))
    with pytest.raises(CompilationFailure) as size_error:
        _compile(compiler, oversized, intent)
    assert size_error.value.code == "INPUT_LIMIT"

    raw = plan.to_dict()
    raw["config"] = {"model": "attacker-model", "provider": "attacker-provider"}
    with pytest.raises(CompilationFailure) as injection_error:
        _compile(compiler, raw, intent)
    assert injection_error.value.code in {"MODEL_PROVIDER_INJECTION", "DRAFT_INVALID"}

    recursive: dict[str, object] = {}
    recursive["cycle"] = recursive
    with pytest.raises(CompilationFailure) as recursive_error:
        _compile(compiler, recursive, intent)
    assert recursive_error.value.code in {"RECURSIVE_INPUT", "DRAFT_TYPE_REQUIRED"}


def test_plan_compiler_rejects_duplicate_identity_and_port_mismatch() -> None:
    compiler, plan, intent = _compiler()

    duplicate = plan.to_dict()
    duplicate["capability_refs"].append(dict(duplicate["capability_refs"][0]))  # type: ignore[index]
    with pytest.raises(CompilationFailure) as duplicate_error:
        _compile(compiler, duplicate, intent)
    assert duplicate_error.value.code == "DUPLICATE_IDENTITY"

    mismatch = replace(
        plan,
        connections=(
            {
                "source_port": "port:source",
                "target_port": "port:target",
            },
        ),
    )
    with pytest.raises(CompilationFailure) as port_error:
        _compile(compiler, mismatch, intent)
    assert port_error.value.code == "PORT_TYPE_INVALID"


def test_failure_envelope_is_stable_redacted_and_context_shadow_is_bounded() -> None:
    compiler, plan, intent = _compiler()
    bad = replace(plan, method_ref="method:unknown.operation")
    with pytest.raises(CompilationFailure) as first_error:
        _compile(compiler, bad, intent)
    with pytest.raises(CompilationFailure) as second_error:
        _compile(compiler, bad, intent)

    assert first_error.value.envelope.to_dict() == second_error.value.envelope.to_dict()
    assert "attacker" not in str(first_error.value.envelope.to_dict())

    context = compile_agent_compiler_context(
        build_capability_manifest(),
        scope_ref="project:alpha",
        intent_ref=intent.intent_ref,
        selected_capability_ids=(plan.capability_refs[0].logical_id,),
    )
    assert context.bounded is True
    assert context.shadow_equivalent is True
    assert context.capability_ids == (plan.capability_refs[0].logical_id,)


def test_compiler_rejects_registry_policy_downgrade_and_oversized_budget() -> None:
    compiler, plan, intent = _compiler()

    downgrade_cases = (
        replace(plan, effect=PlanEffectV1.NONE),
        replace(plan, risk_level=PlanRiskLevelV1.LOW),
        replace(plan, policy_snapshot_ref="policy:none"),
        replace(plan, resource_budget={"cpu_ms": 100_000, "memory_mb": 100_000}),
    )
    for candidate in downgrade_cases:
        with pytest.raises(CompilationFailure) as exc_info:
            _compile(compiler, candidate, intent)
        assert exc_info.value.code == "SAFETY_POLICY"


def test_compiler_rejects_semantic_effect_downgrade_for_model_genesis() -> None:
    compiler, plan, intent = _compiler()

    downgraded = replace(plan, effect=PlanEffectV1.MODEL_EVALUATE)

    with pytest.raises(CompilationFailure) as exc_info:
        _compile(compiler, downgraded, intent)

    assert exc_info.value.code == "SAFETY_POLICY"


def test_compiler_rejects_disabled_read_only_none_risk_capability() -> None:
    compiler, base_plan, base_intent = _compiler()
    entry = compiler.manifest.require("model.auto")
    plan = replace(
        base_plan,
        intent_ref="intent:model-auto:1",
        capability_refs=(entry.capability_ref,),
        method_ref="method:model.auto",
        effect=PlanEffectV1.READ,
        risk_level=PlanRiskLevelV1.LOW,
        contract_snapshot_refs=(entry.contract_ref,),
        policy_snapshot_ref=entry.policy_snapshot_ref,
        nodes=(
            {
                "node_id": "auto",
                "capability_ref": "capability:model.auto",
                "read_refs": ["dataset:source"],
                "write_mode": "none",
                "options": {"analysis_mode": "predictive"},
            },
        ),
    )
    intent = replace(
        base_intent,
        intent_ref=plan.intent_ref,
        capability_ids=(entry.capability_id,),
    )

    with pytest.raises(CompilationFailure) as exc_info:
        compiler._compile_for_registry(plan, intent=intent, scope_ref="project:alpha")

    assert exc_info.value.code == "NATURAL_LANGUAGE_DISABLED"


def test_compiler_rejects_every_disabled_read_only_none_risk_capability() -> None:
    compiler, base_plan, base_intent = _compiler()
    entries = tuple(
        entry
        for entry in compiler.manifest.entries
        if entry.effect_level == "read_only" and entry.risk_level == "none"
    )

    assert entries
    for entry in entries:
        intent_ref = "intent:readonly-" + entry.capability_id.replace(".", "-") + ":1"
        plan = replace(
            base_plan,
            intent_ref=intent_ref,
            capability_refs=(entry.capability_ref,),
            method_ref=f"method:{entry.operation_id}",
            effect=PlanEffectV1.READ,
            risk_level=PlanRiskLevelV1.LOW,
            contract_snapshot_refs=(entry.contract_ref,),
            policy_snapshot_ref=entry.policy_snapshot_ref,
            nodes=(
                {
                    "node_id": "read-only",
                    "capability_ref": f"capability:{entry.capability_id}",
                    "read_refs": ["dataset:source"],
                    "write_mode": "none",
                    "options": {"analysis_mode": "descriptive"},
                },
            ),
        )
        intent = replace(
            base_intent,
            intent_ref=intent_ref,
            capability_ids=(entry.capability_id,),
        )

        with pytest.raises(CompilationFailure) as exc_info:
            compiler._compile_for_registry(plan, intent=intent, scope_ref="project:alpha")

        assert exc_info.value.code == "NATURAL_LANGUAGE_DISABLED"


def test_disabled_natural_language_capability_is_not_queryable_or_resolvable() -> None:
    from workbench.agent.capability_discovery import CapabilityDiscovery

    manifest = build_capability_manifest()
    _server, _handle, resolver = _host_authority(manifest)
    discovery = CapabilityDiscovery(
        manifest,
        authority_resolver=resolver,
    )
    result = discovery.query("code.execute", scope_ref="project:alpha")

    assert result.items == ()
    with pytest.raises(CompilationFailure) as exc_info:
        discovery.resolve("code.execute", scope_ref="project:alpha", receipt=result)
    assert exc_info.value.code == "NATURAL_LANGUAGE_DISABLED"


def test_compiler_fails_closed_without_server_scope_authority() -> None:
    manifest, plan, intent = _draft_and_intent()
    compiler = PlanCompiler(
        manifest=manifest,
        store=CompilationStore(reservation_root=_test_reservation_root()),
    )

    with pytest.raises(CompilationFailure) as exc_info:
        compiler.compile(plan, intent=intent, scope_ref="project:alpha")

    assert exc_info.value.code == "FORGED_AUTHORITY"


def test_manifest_exposes_runtime_identity_for_shadow_comparison() -> None:
    entry = build_capability_manifest().require("model.genesis")

    payload = entry.to_dict()

    assert payload["executor_identity"] == "model.genesis"
    assert payload["reconciler_identity"] == "model.genesis"
    assert payload["runtime_identity"]


def test_compiler_rejects_forged_connection_fields() -> None:
    compiler, plan, intent = _data_cast_plan()
    entry = compiler.manifest.require("data.columns.cast")
    connection = {
        "source_port": entry.output_port_refs[0],
        "target_port": entry.input_port_refs[0],
        "from_port": "port:forged",
        "to_port": "port:forged",
    }

    with pytest.raises(CompilationFailure) as exc_info:
        _compile(
            compiler,
            replace(plan, effect=PlanEffectV1.WRITE, connections=(connection,)),
            intent=intent,
        )

    assert exc_info.value.code == "PORT_TYPE_INVALID"


def test_compiler_concurrent_identical_requests_have_one_compilation_reservation() -> None:
    compiler, plan, intent = _compiler()
    replay_barrier = Barrier(8)
    host_compile_lock = Lock()
    host_compile_calls = 0
    original_replay = compiler.store.replay
    host_compiler = compiler.host_compiler
    assert host_compiler is not None
    original_host_compile = host_compiler.compile

    def synchronized_replay(idempotency_key: str):
        try:
            return original_replay(idempotency_key)
        except CompilationFailure as exc:
            if exc.code != "REPLAY_NOT_FOUND":
                raise
            replay_barrier.wait(timeout=5)
            raise

    def counted_host_compile(request):
        nonlocal host_compile_calls
        with host_compile_lock:
            host_compile_calls += 1
        return original_host_compile(request)

    compiler.store.replay = synchronized_replay
    host_compiler.compile = counted_host_compile

    def compile_once(_index: int) -> CompilationResultV1:
        return _compile(compiler, plan, intent)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(compile_once, range(8)))

    assert host_compile_calls == 1
    assert len({result.idempotency_key for result in results}) == 1
    assert all(result.to_dict() == results[0].to_dict() for result in results)


def test_compiler_rejects_forged_registry_manifest_even_with_recomputed_digest() -> None:
    manifest, plan, intent = _draft_and_intent()
    entry = manifest.require("model.rerun")
    tampered_entry = replace(entry, risk_level="low")
    entries = tuple(
        tampered_entry if item.capability_id == entry.capability_id else item
        for item in manifest.entries
    )
    tampered_manifest = type(manifest)(
        entries=entries,
        manifest_digest=sha256_canonical(
            {
                "schema_version": "capability-manifest.v1",
                "entries": [item.to_dict() for item in entries],
            }
        ),
    )
    tampered_plan = replace(
        plan,
        catalog_snapshot_ref=f"catalog:{tampered_manifest.manifest_digest}",
    )
    tampered_intent = replace(
        intent,
        contract_digest=tampered_manifest.manifest_digest,
    )

    compiler = _server_compiler(tampered_manifest)
    with pytest.raises(CompilationFailure) as exc_info:
        _compile(
            compiler,
            tampered_plan,
            intent=tampered_intent,
        )
    assert exc_info.value.code == "FORGED_AUTHORITY"


def test_compiler_keeps_code_execute_off_the_natural_language_path() -> None:
    manifest, plan, intent = _draft_and_intent()
    entry = manifest.require("code.execute")
    code_plan = replace(
        plan,
        capability_refs=(entry.capability_ref,),
        method_ref="method:code.execute",
        effect=PlanEffectV1.WRITE,
        risk_level=PlanRiskLevelV1.HIGH,
        resource_budget=dict(entry.resource_budget),
        contract_snapshot_refs=(entry.contract_ref,),
        policy_snapshot_ref=entry.policy_snapshot_ref,
        nodes=(
            {
                "node_id": "execute",
                "capability_ref": "capability:code.execute",
                "read_refs": ["dataset:source"],
                "write_mode": "none",
                "options": {"analysis_mode": "predictive"},
            },
        ),
    )
    code_intent = replace(intent, capability_ids=(entry.capability_id,))
    compiler = _server_compiler(manifest)

    with pytest.raises(CompilationFailure) as discovery_error:
        compiler.server_selection("code.execute", scope_ref="project:alpha")
    assert discovery_error.value.code in {"NATURAL_LANGUAGE_DISABLED", "FORGED_AUTHORITY"}

    with pytest.raises(CompilationFailure) as compile_error:
        compiler.compile(code_plan, intent=code_intent, scope_ref="project:alpha")
    assert compile_error.value.code == "NATURAL_LANGUAGE_DISABLED"


@pytest.mark.parametrize(
    "connection",
    [
        {},
        {"source_port": "port:forged:output:0", "target_port": "port:forged:input:0"},
        {
            "source_port": "port:data.columns.cast:v1:input:0",
            "target_port": "port:data.columns.cast:v1:output:0",
        },
    ],
)
def test_compiler_requires_real_directional_port_identity(connection: dict[str, object]) -> None:
    compiler, plan, intent = _data_cast_plan()
    candidate = replace(plan, connections=(connection,))

    with pytest.raises(CompilationFailure) as exc_info:
        _compile(compiler, candidate, intent)

    assert exc_info.value.code in {
        "PORT_DIRECTION_MISMATCH",
        "PORT_TYPE_INVALID",
        "PORT_KIND_MISMATCH",
        "PORT_SCHEMA_MISMATCH",
    }


def test_failure_contract_exposes_only_locked_c0_envelope_and_rejects_paths() -> None:
    error = failure("UNKNOWN_CAPABILITY", stage="compile")

    assert type(error.envelope) is ContractFailureEnvelopeV1
    assert set(error.envelope.to_dict()) == {
        "schema_version",
        "failure_class",
        "reason_code",
        "capability_ref",
        "step_ref",
        "evidence_refs",
        "retryable",
        "remediation_codes",
        "confirmation_required",
        "partial_output_refs",
        "partial_output_trust",
    }
    assert not hasattr(error.envelope, "code")
    with pytest.raises(ValueError):
        failure("UNKNOWN_CAPABILITY", stage="compile", path="../secret")


def test_compilation_store_rejects_forged_cross_object_and_reference_bindings() -> None:
    compiler, plan, intent = _compiler()
    first = _compile(compiler, plan, intent)
    forged_compiled = CompiledWorkflowV1.from_draft(
        plan,
        compiler_version="compiler:forged",
        server_execution_identity="compile:forged",
        preview_fingerprint="d" * 64,
        plan_diff={"effect": "model_fit"},
        risk_level=plan.risk_level,
        effect=plan.effect,
        resource_budget=plan.resource_budget,
        contract_snapshot_refs=plan.contract_snapshot_refs,
        catalog_snapshot_ref=plan.catalog_snapshot_ref,
    )
    forged_result = replace(first, compiled_plan=forged_compiled)

    with pytest.raises(CompilationFailure) as object_error:
        compiler.store.save_result(first.idempotency_key, forged_result)
    assert object_error.value.code == "FORGED_AUTHORITY"
    compiler.store._results[first.idempotency_key] = forged_result
    with pytest.raises(CompilationFailure) as replay_error:
        compiler.store.replay(first.idempotency_key)
    assert replay_error.value.code == "FORGED_AUTHORITY"

    foreign_compiler, foreign_plan, foreign_intent = _compiler()
    foreign = _compile(foreign_compiler, foreign_plan, foreign_intent)
    with pytest.raises(CompilationFailure) as reference_error:
        compiler.store.save_result(foreign.idempotency_key, foreign)
    assert reference_error.value.code == "FORGED_AUTHORITY"


def test_compilation_store_concurrent_same_result_is_immutable_replay() -> None:
    compiler, plan, intent = _compiler()
    first = _compile(compiler, plan, intent)

    def replay() -> CompilationResultV1:
        return compiler.store.save_result(first.idempotency_key, first)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _index: replay(), range(8)))

    assert all(result is first for result in results)
    assert compiler.store.replay(first.idempotency_key) is first


def test_discovery_scope_and_shortlist_receipt_are_authoritative() -> None:
    from workbench.agent.capability_discovery import (
        CapabilityDiscovery,
        CapabilityDiscoveryResultV1,
        DiscoveryLimitsV1,
    )

    manifest = build_capability_manifest()
    _server, _handle, resolver = _host_authority(manifest)
    discovery = CapabilityDiscovery(
        manifest,
        limits=DiscoveryLimitsV1(max_query_results=1),
        authority_resolver=resolver,
    )
    with pytest.raises(CompilationFailure) as scope_error:
        discovery.query("model", scope_ref="tenant:other")
    assert scope_error.value.code == "CROSS_SCOPE"

    result = discovery.query("data.columns.cast", scope_ref="project:alpha")
    with pytest.raises(CompilationFailure) as receipt_error:
        discovery.resolve("data.columns.cast", scope_ref="project:alpha")
    assert receipt_error.value.code == "FORGED_AUTHORITY"

    selected = discovery.resolve(
        "data.columns.cast",
        scope_ref="project:alpha",
        receipt=result,
    )
    assert selected.capability_id == "data.columns.cast"

    forged_receipt = CapabilityDiscoveryResultV1(
        query="data.columns.cast",
        scope_ref="project:alpha",
        items=(discovery.manifest.require("data.columns.cast"),),
        manifest_digest=discovery.manifest.manifest_digest,
    )
    with pytest.raises(CompilationFailure) as forged_receipt_error:
        discovery.resolve(
            "data.columns.cast",
            scope_ref="project:alpha",
            receipt=forged_receipt,
        )
    assert forged_receipt_error.value.code == "FORGED_AUTHORITY"

    with pytest.raises(CompilationFailure) as budget_error:
        discovery.query("", scope_ref="project:alpha")
    assert budget_error.value.code == "DISCOVERY_QUERY_LIMIT"


def test_shadow_equivalence_compares_full_manifest_metadata_and_ports() -> None:
    from workbench.agent.capability_manifest import CapabilityManifestV1

    manifest = build_capability_manifest()
    entry = manifest.require("model.genesis")
    tampered_entry = replace(entry, scope_requirements=("unauthorized",))
    entries = tuple(
        tampered_entry if item.capability_id == entry.capability_id else item
        for item in manifest.entries
    )
    tampered_manifest = CapabilityManifestV1(
        entries=entries,
        manifest_digest=sha256_canonical(
            {
                "schema_version": "capability-manifest.v1",
                "entries": [item.to_dict() for item in entries],
            }
        ),
    )

    context = compile_agent_compiler_context(
        tampered_manifest,
        scope_ref="project:alpha",
        intent_ref="intent:model-genesis:1",
        selected_capability_ids=("model.genesis",),
    )

    assert context.shadow_equivalent is False


def test_shadow_equivalence_rejects_runtime_identity_tampering() -> None:
    from workbench.agent.capability_manifest import CapabilityManifestV1

    manifest = build_capability_manifest()
    entry = manifest.require("model.genesis")
    tampered_entry = replace(entry, executor_identity="executor:forged")
    entries = tuple(
        tampered_entry if item.capability_id == entry.capability_id else item
        for item in manifest.entries
    )
    tampered_manifest = CapabilityManifestV1(
        entries=entries,
        manifest_digest=sha256_canonical(
            {
                "schema_version": "capability-manifest.v1",
                "entries": [item.to_dict() for item in entries],
            }
        ),
    )

    context = compile_agent_compiler_context(
        tampered_manifest,
        scope_ref="project:alpha",
        intent_ref="intent:model-genesis:1",
        selected_capability_ids=("model.genesis",),
    )

    assert context.shadow_equivalent is False


def test_scope_authority_resolver_is_not_caller_constructible_or_reissuable() -> None:
    binding = ServerScopeBindingV1(
        scope_ref="project:attacker",
        principal_ref="principal:attacker",
        session_ref="session:attacker",
        project_ref="project:attacker",
    )

    with pytest.raises(ValueError, match="host authority"):
        ScopeAuthorityResolverV1(bindings=(binding,))

    payload = binding.to_dict()
    reconstructed = ServerScopeBindingV1(
        scope_ref=payload["scope_ref"],
        principal_ref=payload["principal_ref"],
        session_ref=payload["session_ref"],
        project_ref=payload["project_ref"],
    )
    with pytest.raises(ValueError, match="host authority"):
        ScopeAuthorityResolverV1(bindings=(reconstructed,))

    with pytest.raises(ValueError, match="host authority handle"):
        ScopeAuthorityResolverV1._from_server_snapshots(
            (
                {
                    "scope_ref": "project:attacker",
                    "principal_ref": "principal:attacker",
                    "session_ref": "session:attacker",
                    "project_ref": "project:attacker",
                },
            )
        )

    with pytest.raises(ValueError, match="cannot be reconstructed"):
        ServerScopeBindingV1.from_dict(payload)


def test_direct_typed_or_json_draft_requires_server_discovery_selection() -> None:
    compiler, plan, intent = _compiler()

    for candidate in (plan, plan.to_dict()):
        with pytest.raises(CompilationFailure) as exc_info:
            compiler.compile(candidate, intent=intent, scope_ref="project:alpha")
        assert exc_info.value.code == "FORGED_AUTHORITY"


def test_discovery_scope_cannot_be_selected_by_caller_string() -> None:
    from workbench.agent.capability_discovery import CapabilityDiscovery

    discovery = CapabilityDiscovery(build_capability_manifest())

    with pytest.raises(CompilationFailure) as exc_info:
        discovery.query("model", scope_ref="project:attacker")

    assert exc_info.value.code == "FORGED_AUTHORITY"


def test_public_compiler_requires_durable_reservation_store() -> None:
    manifest, plan, intent = _draft_and_intent()
    _server, _handle, resolver = _host_authority(manifest)
    compiler = PlanCompiler(
        manifest=manifest,
        store=CompilationStore(),
        authority_resolver=resolver,
    )

    with pytest.raises(CompilationFailure) as exc_info:
        compiler.compile(
            plan,
            intent=intent,
            scope_ref="project:alpha",
            selection=compiler.server_selection("model.rerun", scope_ref="project:alpha"),
        )
    assert exc_info.value.code == "DURABLE_RESERVATION_REQUIRED"


def test_plan_compiler_has_no_live_dependency_on_retired_issuer() -> None:
    source = inspect.getsource(plan_compiler_module)

    assert "ServerCompilationRecordIssuerV1" not in source


def test_agent_planning_facade_does_not_export_retired_issuer() -> None:
    assert "ServerCompilationRecordIssuerV1" not in planning_contracts_module.__all__
    assert not hasattr(planning_contracts_module, "ServerCompilationRecordIssuerV1")


def test_compiler_requires_host_compiler_port_when_authority_is_present() -> None:
    manifest, plan, intent = _draft_and_intent()
    _server, _handle, resolver = _host_authority(manifest)
    compiler = PlanCompiler(
        manifest=manifest,
        store=CompilationStore(reservation_root=_new_test_reservation_root()),
        authority_resolver=resolver,
    )

    with pytest.raises(CompilationFailure) as exc_info:
        compiler.compile(
            plan,
            intent=intent,
            scope_ref="project:alpha",
            selection=compiler.server_selection("model.rerun", scope_ref="project:alpha"),
        )

    assert exc_info.value.code == "HOST_COMPILER_INTEGRATION_REQUIRED"


def test_compiler_rejects_malformed_host_compiler_result() -> None:
    compiler, plan, intent = _compiler()

    class MalformedHost:
        def compile(self, _request):
            return {"compiled_plan": "forged"}

    compiler.host_compiler = MalformedHost()

    with pytest.raises(CompilationFailure) as exc_info:
        _compile(compiler, plan, intent)

    assert exc_info.value.code == "HOST_COMPILER_RESULT_INVALID"


def test_compiler_rejects_host_record_that_does_not_bind_to_workflow_snapshots() -> None:
    compiler, plan, intent = _compiler()
    base_host = compiler.host_compiler
    assert base_host is not None

    class SnapshotMismatchHost:
        def compile(self, request):
            result = base_host.compile(request)
            record_payload = result.record._record_payload()
            record_payload["policy_snapshot_ref"] = "policy:tampered"
            record = replace(
                result.record,
                policy_snapshot_ref="policy:tampered",
                record_digest=sha256_canonical(record_payload),
            )
            compiler.store.record_store.resolve = lambda _reference: record  # type: ignore[method-assign]
            reference = ServerCompilationRecordReferenceV1(
                record_id=record.record_id,
                record_digest=record.record_digest,
                semantic_plan_hash=record.semantic_plan_hash,
            )
            return HostCompilationResultV1(
                compiled_plan=result.compiled_plan,
                record=record,
                reference=reference,
            )

    compiler.host_compiler = SnapshotMismatchHost()

    with pytest.raises(CompilationFailure) as exc_info:
        _compile(compiler, plan, intent)

    assert exc_info.value.code == "HOST_COMPILER_RESULT_INVALID"


def test_independent_compilation_stores_do_not_both_reserve_same_key() -> None:
    key = "e" * 64
    root = Path(_test_reservation_root()) / "shared-reservation"
    root.mkdir()
    owner = CompilationStore(reservation_root=root)
    contender = CompilationStore(reservation_root=root)

    def reserve() -> str:
        try:
            with contender.reservation(key) as replay:
                return "replay" if replay is not None else "owner"
        except CompilationFailure as exc:
            return exc.code

    with owner.reservation(key) as replay:
        assert replay is None
        with ThreadPoolExecutor(max_workers=1) as pool:
            outcome = pool.submit(reserve).result(timeout=5)

    assert outcome == "IDEMPOTENCY_CONFLICT"


def test_independent_processes_do_not_both_reserve_same_durable_key(tmp_path) -> None:
    key = "f" * 64
    context = mp.get_context("fork")
    owner_ready = context.Event()
    owner_release = context.Event()
    owner_result = context.Queue()
    contender_ready = context.Event()
    contender_result = context.Queue()

    owner = context.Process(
        target=_reserve_in_process,
        args=(str(tmp_path), key, owner_ready, owner_release, owner_result, True),
    )
    owner.start()
    assert owner_ready.wait(5)
    assert owner_result.get(timeout=5) == "owner"

    contender = context.Process(
        target=_reserve_in_process,
        args=(str(tmp_path), key, contender_ready, context.Event(), contender_result, False),
    )
    contender.start()
    assert contender_ready.wait(5)
    assert contender_result.get(timeout=5) == "IDEMPOTENCY_CONFLICT"
    contender.join(timeout=5)
    assert contender.exitcode == 0

    owner_release.set()
    owner.join(timeout=5)
    assert owner.exitcode == 0
    assert (tmp_path / f"reservation-{key}.v1").is_file()


def test_public_compiler_rejects_compiled_workflow_input_and_json_reissue() -> None:
    compiler, plan, intent = _compiler()
    compiled = _compile(compiler, plan, intent).compiled_plan
    selection = _selection(compiler, intent)

    with pytest.raises(CompilationFailure) as object_exc:
        compiler.compile(
            compiled,
            intent=intent,
            scope_ref="project:alpha",
            selection=selection,
        )
    assert object_exc.value.code == "FORGED_AUTHORITY"

    with pytest.raises(CompilationFailure) as json_exc:
        compiler.compile(
            compiled.to_dict(),
            intent=intent,
            scope_ref="project:alpha",
            selection=selection,
        )
    assert json_exc.value.code in {"FORGED_AUTHORITY", "DRAFT_INVALID"}


def test_compiler_rejects_imported_selection_token_even_when_fields_are_valid() -> None:
    from workbench.agent.capability_discovery import CapabilitySelectionV1

    compiler, plan, intent = _compiler()
    entry = compiler.manifest.require(intent.capability_ids[0])
    forged = CapabilitySelectionV1(
        capability_id=entry.capability_id,
        scope_ref="project:alpha",
        manifest_digest=compiler.manifest.manifest_digest,
        entry=entry,
        receipt_digest="a" * 64,
        authority_binding_digest=compiler.authority_resolver.resolve(
            scope_ref="project:alpha",
            principal_ref="principal:unknown",
            session_ref="session:unknown",
            project_ref="project:alpha",
        ).binding_digest,
    )

    with pytest.raises(CompilationFailure) as exc_info:
        compiler.compile(
            plan,
            intent=intent,
            scope_ref="project:alpha",
            selection=forged,
        )

    assert exc_info.value.code == "FORGED_AUTHORITY"


def test_internal_registry_path_cannot_bypass_disabled_natural_language() -> None:
    compiler, plan, intent = _compiler()
    entry = compiler.manifest.require("code.execute")
    code_plan = replace(
        plan,
        capability_refs=(entry.capability_ref,),
        method_ref="method:code.execute",
        effect=PlanEffectV1.WRITE,
        risk_level=PlanRiskLevelV1.HIGH,
        resource_budget=dict(entry.resource_budget),
        contract_snapshot_refs=(entry.contract_ref,),
        policy_snapshot_ref=entry.policy_snapshot_ref,
        nodes=(
            {
                "node_id": "execute",
                "capability_ref": "capability:code.execute",
                "read_refs": ["dataset:source"],
                "write_mode": "none",
                "options": {"analysis_mode": "predictive"},
            },
        ),
    )
    code_intent = replace(intent, capability_ids=(entry.capability_id,))

    with pytest.raises(CompilationFailure) as exc_info:
        compiler._compile_for_registry(code_plan, intent=code_intent, scope_ref="project:alpha")

    assert exc_info.value.code == "NATURAL_LANGUAGE_DISABLED"


def test_reservation_root_path_replacement_cannot_create_a_second_owner(tmp_path) -> None:
    root = tmp_path / "reservation-root"
    root.mkdir()
    old_root = tmp_path / "reservation-root-old"
    key = "a" * 64
    first = CompilationStore(reservation_root=root)
    root.rename(old_root)
    root.mkdir()
    try:
        with first.reservation(key) as first_replay:
            assert first_replay is None
            with pytest.raises(ValueError) as exc_info:
                CompilationStore(reservation_root=root)
        assert "identity changed" in str(exc_info.value)
    finally:
        first.close()


def test_malformed_selection_proof_is_a_stable_typed_failure() -> None:
    from workbench.agent.capability_discovery import CapabilitySelectionV1

    compiler, plan, intent = _compiler()
    malformed = object.__new__(CapabilitySelectionV1)

    with pytest.raises(CompilationFailure) as exc_info:
        compiler.compile(
            plan,
            intent=intent,
            scope_ref="project:alpha",
            selection=malformed,
        )

    assert exc_info.value.code == "FORGED_AUTHORITY"


def test_snapshot_bootstrap_with_imported_proof_is_rejected() -> None:
    with pytest.raises(ValueError, match="host authority handle"):
        ScopeAuthorityResolverV1._from_server_snapshots(
            (
                {
                    "scope_ref": "project:alpha",
                    "principal_ref": "principal:unknown",
                    "session_ref": "session:unknown",
                    "project_ref": "project:alpha",
                },
            ),
            _server_proof=_SERVER_SCOPE_AUTHORITY_PROOF,
        )


def test_host_handle_and_selection_proofs_cannot_be_copied_or_reconstructed() -> None:
    from workbench.agent.capability_discovery import CapabilityDiscovery

    compiler, plan, intent = _compiler()
    handle = compiler.authority_handle
    assert handle is not None

    with pytest.raises(TypeError):
        copy.copy(handle)
    with pytest.raises(TypeError):
        pickle.dumps(handle)

    selection = _selection(compiler, intent)
    receipt = CapabilityDiscovery(
        compiler.manifest,
        authority_handle=handle,
    ).query(
        intent.capability_ids[0],
        scope_ref="project:alpha",
        project_ref="project:alpha",
    )
    with pytest.raises(TypeError):
        copy.copy(receipt)
    with pytest.raises(TypeError):
        pickle.dumps(receipt)

    with pytest.raises(TypeError):
        pickle.dumps(selection)

    with pytest.raises(TypeError):
        copy.copy(selection)

    left, right = socket.socketpair()
    try:
        from workbench.agent.authority import HostAuthorityHandleV1

        with pytest.raises(TypeError):
            HostAuthorityHandleV1._from_host_socket(left, "channel:caller-forged")
    finally:
        left.close()
        right.close()


def test_store_without_durable_authority_fails_closed_before_reservation() -> None:
    store = CompilationStore()
    with pytest.raises(CompilationFailure) as exc_info:
        with store.reservation("b" * 64):
            pass
    assert exc_info.value.code == "DURABLE_RESERVATION_REQUIRED"


def test_public_host_authority_server_constructor_is_not_an_authority_boundary() -> None:
    manifest = build_capability_manifest()

    with pytest.raises(TypeError):
        HostAuthorityServerV1(
            manifest_digest=manifest.manifest_digest,
            natural_language_capability_ids=(
                entry.capability_id for entry in manifest.entries if entry.natural_language_enabled
            ),
            bindings=(
                {
                    "scope_ref": "project:alpha",
                    "principal_ref": "principal:unknown",
                    "session_ref": "session:unknown",
                    "project_ref": "project:alpha",
                },
            ),
        )


def test_caller_socket_with_arbitrary_private_ticket_cannot_become_host_handle() -> None:
    from workbench.agent.authority import HostAuthorityHandleV1

    left, right = socket.socketpair()
    try:
        with pytest.raises(TypeError):
            HostAuthorityHandleV1._from_host_socket(
                left,
                "channel:caller-forged",
                _construction_ticket=object(),
            )
    finally:
        left.close()
        right.close()


def test_deployment_config_cannot_be_caller_constructed() -> None:
    from workbench.agent.authority import HostAuthorityEndpointConfigV1

    with pytest.raises(TypeError):
        HostAuthorityEndpointConfigV1(
            endpoint_path="/private/tmp/forged.sock",
            endpoint_device=1,
            endpoint_inode=1,
            peer_uid=1,
            peer_pid=2,
            scope_ref="project:attacker",
            session_ref="session:attacker",
            shared_secret="11" * 32,
        )


def test_host_authority_requires_configured_external_endpoint(monkeypatch) -> None:
    monkeypatch.delenv(_HOST_CONFIG_ENV, raising=False)

    with pytest.raises(HostAuthorityChannelError) as exc_info:
        load_host_authority_config()

    assert exc_info.value.code == "HOST_AUTHORITY_REQUIRED"


def test_socketpair_and_same_process_path_socket_fail_before_authority_use() -> None:
    from workbench.agent.authority import HostAuthorityEndpointConfigV1

    left, right = socket.socketpair()
    try:
        with pytest.raises(HostAuthorityChannelError) as config_error:
            admit_host_authority_endpoint(left, deployment_config=object())  # type: ignore[arg-type]
        assert config_error.value.code == "HOST_AUTHORITY_REQUIRED"
    finally:
        left.close()
        right.close()

    directory = tempfile.mkdtemp(prefix="workbench-agent-fake-", dir="/private/tmp")
    path = str(Path(directory) / "authority.sock")
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(path)
    listener.listen(1)
    endpoint_stat = os.lstat(path)
    config_path = str(Path(directory) / "config.json")
    Path(config_path).write_text(
        json.dumps(
            {
                "schema_version": _HOST_CONFIG_SCHEMA,
                "endpoint_path": path,
                "endpoint_device": int(endpoint_stat.st_dev),
                "endpoint_inode": int(endpoint_stat.st_ino),
                "peer_uid": os.getuid(),
                "peer_pid": os.getpid(),
                "scope_ref": "project:attacker",
                "session_ref": "session:attacker",
                "shared_secret": "55" * 32,
                "purpose_prefix": "agent.",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    os.chmod(config_path, 0o600)
    previous = os.environ.get(_HOST_CONFIG_ENV)
    os.environ[_HOST_CONFIG_ENV] = config_path
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(path)
        config = load_host_authority_config()
        with pytest.raises(HostAuthorityChannelError) as path_error:
            admit_host_authority_endpoint(client, deployment_config=config)
        assert path_error.value.code == "FORGED_AUTHORITY"
    finally:
        client.close()
        listener.close()
        _restore_loaded_config(config_path, previous)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        try:
            os.rmdir(directory)
        except OSError:
            pass


@pytest.mark.parametrize(
    "override",
    [
        {"endpoint_path": "/private/tmp/workbench-agent-wrong-endpoint.sock"},
        {"endpoint_device": 0},
        {"endpoint_inode": 0},
        {"peer_uid": 0 if os.getuid() != 0 else 1},
        {"peer_pid": os.getpid() + 1},
        {"shared_secret": "66" * 32},
    ],
)
def test_external_endpoint_rejects_wrong_config_identity(override: dict[str, object]) -> None:
    manifest = build_capability_manifest()
    server = _ExternalHostAuthority(manifest)
    config_path = ""
    previous = None
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        config, config_path, previous = server.loaded_config(**override)
        client.connect(server.path)
        with pytest.raises(HostAuthorityChannelError):
            admit_host_authority_endpoint(client, deployment_config=config)
    finally:
        client.close()
        if config_path:
            _restore_loaded_config(config_path, previous)
        server.close()


def test_supervisor_fd_admission_still_binds_path_and_peer() -> None:
    manifest = build_capability_manifest()
    server = _ExternalHostAuthority(manifest)
    fd = -1
    handle = None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(server.path)
        fd = client.detach()
        config = load_host_authority_config()
        handle = admit_host_authority_fd(fd, deployment_config=config)
        assert handle.channel_id.startswith("channel:")
    finally:
        if handle is not None:
            handle.close()
        if fd >= 0:
            os.close(fd)
        server.close()


def test_admitted_handle_rejects_endpoint_inode_replacement() -> None:
    manifest = build_capability_manifest()
    server, handle, _resolver = _host_authority(manifest)
    replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        os.unlink(server.path)
        replacement.bind(server.path)
        replacement.listen(1)
        with pytest.raises(HostAuthorityChannelError) as exc_info:
            handle.channel_id
        assert exc_info.value.code == "FORGED_AUTHORITY"
    finally:
        replacement.close()
        handle.close()
        _close_test_host()


def test_authority_config_and_handle_reject_copy_pickle_json_and_object_new() -> None:
    manifest = build_capability_manifest()
    server, handle, _resolver = _host_authority(manifest)
    config = load_host_authority_config()
    try:
        for value in (config, handle):
            with pytest.raises(TypeError):
                copy.copy(value)
            with pytest.raises(TypeError):
                copy.deepcopy(value)
            with pytest.raises(TypeError):
                pickle.dumps(value)
            with pytest.raises(TypeError):
                json.dumps(value)

        forged = object.__new__(type(handle))
        for name in type(handle).__slots__:
            if name != "__weakref__" and hasattr(handle, name):
                object.__setattr__(forged, name, getattr(handle, name))
        with pytest.raises(HostAuthorityChannelError) as exc_info:
            forged.channel_id
        assert exc_info.value.code == "FORGED_AUTHORITY"
    finally:
        handle.close()
        server.close()


def test_admitted_handle_cannot_be_reused_after_fork() -> None:
    manifest = build_capability_manifest()
    server, handle, _resolver = _host_authority(manifest)
    context = mp.get_context("fork")
    result_queue = context.Queue()
    process = context.Process(target=_forked_handle_probe, args=(handle, result_queue))
    try:
        process.start()
        process.join(timeout=10)
        assert process.exitcode == 0
        assert result_queue.get(timeout=2) == "FORGED_AUTHORITY"
    finally:
        handle.close()
        server.close()
