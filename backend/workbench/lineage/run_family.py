"""Gate 1 — RunFamily as a first-class persisted identity (spec DEC-NB-002).

A run family is the analysis evolution line a notebook binds to. Before this
module the id was *derived*: `agent/chains.py: legacy_family_anchor()` scanned the
rerun forest for a root run and returned `legacy-family:<root_run_id>`. That
cannot satisfy DEC-NB-001 ("a notebook may exist before any run"), and it makes
the id move whenever ancestry is re-scanned.

Identity rules:

- A newly created family is `run-family:<uuid4>`. It MUST NOT encode a run id —
  `create_family()` deliberately takes no run argument at all.
- A migrated family keeps its `legacy-family:<root_run_id>` string **verbatim**,
  because that exact string is already visible through the serve layer. Migration
  changes where the id comes from, never what it says.

Storage follows the append-only JSONL convention already used by agent sessions
and operation records: one file per family under `<root>/run-families/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..artifacts import read_json, write_json
from .family import scan_family


def _jsonl() -> tuple[Any, Any]:
    """Lazily borrow the shared atomic JSONL primitives.

    Imported inside the call rather than at module scope because
    `workbench.agent` imports this module (chains re-exports
    `legacy_family_anchor`), and a top-level import would close that cycle.
    """

    from ..agent.storage import append_jsonl_atomic, read_jsonl

    return append_jsonl_atomic, read_jsonl

RUN_FAMILY_SCHEMA_VERSION = "run-family.v1"
RUN_FAMILY_MEMBERSHIP_SCHEMA_VERSION = "run-family-membership.v1"
RUN_FAMILY_DIRNAME = "run-families"
RUN_FAMILY_MEMBERSHIP_FILENAME = "run_family.json"
MIGRATION_STATE_FILENAME = "_migration.json"

NEW_FAMILY_PREFIX = "run-family:"
LEGACY_FAMILY_PREFIX = "legacy-family:"

ORIGINS = frozenset({"notebook", "run_adoption", "legacy_migration"})


class RunFamilyConflict(ValueError):
    """A family already exists with different identity fields."""


class RunFamilyRequired(ValueError):
    """A run created after the migration cutover declared no family.

    Deliberately NOT recoverable by falling back to `legacy_family_anchor()`:
    the whole point of Gate 1 is that new runs stop deriving their family from
    ancestry. A caller that hits this must supply a family, not retry loosely.
    """

    code = "RUN_FAMILY_REQUIRED"


class RunFamilyMismatch(ValueError):
    """A run was used where a different family's run was required."""

    code = "RUN_FAMILY_MISMATCH"


@dataclass(frozen=True)
class ResolvedRunFamily:
    run_family_id: str
    source: str  # persisted | legacy_fallback
    warning: str | None = None
    derived_run_family_id: str | None = None
    consistency_error: str | None = None


@dataclass(frozen=True)
class RunFamily:
    run_family_id: str
    project_id: str
    created_at: str
    created_by: str
    origin: str
    legacy_anchor_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUN_FAMILY_SCHEMA_VERSION,
            "run_family_id": self.run_family_id,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "origin": self.origin,
            "legacy_anchor_run_id": self.legacy_anchor_run_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RunFamily":
        return cls(
            run_family_id=str(value["run_family_id"]),
            project_id=str(value["project_id"]),
            created_at=str(value["created_at"]),
            created_by=str(value["created_by"]),
            origin=str(value["origin"]),
            legacy_anchor_run_id=value.get("legacy_anchor_run_id"),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def legacy_family_anchor(runs_root: Path | str, run_id: str) -> str:
    """Return the deterministic family id used when adopting a legacy run.

    Canonical home for the derivation. It used to live in `agent/chains.py`,
    which made the lineage layer depend on the agent layer once membership
    resolution needed it; `agent.chains` now re-exports this. Derivation is a
    lineage concern, and after Gate 1 it is a *read-side compatibility* concern
    only — never a way for a new run to acquire a family.
    """

    family = scan_family(Path(runs_root), run_id)
    root_run_id = family.ancestors[-1] if family.ancestors else run_id
    return f"{LEGACY_FAMILY_PREFIX}{root_run_id}"


def encode_family_filename(run_family_id: str) -> str:
    """Map a family id onto a path-safe filename.

    Family ids carry a `<kind>:` prefix. A colon is legal in POSIX filenames but
    hostile on other filesystems and in URLs, so it is encoded rather than
    stripped — stripping would make `run-family:x` and `legacy-family:x` collide.
    """

    if not run_family_id:
        raise ValueError("run_family_id must not be empty")
    encoded = run_family_id.replace(":", "__")
    if Path(encoded).name != encoded:
        raise ValueError(f"run_family_id is not path-safe: {run_family_id!r}")
    return encoded


class RunFamilyStore:
    """Append-only project-local store of run family identities."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.directory = self.root / RUN_FAMILY_DIRNAME
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _path(self, run_family_id: str) -> Path:
        return self.directory / f"{encode_family_filename(run_family_id)}.jsonl"

    def create_family(
        self,
        *,
        project_id: str,
        created_by: str,
        origin: str,
    ) -> RunFamily:
        """Create a family whose identity is independent of any run.

        This signature takes no run argument on purpose: a family that can be
        created before its first run must not be able to borrow a run's id.
        """

        if origin not in ORIGINS - {"legacy_migration"}:
            raise ValueError(
                f"origin must be one of {sorted(ORIGINS - {'legacy_migration'})}; "
                "legacy families are created through adopt_legacy_family()"
            )
        family = RunFamily(
            run_family_id=f"{NEW_FAMILY_PREFIX}{uuid4()}",
            project_id=project_id,
            created_at=_now(),
            created_by=created_by,
            origin=origin,
        )
        return self._write_new(family)

    def adopt_legacy_family(
        self,
        *,
        run_family_id: str,
        project_id: str,
        created_by: str,
        legacy_anchor_run_id: str,
    ) -> RunFamily:
        """Persist a pre-existing derived family id **verbatim**.

        Idempotent: re-running migration returns the stored record unchanged. It
        raises rather than rewriting when the stored record disagrees, so a
        half-finished migration can never silently repoint a family.
        """

        if not run_family_id.startswith(LEGACY_FAMILY_PREFIX):
            raise ValueError(
                f"legacy family id must start with {LEGACY_FAMILY_PREFIX!r}: {run_family_id!r}"
            )
        family = RunFamily(
            run_family_id=run_family_id,
            project_id=project_id,
            created_at=_now(),
            created_by=created_by,
            origin="legacy_migration",
            legacy_anchor_run_id=legacy_anchor_run_id,
        )
        with self._lock:
            existing = self._read(run_family_id)
            if existing is not None:
                self._assert_identical(existing, family)
                return existing
            return self._write_new(family)

    def get(self, run_family_id: str) -> RunFamily:
        with self._lock:
            family = self._read(run_family_id)
            if family is None:
                raise KeyError(f"unknown run family: {run_family_id}")
            return family

    def exists(self, run_family_id: str) -> bool:
        with self._lock:
            return self._read(run_family_id) is not None

    def list_families(self) -> list[RunFamily]:
        with self._lock:
            if not self.directory.exists():
                return []
            families: list[RunFamily] = []
            _, read_jsonl = _jsonl()
            for path in sorted(self.directory.glob("*.jsonl")):
                records = read_jsonl(path)
                if records:
                    families.append(RunFamily.from_dict(records[0]))
            return families

    # ------------------------------------------------------------------
    # Migration cutover state
    #
    # A project that has completed migration must never gain an unbound run.
    # This marker is what lets the reader tell "old data we must tolerate" from
    # "a new run that skipped the contract" — without it, both look identical.
    # ------------------------------------------------------------------

    @property
    def _migration_path(self) -> Path:
        return self.directory / MIGRATION_STATE_FILENAME

    def mark_migrated(self, run_ids: list[str]) -> dict[str, Any]:
        """Record the cutover. Idempotent: re-running unions the run set."""

        with self._lock:
            state = self.migration_state()
            migrated = sorted(set(state.get("migrated_run_ids", [])) | set(run_ids))
            payload = {
                "schema_version": "run-family-migration.v1",
                "migrated_at": state.get("migrated_at") or _now(),
                "migrated_run_ids": migrated,
            }
            self.directory.mkdir(parents=True, exist_ok=True)
            write_json(self._migration_path, payload)
            return payload

    def migration_state(self) -> dict[str, Any]:
        with self._lock:
            try:
                value = read_json(self._migration_path)
            except (FileNotFoundError, OSError, ValueError):
                return {}
            return value if isinstance(value, dict) else {}

    def has_migrated(self) -> bool:
        return bool(self.migration_state())

    def _read(self, run_family_id: str) -> RunFamily | None:
        _, read_jsonl = _jsonl()
        records = read_jsonl(self._path(run_family_id))
        if not records:
            return None
        return RunFamily.from_dict(records[0])

    def _write_new(self, family: RunFamily) -> RunFamily:
        append_jsonl_atomic, read_jsonl = _jsonl()
        with self._lock:
            path = self._path(family.run_family_id)
            if path.exists() and read_jsonl(path):
                raise RunFamilyConflict(
                    f"run family already exists: {family.run_family_id}"
                )
            append_jsonl_atomic(path, family.to_dict())
            return family

    @staticmethod
    def _assert_identical(stored: RunFamily, incoming: RunFamily) -> None:
        # created_at/created_by are provenance of the *record*, not of the
        # identity; re-running migration legitimately produces a new timestamp.
        for field in ("run_family_id", "project_id", "origin", "legacy_anchor_run_id"):
            if getattr(stored, field) != getattr(incoming, field):
                raise RunFamilyConflict(
                    f"run family {stored.run_family_id} already persisted with "
                    f"{field}={getattr(stored, field)!r}, refusing to rewrite as "
                    f"{getattr(incoming, field)!r}"
                )


# ----------------------------------------------------------------------
# Run <-> family membership
# ----------------------------------------------------------------------


def read_run_family_membership(run_root: Path) -> dict[str, Any] | None:
    """Return the persisted membership record for a run, or None if unbound."""

    try:
        value = read_json(run_root / RUN_FAMILY_MEMBERSHIP_FILENAME)
    except (FileNotFoundError, OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def bind_run_to_family(
    run_root: Path,
    *,
    run_family_id: str,
    bound_by: str,
) -> dict[str, Any]:
    """Persist a run's family membership.

    Idempotent for an identical binding so migration can be re-run, but a
    *different* family raises: repointing a run at another analysis line would
    silently rewrite lineage that other records already reference.
    """

    if not run_family_id:
        raise ValueError("run_family_id must not be empty")
    existing = read_run_family_membership(run_root)
    if existing is not None:
        if existing.get("run_family_id") != run_family_id:
            raise RunFamilyConflict(
                f"run {run_root.name} is already bound to "
                f"{existing.get('run_family_id')!r}; refusing to rebind to {run_family_id!r}"
            )
        return existing
    payload = {
        "schema_version": RUN_FAMILY_MEMBERSHIP_SCHEMA_VERSION,
        "run_id": run_root.name,
        "run_family_id": run_family_id,
        "bound_by": bound_by,
        "bound_at": _now(),
    }
    write_json(run_root / RUN_FAMILY_MEMBERSHIP_FILENAME, payload)
    return payload


def resolve_run_family(
    project_root: Path | str,
    run_id: str,
    *,
    check_consistency: bool = False,
) -> ResolvedRunFamily:
    """Three-level read priority (plan Task 2 Step 4).

    1. persisted membership            -> authoritative
    2. no membership, project not yet migrated -> derive + compatibility warning
    3. no membership, project migrated -> RUN_FAMILY_REQUIRED

    Case 3 is the point of the whole gate: once a project has cut over, an
    unbound run is a contract violation on the write path, not old data.

    `check_consistency` additionally derives the ancestry family and reports a
    divergence (never repairs it — see `_check_consistency`). It is off by
    default because deriving costs an O(runs-in-project) scan, which is the
    exact cost persisting membership was meant to remove; paying it on every
    read would make the persisted path pointless. Consistency is instead swept
    over the whole project by `verify_project_families()`.
    """

    project_root = Path(project_root)
    runs_root = project_root / "runs"
    run_root = runs_root / run_id
    membership = read_run_family_membership(run_root)
    store = RunFamilyStore(project_root, create=False)

    if membership is not None:
        persisted = str(membership.get("run_family_id", ""))
        if not persisted:
            raise RunFamilyConflict(f"membership record for {run_id} carries no family id")
        if not check_consistency:
            return ResolvedRunFamily(run_family_id=persisted, source="persisted")
        return _check_consistency(runs_root, run_id, persisted)

    if store.has_migrated():
        raise RunFamilyRequired(
            f"run {run_id} has no persisted run family, and project "
            f"{project_root.name} has already migrated. A newly created run must "
            "declare its family; ancestry fallback is not available here."
        )

    derived = legacy_family_anchor(runs_root, run_id)
    return ResolvedRunFamily(
        run_family_id=derived,
        source="legacy_fallback",
        warning=(
            f"run {run_id} has no persisted run family; derived {derived} from "
            "ancestry. Run the run-family migration to make this durable."
        ),
    )


def _check_consistency(runs_root: Path, run_id: str, persisted: str) -> ResolvedRunFamily:
    """Persisted wins, always — but a disagreement must be reported, not hidden.

    This function performs no writes. Repairing a divergence is an explicit
    operator action, never a side effect of reading.
    """

    try:
        derived = legacy_family_anchor(runs_root, run_id)
    except (OSError, ValueError):
        derived = None
    if derived is not None and derived != persisted and persisted.startswith(LEGACY_FAMILY_PREFIX):
        return ResolvedRunFamily(
            run_family_id=persisted,
            source="persisted",
            derived_run_family_id=derived,
            consistency_error=(
                f"run {run_id}: persisted family {persisted} disagrees with "
                f"ancestry-derived {derived}; persisted identity is authoritative "
                "and was NOT rewritten"
            ),
        )
    return ResolvedRunFamily(run_family_id=persisted, source="persisted")


def ensure_run_family_binding(
    project_root: Path | str,
    run_root: Path,
    *,
    rerun_of: str | None,
    created_by: str,
    run_family_id: str | None = None,
) -> str | None:
    """Bind a freshly created run to a family, on the write path.

    Returns the bound family id, or None when the project has not migrated yet
    (pre-cutover projects keep deriving on read, exactly as before — see
    `resolve_run_family`). Binding is deliberately gated on migration so that
    turning a project strict is one explicit act rather than a drift that
    happens whenever a run is created.

    A child run **inherits** its parent's family; it never re-derives one. A
    root run gets a genuinely new family (`origin="run_adoption"`), which is not
    the forbidden ancestry fallback: nothing is being reconstructed from lineage.
    """

    project_root = Path(project_root)
    store = RunFamilyStore(project_root, create=False)

    if run_family_id:
        # An explicit family (Gate 4: the notebook's) is authoritative and binds
        # even before the project has migrated — the caller has stated the answer,
        # so there is nothing to derive and nothing to be strict about.
        if not store.exists(run_family_id):
            raise KeyError(f"unknown run family: {run_family_id}")
        if rerun_of:
            assert_run_in_family(project_root, run_family_id=run_family_id, run_id=rerun_of)
        bind_run_to_family(run_root, run_family_id=run_family_id, bound_by=created_by)
        return run_family_id

    if not store.has_migrated():
        return None

    if rerun_of:
        inherited = resolve_run_family(project_root, rerun_of).run_family_id
        bind_run_to_family(run_root, run_family_id=inherited, bound_by="rerun_inheritance")
        return inherited

    family = RunFamilyStore(project_root).create_family(
        project_id=project_root.name,
        created_by=created_by,
        origin="run_adoption",
    )
    bind_run_to_family(run_root, run_family_id=family.run_family_id, bound_by="create_run")
    return family.run_family_id


def verify_project_families(project_root: Path | str) -> list[str]:
    """Sweep every run for persisted/ancestry divergence. Read-only.

    Returns human-readable consistency errors. Repair is never automatic: a
    divergence means two sources of truth disagree about which analysis line a
    run belongs to, and guessing would silently rewrite lineage.
    """

    project_root = Path(project_root)
    runs_root = project_root / "runs"
    if not runs_root.is_dir():
        return []
    errors: list[str] = []
    for entry in sorted(runs_root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            resolved = resolve_run_family(project_root, entry.name, check_consistency=True)
        except RunFamilyRequired as error:
            errors.append(str(error))
            continue
        if resolved.consistency_error:
            errors.append(resolved.consistency_error)
    return errors


def migrate_project_families(
    project_root: Path | str,
    *,
    created_by: str = "legacy_migration",
) -> dict[str, Any]:
    """Give every existing run a persisted family, keeping its id verbatim.

    Grouping is by `legacy_family_anchor()`, so the id every caller already sees
    stays the id it gets afterwards. Migration changes the *source* of the
    answer (scan -> record), never the answer.

    Idempotent by construction: adopting an existing family returns the stored
    record, binding an already-bound run is a no-op, and the cutover marker
    unions run ids. Re-running after an interruption completes the job instead
    of creating a second, competing set of records.
    """

    project_root = Path(project_root)
    runs_root = project_root / "runs"
    store = RunFamilyStore(project_root)
    known_before = {family.run_family_id for family in store.list_families()}

    migrated: list[str] = []
    created: list[str] = []
    if runs_root.is_dir():
        for entry in sorted(runs_root.iterdir()):
            if not entry.is_dir():
                continue
            run_id = entry.name
            family_id = legacy_family_anchor(runs_root, run_id)
            anchor = family_id[len(LEGACY_FAMILY_PREFIX):]
            store.adopt_legacy_family(
                run_family_id=family_id,
                project_id=project_root.name,
                created_by=created_by,
                legacy_anchor_run_id=anchor,
            )
            if family_id not in known_before and family_id not in created:
                created.append(family_id)
            bind_run_to_family(entry, run_family_id=family_id, bound_by="legacy_migration")
            migrated.append(run_id)

    state = store.mark_migrated(migrated)
    return {
        "migrated_run_ids": state["migrated_run_ids"],
        "created_families": created,
        "migrated_at": state["migrated_at"],
    }


def assert_run_in_family(
    project_root: Path | str,
    *,
    run_family_id: str,
    run_id: str,
) -> None:
    """Refuse a run that belongs to a different analysis line.

    DEC-NB-001: a notebook binds to exactly one family, and its active head must
    belong to that family. Cross-family runs may be *referenced* for read-only
    comparison; they may never become the head.
    """

    resolved = resolve_run_family(project_root, run_id)
    if resolved.run_family_id != run_family_id:
        raise RunFamilyMismatch(
            f"run {run_id} belongs to {resolved.run_family_id}, "
            f"which is not {run_family_id}"
        )
