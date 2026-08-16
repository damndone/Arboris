"""Deterministic, repository-local provider contribution catalog.

The catalog is a manifest-input seam.  It validates declarations and contract
references but never imports, resolves, or executes feature code.
"""

from __future__ import annotations

import json
import os
import stat
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.contracts.common.contract_ref import (
    CONTRACT_DIGEST_MISMATCH,
    CONTRACT_DUPLICATE,
    CONTRACT_MAJOR_INCOMPATIBLE,
    CONTRACT_UNRESOLVED,
    ContractRefError,
    ContractRefResolverV1,
)
from workbench.contracts.common.provider import (
    PROVIDER_CONTRIBUTION_INVALID,
    PROVIDER_DUPLICATE,
    PROVIDER_EXECUTOR_INVALID,
    PROVIDER_REF_INVALID,
    PROVIDER_UNRESOLVED,
    ProviderContractError,
    ProviderContributionV1,
)


_CATALOG_FIELDS = frozenset(
    {
        "provider_id",
        "semantic_version",
        "contracts",
        "exposure_paths",
        "adapter_declarations",
        "projection_refs",
        "renderer_refs",
        "policy_refs",
    }
)


ProviderCatalogError = ProviderContractError


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, f"duplicate JSON key {key}")
        value[key] = item
    return value


def _load_json(path: Path) -> Mapping[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except ProviderContractError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, path.name) from exc
    if type(value) is not dict:
        raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "manifest root")
    return value


def _reject_path_like_refs(value: object, location: str = "manifest") -> None:
    if type(value) is str:
        normalized = unicodedata.normalize("NFC", value)
        windows_absolute = PureWindowsPath(normalized).is_absolute()
        if (
            normalized.startswith(("/", "\\", "~"))
            or windows_absolute
            or "://" in normalized
            or any(part == ".." for part in normalized.replace("\\", "/").split("/"))
        ):
            if location.endswith(".executor_ref"):
                raise ProviderContractError(PROVIDER_EXECUTOR_INVALID)
            raise ProviderContractError(PROVIDER_REF_INVALID, f"path-like ref at {location}")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_path_like_refs(item, f"{location}.{key}")
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _reject_path_like_refs(item, f"{location}[{index}]")


def _normalized_filename(path: Path) -> str:
    return unicodedata.normalize("NFC", path.name).casefold()


def _safe_manifest_paths(root: Path) -> tuple[Path, ...]:
    try:
        root_info = os.lstat(root)
    except OSError as exc:
        raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "builtin root unavailable") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "builtin root is not a directory")

    paths: list[Path] = []
    for path in root.iterdir():
        if path.suffix != ".json":
            continue
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, path.name) from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, f"unsafe manifest {path.name}")
        paths.append(path)
    return tuple(paths)


def _provider_error(error: ContractRefError) -> ProviderContractError:
    if error.code == CONTRACT_DUPLICATE:
        return ProviderContractError(PROVIDER_DUPLICATE)
    if error.code in {CONTRACT_UNRESOLVED, CONTRACT_MAJOR_INCOMPATIBLE}:
        return ProviderContractError(PROVIDER_UNRESOLVED)
    if error.code == CONTRACT_DIGEST_MISMATCH:
        return ProviderContractError(PROVIDER_REF_INVALID, "digest mismatch")
    return ProviderContractError(PROVIDER_REF_INVALID)


@dataclass(frozen=True)
class ProviderCatalogV1:
    """Immutable catalog projection produced from fixed builtin manifests."""

    providers: tuple[ProviderContributionV1, ...]
    source_filenames: tuple[str, ...]
    contract_resolver: ContractRefResolverV1
    catalog_digest: str

    @property
    def digest(self) -> str:
        return self.catalog_digest

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(provider.provider_id for provider in self.providers)

    def digest_payload(self) -> list[dict[str, object]]:
        return [
            {
                "filename": filename,
                "contribution": provider.to_dict(),
            }
            for filename, provider in zip(self.source_filenames, self.providers, strict=True)
        ]

    @property
    def manifest_inputs(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "provider_id": provider.provider_id,
                "semantic_version": provider.semantic_version,
                "provider_digest": sha256_canonical(provider.to_dict()),
                "contract_refs": [ref.to_dict() for ref in provider.contract_refs],
                "adapter_ids": [adapter.adapter_id for adapter in provider.adapter_declarations],
            }
            for provider in self.providers
        )

    @property
    def path_rows(self) -> tuple[dict[str, object], ...]:
        rows: list[dict[str, object]] = []
        for provider in self.providers:
            provider_digest = sha256_canonical(provider.to_dict())
            for path in provider.exposure_paths:
                rows.append(
                    {
                        "provider_id": provider.provider_id,
                        "provider_digest": provider_digest,
                        "path_id": path.path_id,
                        "semantic_version": path.semantic_version,
                        "exposure": path.exposure,
                        "capability_ref": path.capability_ref.to_dict(),
                        "projection_refs": {
                            key: ref.to_dict() for key, ref in sorted(path.projection_refs.items())
                        },
                    }
                )
        return tuple(rows)

    @property
    def descriptor_inputs(self) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "provider_id": provider.provider_id,
                "semantic_version": provider.semantic_version,
                "capability_refs": [
                    path.capability_ref.to_dict() for path in provider.exposure_paths
                ],
                "path_ids": [path.path_id for path in provider.exposure_paths],
            }
            for provider in self.providers
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "providers": [provider.to_dict() for provider in self.providers],
            "source_filenames": list(self.source_filenames),
            "catalog_digest": self.catalog_digest,
        }


def _load_catalog_from_root(root: Path | str) -> ProviderCatalogV1:
    """Test-only injection seam; callers must use ``load_builtin_catalog``."""

    manifest_root = Path(root)
    paths = _safe_manifest_paths(manifest_root)
    candidates: list[tuple[str, ProviderContributionV1]] = []
    seen_provider_ids: set[str] = set()

    for path in paths:
        payload = _load_json(path)
        _reject_path_like_refs(payload)
        if set(payload) != _CATALOG_FIELDS:
            raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, f"fields in {path.name}")
        contribution = ProviderContributionV1.from_dict(payload)
        if contribution.provider_id in seen_provider_ids:
            raise ProviderContractError(PROVIDER_DUPLICATE, contribution.provider_id)
        seen_provider_ids.add(contribution.provider_id)
        candidates.append((_normalized_filename(path), contribution))

    candidates.sort(key=lambda item: (item[0], item[1].provider_id))
    filenames = [filename for filename, _ in candidates]
    providers = [provider for _, provider in candidates]
    declared_refs = [ref for provider in providers for ref in provider.contract_refs]

    if not providers:
        raise ProviderContractError(PROVIDER_CONTRIBUTION_INVALID, "no builtin manifests")

    try:
        resolver = ContractRefResolverV1(declared_refs)
    except ContractRefError as exc:
        raise _provider_error(exc) from exc

    for provider in providers:
        for ref in provider.all_referenced_contracts():
            try:
                resolver.resolve(ref)
            except ContractRefError as exc:
                raise _provider_error(exc) from exc

    digest_payload = [
        {"filename": filename, "contribution": provider.to_dict()}
        for filename, provider in zip(filenames, providers, strict=True)
    ]
    return ProviderCatalogV1(
        providers=tuple(providers),
        source_filenames=tuple(filenames),
        contract_resolver=resolver,
        catalog_digest=sha256_canonical(digest_payload),
    )


def _make_builtin_catalog_loader():
    repository_builtin_root = Path(__file__).with_name("builtin")

    def load_repository_builtin_catalog() -> ProviderCatalogV1:
        return _load_catalog_from_root(repository_builtin_root)

    return load_repository_builtin_catalog


_LOAD_REPOSITORY_BUILTIN_CATALOG = _make_builtin_catalog_loader()


def load_builtin_catalog() -> ProviderCatalogV1:
    """Load only the repository-local builtin provider manifests."""

    return _LOAD_REPOSITORY_BUILTIN_CATALOG()


def load_provider_catalog() -> ProviderCatalogV1:
    return load_builtin_catalog()


def build_provider_catalog() -> ProviderCatalogV1:
    return load_builtin_catalog()


def load_catalog() -> ProviderCatalogV1:
    return load_builtin_catalog()


__all__ = [
    "ProviderCatalogError",
    "ProviderCatalogV1",
    "build_provider_catalog",
    "load_builtin_catalog",
    "load_catalog",
    "load_provider_catalog",
]
