"""The `code.execute` typed operation (v1.7 G3).

This is the "terminal can change code" capability, expressed the only way the
rest of the system can audit: as a typed operation with the same
proposal → confirm → execute → Operation Record → verification lifecycle as
`data.columns.cast`. Privilege comes from this operation being registered, not
from which input box the text was typed into.

PREVIEW SEMANTICS (the design question this module settles)
-----------------------------------------------------------
A cast can compute its outcome without writing anything. Arbitrary code cannot:
the only way to know what it does is to run it. So `preview_code_execute`
**really runs the code**, inside the sandbox, writing to a disposable temp
directory that is thrown away. Nothing in the project is touched. What the user
confirms is therefore a real result, not a prediction.

`apply_code_execute` then runs the code a **second** time, materializing into
the derived directory — and requires the result to be byte-identical to the
previewed one. That second run is not waste, it is the enforcement mechanism:
we claim the code is a pure transform, and this is what turns that claim from a
promise into a check. Non-deterministic code fails loudly
(`NondeterministicCodeError`) instead of silently materializing something the
user never approved.

Replaying an execution key re-runs the deterministic code and replays each
idempotent materialization step. That is intentional: a crash can leave the
artifact and recipe present before registration, graph commit, or node-index
repair, and replay must reconcile all of those durable projections.

CODE CONTRACT
-------------
Deliberately narrow: the code receives `df` (the source frame) and must bind
`result` to a DataFrame. It does not do its own file IO. That keeps the
sandbox's write permission scoped to a single temp directory, keeps the source
physically unwritable, and lets the derived artifact reuse the same
dtype-sidecar writer every other data operation uses.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from .artifacts import read_json, sha256_file, write_json
from .data_operations import (
    ALLOWED_OUTPUT_FORMATS,
    DataCastOutputFormat,
    _ensure_node_index_entry,
    _ensure_registered_artifact,
    _frame_dtypes,
    _graph_store_for,
    _mark_downstream_invalidation,
    _read_frame,
    _schema_fingerprint,
    _write_frame_artifact,
)
from .graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from .sandbox import (
    SandboxLimits,
    SandboxTimeoutError,
    SandboxUnavailableError,
    run_python_sandboxed,
)

CodeLanguage = Literal["python"]
ALLOWED_LANGUAGES = frozenset({"python"})

MAX_CODE_CHARS = 20_000
MAX_STDOUT_CHARS = 8_000
MAX_ERROR_CHARS = 4_000
PREVIEW_ROW_LIMIT = 5


class CodeExecuteValidationError(ValueError):
    """The code.execute spec, preview or source is not usable."""


class NondeterministicCodeError(RuntimeError):
    """The confirmed code produced a different result on execution.

    The user approved a specific result; re-running produced another one, so the
    code is not the pure transform this operation requires. Refusing is the only
    honest option — materializing would persist something never confirmed.
    """


@dataclass(frozen=True)
class CodeExecuteSpecV1:
    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    code: str
    language: CodeLanguage = "python"
    output_format: DataCastOutputFormat = "csv"
    operation_id: str = "code.execute"
    operation_version: str = "v1"

    def __post_init__(self) -> None:
        for field_name in ("source_run_id", "source_node_id", "source_artifact_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("code must be a non-empty string")
        if len(self.code) > MAX_CODE_CHARS:
            raise ValueError(f"code must be at most {MAX_CODE_CHARS} characters")
        if self.language not in ALLOWED_LANGUAGES:
            raise ValueError("language must be one of: " + ", ".join(sorted(ALLOWED_LANGUAGES)))
        if self.output_format not in ALLOWED_OUTPUT_FORMATS:
            raise ValueError(
                "output_format must be one of: " + ", ".join(sorted(ALLOWED_OUTPUT_FORMATS))
            )

    @property
    def code_sha256(self) -> str:
        return hashlib.sha256(self.code.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "source_run_id": self.source_run_id,
            "source_node_id": self.source_node_id,
            "source_artifact_id": self.source_artifact_id,
            "language": self.language,
            "code": self.code,
            "code_sha256": self.code_sha256,
            "output_format": self.output_format,
        }


@dataclass(frozen=True)
class CodeDtypeChange:
    column: str
    before_dtype: str
    after_dtype: str

    def to_dict(self) -> dict[str, str]:
        return {
            "column": self.column,
            "before_dtype": self.before_dtype,
            "after_dtype": self.after_dtype,
        }


@dataclass(frozen=True)
class CodeExecutePreview:
    spec: CodeExecuteSpecV1
    source_sha256: str
    row_count_before: int
    row_count_after: int
    columns_added: tuple[str, ...]
    columns_removed: tuple[str, ...]
    dtype_changes: tuple[CodeDtypeChange, ...]
    schema_fingerprint_before: str
    schema_fingerprint_after: str
    result_fingerprint: str
    result_preview_rows: tuple[dict[str, Any], ...]
    stdout: str
    fingerprint: str
    downstream_invalidation: tuple[str, ...] = field(default_factory=tuple)
    status: str = "ready"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.spec.operation_id,
            "operation_version": self.spec.operation_version,
            "source_run_id": self.spec.source_run_id,
            "source_node_id": self.spec.source_node_id,
            "source_artifact_id": self.spec.source_artifact_id,
            "language": self.spec.language,
            "code": self.spec.code,
            "code_sha256": self.spec.code_sha256,
            "output_format": self.spec.output_format,
            "source_sha256": self.source_sha256,
            "row_count_before": self.row_count_before,
            "row_count_after": self.row_count_after,
            "columns_added": list(self.columns_added),
            "columns_removed": list(self.columns_removed),
            "dtype_changes": [change.to_dict() for change in self.dtype_changes],
            "schema_fingerprint_before": self.schema_fingerprint_before,
            "schema_fingerprint_after": self.schema_fingerprint_after,
            "result_fingerprint": self.result_fingerprint,
            "result_preview_rows": [dict(row) for row in self.result_preview_rows],
            "stdout": self.stdout,
            "fingerprint": self.fingerprint,
            "downstream_invalidation": list(self.downstream_invalidation),
            "status": self.status,
            "error": self.error,
        }


@dataclass(frozen=True)
class CodeExecuteEffect:
    execution_key: str
    artifact_id: str
    artifact_path: str
    recipe_artifact_id: str
    recipe_path: str
    child_node_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "execution_key": self.execution_key,
            "artifact_id": self.artifact_id,
            "artifact_path": self.artifact_path,
            "recipe_artifact_id": self.recipe_artifact_id,
            "recipe_path": self.recipe_path,
            "child_node_id": self.child_node_id,
        }


@dataclass(frozen=True)
class _CodeRunOutcome:
    ok: bool
    frame: pd.DataFrame | None
    stdout: str
    error: str | None


_MANIFEST_PLACEHOLDER = "__WORKBENCH_MANIFEST_JSON__"

# NOTE: injected with str.replace, not str.format/f-string — this template is
# mostly braces, and brace-escaping a security-relevant harness is a bug farm.
_HARNESS = '''\
import json
import sys
import traceback
from pathlib import Path

import pandas as pd

MANIFEST = json.loads(__WORKBENCH_MANIFEST_JSON__)
OUT_DIR = Path(MANIFEST["out_dir"])


def _read_frame(path):
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix == ".csv":
        frame = pd.read_csv(target)
    elif suffix in (".parquet", ".pq"):
        frame = pd.read_parquet(target)
    elif suffix in (".xlsx", ".xls"):
        frame = pd.read_excel(target)
    else:
        raise RuntimeError("unsupported source format: " + (suffix or "<none>"))
    sidecar = target.with_name(target.stem + ".schema.json")
    if sidecar.is_file():
        dtypes = json.loads(sidecar.read_text()).get("dtypes", {})
        for column, dtype in dtypes.items():
            if column not in frame.columns:
                continue
            try:
                if str(dtype).startswith("datetime64"):
                    frame[column] = pd.to_datetime(frame[column], errors="coerce")
                else:
                    frame[column] = frame[column].astype(dtype)
            except (TypeError, ValueError):
                pass
    return frame


def _fail(message, tb=""):
    OUT_DIR.joinpath("meta.json").write_text(
        json.dumps({"ok": False, "error": message, "traceback": tb})
    )
    sys.exit(1)


try:
    df = _read_frame(MANIFEST["source_path"])
except BaseException as exc:  # noqa: BLE001 - reported to the user verbatim
    _fail("failed to read the source artifact: " + str(exc), traceback.format_exc()[-4000:])

namespace = {"df": df, "pd": pd}
try:
    exec(compile(MANIFEST["code"], "<user-code>", "exec"), namespace)
except BaseException as exc:  # noqa: BLE001 - user code errors are user feedback
    _fail(
        "".join(traceback.format_exception_only(type(exc), exc)).strip(),
        traceback.format_exc()[-4000:],
    )

if "result" not in namespace:
    _fail("code did not define `result` (bind the output DataFrame to `result`)")

result = namespace["result"]
if not isinstance(result, pd.DataFrame):
    _fail("`result` must be a pandas DataFrame, got " + type(result).__name__)

result = result.reset_index(drop=True)
try:
    OUT_DIR.joinpath("result.schema.json").write_text(
        json.dumps({"dtypes": {str(c): str(result[c].dtype) for c in result.columns}})
    )
    OUT_DIR.joinpath("result.csv").write_text(result.to_csv(index=False))
    OUT_DIR.joinpath("meta.json").write_text(json.dumps({"ok": True}))
except BaseException as exc:  # noqa: BLE001
    _fail("failed to write the result: " + str(exc), traceback.format_exc()[-4000:])
'''


def _build_harness(*, source_path: Path, code: str, out_dir: Path) -> str:
    """Render the harness with the manifest embedded as an inert JSON literal.

    The user code travels as data (a JSON string compiled inside the child), not
    as text spliced into this template, so it cannot break out of the harness by
    manipulating indentation or quoting.
    """

    manifest = json.dumps(
        {"source_path": str(source_path), "code": code, "out_dir": str(out_dir)},
        ensure_ascii=False,
    )
    return _HARNESS.replace(_MANIFEST_PLACEHOLDER, repr(manifest))


def _bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated, {len(text) - limit} more characters]"


def _run_code(source_path: Path, spec: CodeExecuteSpecV1) -> _CodeRunOutcome:
    """Run the code once in the sandbox against a disposable output directory."""

    with tempfile.TemporaryDirectory(prefix="wb-code-exec-") as work_name:
        work = Path(work_name)
        out_dir = work / "out"
        out_dir.mkdir()
        script = work / "harness.py"
        script.write_text(
            _build_harness(source_path=source_path, code=spec.code, out_dir=out_dir),
            encoding="utf-8",
        )
        try:
            result = run_python_sandboxed(
                script,
                writable_dirs=[out_dir],
                limits=SandboxLimits(),
            )
        except SandboxTimeoutError as exc:
            return _CodeRunOutcome(ok=False, frame=None, stdout="", error=str(exc))

        stdout = _bounded(result.stdout, MAX_STDOUT_CHARS)
        meta_path = out_dir / "meta.json"
        if not meta_path.is_file():
            # Killed before it could report — a resource limit (CPU/memory) or a
            # hard crash. stderr is the only evidence we have.
            detail = _bounded(result.stderr, MAX_ERROR_CHARS).strip()
            return _CodeRunOutcome(
                ok=False,
                frame=None,
                stdout=stdout,
                error=detail
                or (
                    "the code was terminated without producing a result "
                    "(it likely exceeded its CPU or memory limit)"
                ),
            )
        meta = read_json(meta_path)
        if not meta.get("ok"):
            error = str(meta.get("error") or "the code failed")
            traceback_text = str(meta.get("traceback") or "")
            if traceback_text:
                error = f"{error}\n\n{traceback_text}"
            return _CodeRunOutcome(
                ok=False, frame=None, stdout=stdout, error=_bounded(error, MAX_ERROR_CHARS)
            )
        frame = _read_frame(out_dir / "result.csv")
        return _CodeRunOutcome(ok=True, frame=frame, stdout=stdout, error=None)


def _frame_fingerprint(frame: pd.DataFrame) -> str:
    """Content identity of a result frame: values and dtypes, order-sensitive."""

    payload = {
        "dtypes": _frame_dtypes(frame),
        "csv": frame.to_csv(index=False),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _preview_rows(frame: pd.DataFrame) -> tuple[dict[str, Any], ...]:
    head = frame.head(PREVIEW_ROW_LIMIT)
    rows: list[dict[str, Any]] = []
    for record in head.to_dict(orient="records"):
        rows.append({str(key): _json_safe(value) for key, value in record.items()})
    return tuple(rows)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and (pd.isna(value) or value in (float("inf"), float("-inf"))):
            return None
        return value
    if pd.isna(value):
        return None
    return str(value)


def _resolve_source_for(project_root: Path | str, spec: CodeExecuteSpecV1):
    """Resolve the source through the cast resolver, which owns the invariants."""

    from .data_operations import DataColumnCastSpecV1, DataColumnCastValidationError, _resolve_source

    probe = DataColumnCastSpecV1(
        source_run_id=spec.source_run_id,
        source_node_id=spec.source_node_id,
        source_artifact_id=spec.source_artifact_id,
        column="__code_execute_probe__",
        target_dtype="string",
    )
    try:
        return _resolve_source(project_root, probe)
    except DataColumnCastValidationError as exc:
        raise CodeExecuteValidationError(str(exc)) from exc


def preview_code_execute(
    project_root: Path | str,
    spec: CodeExecuteSpecV1,
) -> CodeExecutePreview:
    """Really run the code in the sandbox, into a temp dir that is discarded.

    Raises SandboxUnavailableError when the host has no isolation backend: the
    capability is simply not available there, and we never fall back to running
    the code unsandboxed.
    """

    run_root, graph, node, artifact, source_path = _resolve_source_for(project_root, spec)
    before_frame = _read_frame(source_path)
    schema_before = _schema_fingerprint(before_frame)
    source_sha = str(artifact.get("sha256") or sha256_file(source_path))
    downstream = tuple(
        node_id for node_id, candidate in graph.nodes.items() if candidate.kind == NodeKind.MODEL
    )

    outcome = _run_code(source_path, spec)
    if not outcome.ok or outcome.frame is None:
        return CodeExecutePreview(
            spec=spec,
            source_sha256=source_sha,
            row_count_before=len(before_frame),
            row_count_after=0,
            columns_added=(),
            columns_removed=(),
            dtype_changes=(),
            schema_fingerprint_before=schema_before,
            schema_fingerprint_after="",
            result_fingerprint="",
            result_preview_rows=(),
            stdout=outcome.stdout,
            fingerprint="",
            downstream_invalidation=downstream,
            status="blocked",
            error=outcome.error,
        )

    after_frame = outcome.frame
    before_dtypes = _frame_dtypes(before_frame)
    after_dtypes = _frame_dtypes(after_frame)
    added = tuple(c for c in after_dtypes if c not in before_dtypes)
    removed = tuple(c for c in before_dtypes if c not in after_dtypes)
    changes = tuple(
        CodeDtypeChange(column=column, before_dtype=before_dtypes[column], after_dtype=dtype)
        for column, dtype in after_dtypes.items()
        if column in before_dtypes and before_dtypes[column] != dtype
    )
    schema_after = _schema_fingerprint(after_frame)
    result_fingerprint = _frame_fingerprint(after_frame)
    identity = {
        "spec": spec.to_dict(),
        "source_sha256": source_sha,
        "schema_before": schema_before,
        "schema_after": schema_after,
        "result_fingerprint": result_fingerprint,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return CodeExecutePreview(
        spec=spec,
        source_sha256=source_sha,
        row_count_before=len(before_frame),
        row_count_after=len(after_frame),
        columns_added=added,
        columns_removed=removed,
        dtype_changes=changes,
        schema_fingerprint_before=schema_before,
        schema_fingerprint_after=schema_after,
        result_fingerprint=result_fingerprint,
        result_preview_rows=_preview_rows(after_frame),
        stdout=outcome.stdout,
        fingerprint=fingerprint,
        downstream_invalidation=downstream,
        status="ready",
        error=None,
    )


def code_execute_execution_key(spec: CodeExecuteSpecV1, preview: CodeExecutePreview) -> str:
    identity = {
        "spec": spec.to_dict(),
        "preview_fingerprint": preview.fingerprint,
        "source_sha256": preview.source_sha256,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"exec_{digest[:32]}"


def _effect_for(key: str, output_format: str) -> tuple[CodeExecuteEffect, Path, Path]:
    data_ext = "xlsx" if output_format == "xlsx" else "csv"
    relative_dir = Path("derived") / "code_execute" / key
    artifact_rel = (relative_dir / f"data.{data_ext}").as_posix()
    recipe_rel = (relative_dir / "recipe.json").as_posix()
    effect = CodeExecuteEffect(
        execution_key=f"exec_{key}",
        artifact_id=f"code_exec_{key}",
        artifact_path=artifact_rel,
        recipe_artifact_id=f"code_exec_recipe_{key}",
        recipe_path=recipe_rel,
        child_node_id=f"code-exec:{key}",
    )
    return effect, Path(artifact_rel), Path(recipe_rel)


def apply_code_execute(
    project_root: Path | str,
    spec: CodeExecuteSpecV1,
    preview: CodeExecutePreview,
    *,
    execution_key_value: str | None = None,
) -> CodeExecuteEffect:
    """Materialize the confirmed result — idempotent, determinism-checked."""

    if preview.spec != spec:
        raise CodeExecuteValidationError("preview spec does not match operation spec")
    if preview.status != "ready":
        raise CodeExecuteValidationError("code execute preview is blocked")

    run_root, graph, source_node, source_artifact, source_path = _resolve_source_for(
        project_root, spec
    )
    execution = execution_key_value or code_execute_execution_key(spec, preview)
    key = execution.removeprefix("exec_")
    effect, artifact_rel_path, recipe_rel_path = _effect_for(key, spec.output_format)
    artifact_rel = artifact_rel_path.as_posix()
    recipe_rel = recipe_rel_path.as_posix()
    artifact_path = run_root / artifact_rel
    recipe_path = run_root / recipe_rel

    source_sha = str(source_artifact.get("sha256") or sha256_file(source_path))
    if source_sha != preview.source_sha256:
        raise CodeExecuteValidationError("code execute preview is stale")

    outcome = _run_code(source_path, spec)
    if not outcome.ok or outcome.frame is None:
        raise CodeExecuteValidationError(
            f"code failed during execution: {outcome.error or 'unknown error'}"
        )
    frame = outcome.frame
    if _frame_fingerprint(frame) != preview.result_fingerprint:
        raise NondeterministicCodeError(
            "the code produced a different result than the one confirmed; it is "
            "not a deterministic transform, so nothing was written"
        )

    _write_frame_artifact(artifact_path, frame, spec.output_format)

    recipe = {
        "schema_version": "code-execute.v1",
        "execution_key": execution,
        "spec": spec.to_dict(),
        "preview": preview.to_dict(),
        "source": {
            "artifact_id": spec.source_artifact_id,
            "sha256": source_artifact.get("sha256"),
            "path": source_artifact.get("path"),
        },
        "result": {
            "artifact_id": effect.artifact_id,
            "path": artifact_rel,
            "schema_fingerprint": preview.schema_fingerprint_after,
            "result_fingerprint": preview.result_fingerprint,
        },
    }
    if recipe_path.exists() and read_json(recipe_path) != recipe:
        raise CodeExecuteValidationError("deterministic code execute recipe path is occupied")
    if not recipe_path.exists():
        write_json(recipe_path, recipe)

    _ensure_registered_artifact(
        run_root,
        artifact_id=effect.artifact_id,
        path=artifact_path,
        artifact_type="derived_data",
        step="code.execute",
        inputs=[spec.source_artifact_id],
    )
    _ensure_registered_artifact(
        run_root,
        artifact_id=effect.recipe_artifact_id,
        path=recipe_path,
        artifact_type="metadata",
        step="code.execute",
        inputs=[spec.source_artifact_id, effect.artifact_id],
    )

    store = _graph_store_for(run_root)
    store.mutate(
        spec.source_run_id,
        lambda current: (
            current
            if effect.child_node_id in current.nodes
            else _commit_code_graph_child(
                current,
                spec=spec,
                preview=preview,
                artifact_rel=artifact_rel,
                recipe_rel=recipe_rel,
                child_node_id=effect.child_node_id,
                execution_key=execution,
            )
        ),
    )
    _ensure_node_index_entry(
        run_root,
        child_node_id=effect.child_node_id,
        node_hash=sha256_file(artifact_path),
        artifact_rel=artifact_rel,
        producing_stage="code.execute",
    )
    return effect


def _code_summary(preview: CodeExecutePreview) -> str:
    parts: list[str] = [f"{preview.row_count_after} rows"]
    if preview.columns_added:
        parts.append(f"+{len(preview.columns_added)} columns")
    if preview.columns_removed:
        parts.append(f"-{len(preview.columns_removed)} columns")
    if preview.dtype_changes:
        parts.append(f"{len(preview.dtype_changes)} dtype changes")
    return "; ".join(parts) + "; downstream rerun required"


def _commit_code_graph_child(
    graph: Graph,
    *,
    spec: CodeExecuteSpecV1,
    preview: CodeExecutePreview,
    artifact_rel: str,
    recipe_rel: str,
    child_node_id: str,
    execution_key: str,
) -> Graph:
    branch_id = f"code-exec:{execution_key.removeprefix('exec_')[:20]}"
    child = Node(
        id=child_node_id,
        kind=NodeKind.DATASET_STAGE,
        display_label="Run code",
        created_at=datetime.now(timezone.utc).isoformat(),
        parent_stage_id=spec.source_node_id,
        branch_id=branch_id,
        trust=Trust.OK,
        payload_ref=artifact_rel,
        summary=_code_summary(preview),
        annotations=(
            {
                "type": "data_operation",
                "operation_id": spec.operation_id,
                "execution_key": execution_key,
                "recipe_path": recipe_rel,
                "schema_fingerprint": preview.schema_fingerprint_after,
                "language": spec.language,
                "code_sha256": spec.code_sha256,
            },
        ),
        stage=Stage.TRANSFORM,
    )
    nodes = dict(graph.nodes)
    nodes[child_node_id] = child
    nodes = _mark_downstream_invalidation(
        nodes,
        reason="code_execute",
        source_node_id=spec.source_node_id,
        child_node_id=child_node_id,
    )
    edges = dict(graph.edges)
    edge_id = f"edge:{child_node_id}"
    edges[edge_id] = Edge(
        id=edge_id,
        source_id=spec.source_node_id,
        target_id=child_node_id,
        op=spec.operation_id,
        params={
            "language": spec.language,
            "code_sha256": spec.code_sha256,
            "execution_key": execution_key,
            "schema_fingerprint_before": preview.schema_fingerprint_before,
            "schema_fingerprint_after": preview.schema_fingerprint_after,
        },
    )
    branches = dict(graph.branches)
    branches[branch_id] = BranchRef(
        id=branch_id,
        forked_from_node_id=spec.source_node_id,
        head_node_ids=(child_node_id,),
    )
    return Graph(
        schema_version=graph.schema_version,
        run_id=graph.run_id,
        nodes=nodes,
        edges=edges,
        branches=branches,
        legacy=graph.legacy,
    )


__all__ = [
    "ALLOWED_LANGUAGES",
    "MAX_CODE_CHARS",
    "CodeDtypeChange",
    "CodeExecuteEffect",
    "CodeExecutePreview",
    "CodeExecuteSpecV1",
    "CodeExecuteValidationError",
    "NondeterministicCodeError",
    "SandboxUnavailableError",
    "apply_code_execute",
    "code_execute_execution_key",
    "preview_code_execute",
]
