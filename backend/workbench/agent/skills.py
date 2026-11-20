"""Bounded, read-only skill metadata discovery and explicit data-only loading.

Discovery never reads past the YAML frontmatter. Its metadata hash is not a
content version: only load() reads and hashes a complete SKILL.md. Nothing in
this module executes scripts, follows skill references, or grants permissions.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Iterator

import yaml

from ..identity.root import open_validated_project_root

CATALOG_SCHEMA = 'workbench.skills.catalog.v1'
MAX_HEADER_BYTES = 8192
MAX_SKILL_BYTES = 128 * 1024
MAX_CONFIG_BYTES = 16384
MAX_ROOT_ENTRIES = 256
MAX_SKILLS = 128
_NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
_SOURCES = ('builtin', 'personal', 'project')


class SkillError(ValueError):
    def __init__(self, message: str, *, code: str = 'SKILL_INVALID'):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SkillMetadata:
    selector: str
    name: str
    description: str
    source: str
    origin: str
    metadata_sha256: str
    enabled: bool = True
    disabled_by: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SkillDiagnostic:
    code: str
    source: str
    origin: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SkillConflict:
    name: str
    selectors: tuple[str, ...]

    def to_dict(self) -> dict:
        return {'name': self.name, 'selectors': list(self.selectors)}


@dataclass(frozen=True)
class SkillDiscovery:
    skills: tuple[SkillMetadata, ...]
    conflicts: tuple[SkillConflict, ...]
    diagnostics: tuple[SkillDiagnostic, ...]
    schema: str = CATALOG_SCHEMA

    def to_dict(self) -> dict:
        return {'schema': self.schema, 'skills': [item.to_dict() for item in self.skills],
                'conflicts': [item.to_dict() for item in self.conflicts],
                'diagnostics': [item.to_dict() for item in self.diagnostics]}


@dataclass(frozen=True)
class LoadedSkill:
    metadata: SkillMetadata
    content: str
    version_sha256: str
    content_role: str = 'untrusted_data'
    schema: str = 'workbench.skill.loaded.v1'

    def to_dict(self) -> dict:
        return asdict(self)


def _name(value) -> bool:
    return type(value) is str and len(value) <= 64 and _NAME.fullmatch(value) is not None


def _selector(value: str) -> tuple[str | None, str]:
    if type(value) is not str:
        raise SkillError('skill selector must be a name or source:name', code='SKILL_SELECTOR')
    parts = value.split(':')
    if len(parts) == 1 and _name(parts[0]):
        return None, parts[0]
    if len(parts) == 2 and parts[0] in _SOURCES and _name(parts[1]):
        return parts[0], parts[1]
    raise SkillError('invalid skill name or source-qualified selector', code='SKILL_SELECTOR')


def _absolute(value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts:
        raise SkillError('skill source requires an absolute path without traversal', code='SKILL_PATH')
    return path


@contextmanager
def _directory(path: Path, *, required: bool = False) -> Iterator[int | None]:
    try:
        observed = path.lstat()
    except FileNotFoundError:
        if required:
            raise SkillError(f'required skill source is missing: {path}', code='SKILL_SOURCE_MISSING')
        yield None
        return
    if not stat.S_ISDIR(observed.st_mode):
        raise SkillError(f'skill source must be a directory without symlinks: {path}', code='SKILL_PATH')
    with open_validated_project_root(path) as admitted:
        if admitted.validated.path != path:
            raise SkillError('skill source path must not contain symlinks', code='SKILL_PATH')
        yield admitted.fd


def _regular(parent: int, name: str, limit: int) -> int:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        observed = os.fstat(fd)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise SkillError('skill files must be regular and single-link', code='SKILL_PATH')
        if observed.st_size > limit:
            raise SkillError('skill file exceeds its byte limit', code='SKILL_LIMIT')
        return fd
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def _skill_file(root: int, name: str) -> Iterator[int]:
    directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
    try:
        fd = _regular(directory, 'SKILL.md', MAX_SKILL_BYTES)
        try:
            yield fd
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def _signature(fd: int):
    observed = os.fstat(fd)
    if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
        raise SkillError('skill file binding changed', code='SKILL_PATH')
    return (observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns, observed.st_ctime_ns)


def _bounded(fd: int, limit: int) -> bytes:
    chunks = []
    size = 0
    while True:
        value = os.read(fd, min(65536, limit + 1 - size))
        if not value:
            return b''.join(chunks)
        chunks.append(value)
        size += len(value)
        if size > limit:
            raise SkillError('skill content exceeds its byte limit', code='SKILL_LIMIT')


class _MetadataLoader(yaml.SafeLoader):
    pass


def _yaml_mapping(loader, node, deep=False):
    values = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in values:
            raise SkillError('skill frontmatter contains a duplicate or invalid key', code='SKILL_FORMAT')
        values[key] = loader.construct_object(value_node, deep=deep)
    return values


_MetadataLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _yaml_mapping)


def _header(fd: int, folder: str) -> tuple[str, str, str]:
    # Single-byte unbuffered reads are intentional: buffered readline() may
    # prefetch body bytes before a skill has been explicitly requested.
    raw = bytearray()
    lines = []
    current = bytearray()
    while len(raw) < MAX_HEADER_BYTES:
        value = os.read(fd, 1)
        if not value:
            raise SkillError('skill frontmatter is missing its delimiter', code='SKILL_FORMAT')
        raw.extend(value)
        current.extend(value)
        if value != b'\n':
            continue
        line = bytes(current)
        current.clear()
        marker = line.rstrip(b'\r\n')
        if not lines:
            if marker != b'---':
                raise SkillError('SKILL.md must start with YAML frontmatter', code='SKILL_FORMAT')
        elif marker == b'---':
            break
        lines.append(line)
    else:
        raise SkillError('skill frontmatter exceeds its byte limit', code='SKILL_LIMIT')
    try:
        values = yaml.load(b''.join(lines[1:]).decode('utf-8'), Loader=_MetadataLoader)
    except UnicodeDecodeError as error:
        raise SkillError('skill metadata must be UTF-8', code='SKILL_UTF8') from error
    except yaml.YAMLError as error:
        raise SkillError('invalid skill YAML frontmatter', code='SKILL_FORMAT') from error
    if not isinstance(values, dict) or not _name(values.get('name')) or values['name'] != folder:
        raise SkillError('skill name must match its directory slug', code='SKILL_FORMAT')
    description = values.get('description')
    if type(description) is not str or not description.strip() or len(description) > 1024:
        raise SkillError('skill description must be a nonblank bounded string', code='SKILL_FORMAT')
    return values['name'], description.strip(), hashlib.sha256(raw).hexdigest()


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SkillError('duplicate skill configuration field', code='SKILL_CONFIG')
        result[key] = value
    return result


class SkillCatalog:
    def __init__(self, project_root: Path | str, *, personal_root: Path | str | None = None,
                 builtin_root: Path | str | None = None):
        self.project_root = _absolute(project_root)
        self._roots = {
            'builtin': _absolute(builtin_root) if builtin_root is not None else Path(__file__).with_name('builtin_skills'),
            'personal': _absolute(personal_root) if personal_root is not None else Path.home() / '.config/econometrics-workbench/skills',
            'project': self.project_root / 'skills',
        }

    def _disabled(self) -> tuple[str, ...]:
        with _directory(self.project_root, required=True):
            with _directory(self._roots['project']) as root:
                if root is None:
                    return ()
                try:
                    fd = _regular(root, 'disabled.json', MAX_CONFIG_BYTES)
                except FileNotFoundError:
                    return ()
                try:
                    raw = _bounded(fd, MAX_CONFIG_BYTES)
                finally:
                    os.close(fd)
        try:
            values = json.loads(raw.decode('utf-8'), object_pairs_hook=_json_object)
        except (ValueError, UnicodeError) as error:
            if isinstance(error, SkillError):
                raise
            raise SkillError('invalid skill configuration JSON or UTF-8', code='SKILL_CONFIG') from error
        if (type(values) is not dict or set(values) != {'schema', 'disabled'}
                or values['schema'] != 'workbench.skills.v1' or type(values['disabled']) is not list
                or len(values['disabled']) > MAX_SKILLS):
            raise SkillError('invalid skill configuration shape', code='SKILL_CONFIG')
        disabled = values['disabled']
        for selector in disabled:
            try:
                _selector(selector)
            except SkillError as error:
                raise SkillError('invalid skill configuration selector', code='SKILL_CONFIG') from error
        if len(set(disabled)) != len(disabled):
            raise SkillError('duplicate disabled skill configuration selector', code='SKILL_CONFIG')
        return tuple(disabled)

    def discover(self) -> SkillDiscovery:
        """Return frontmatter metadata, explicit conflicts and bounded errors."""
        try:
            disabled = self._disabled()
        except SkillError:
            raise
        except (OSError, ValueError) as error:
            raise SkillError('skill configuration is unsafe or unavailable', code='SKILL_CONFIG') from error
        skills = []
        diagnostics = []
        for source, path in self._roots.items():
            try:
                with _directory(path, required=source == 'builtin') as root:
                    if root is None:
                        continue
                    names = []
                    with os.scandir(root) as entries:
                        for index, entry in enumerate(entries):
                            if index >= MAX_ROOT_ENTRIES:
                                raise SkillError('skill source exceeds its entry limit', code='SKILL_LIMIT')
                            if entry.is_symlink():
                                diagnostics.append(SkillDiagnostic('SKILL_PATH', source, str(path / entry.name), 'symlink skill entry refused'))
                            elif entry.is_dir(follow_symlinks=False) and not entry.name.startswith('.'):
                                names.append(entry.name)
                    for folder in sorted(names):
                        origin = str(path / folder / 'SKILL.md')
                        try:
                            if not _name(folder):
                                raise SkillError('invalid skill directory slug', code='SKILL_FORMAT')
                            with _skill_file(root, folder) as fd:
                                before = _signature(fd)
                                name, description, digest = _header(fd, folder)
                                if _signature(fd) != before:
                                    raise SkillError('skill changed during metadata discovery', code='SKILL_CHANGED')
                            skills.append(SkillMetadata(f'{source}:{name}', name, description, source, origin, digest))
                            if len(skills) > MAX_SKILLS:
                                raise SkillError('catalog exceeds its skill limit', code='SKILL_LIMIT')
                        except (OSError, SkillError) as error:
                            if isinstance(error, SkillError) and error.code == 'SKILL_LIMIT' and len(skills) > MAX_SKILLS:
                                raise
                            diagnostics.append(SkillDiagnostic(getattr(error, 'code', 'SKILL_PATH'), source, origin, str(error)))
            except (OSError, ValueError) as error:
                if isinstance(error, SkillError) and (source == 'builtin' or error.code == 'SKILL_LIMIT'):
                    raise
                if source == 'builtin':
                    raise SkillError('builtin skill source is unsafe or unavailable', code='SKILL_PATH') from error
                diagnostics.append(SkillDiagnostic(getattr(error, 'code', 'SKILL_PATH'), source, str(path), str(error)))
        known = {item.selector for item in skills} | {item.name for item in skills}
        if set(disabled) - known:
            raise SkillError('skill configuration disables an unknown selector', code='SKILL_CONFIG')
        configured = tuple(replace(item, enabled=False, disabled_by=item.name if item.name in disabled else item.selector)
                           if item.name in disabled or item.selector in disabled else item for item in skills)
        conflicts = tuple(SkillConflict(name, tuple(item.selector for item in configured if item.name == name))
                          for name in sorted({item.name for item in configured})
                          if sum(item.name == name for item in configured) > 1)
        return SkillDiscovery(configured, conflicts, tuple(diagnostics))

    def load(self, selector: str, *, expected_version: str | None = None) -> LoadedSkill:
        """Load one complete skill as untrusted data, without loading references."""
        source, name = _selector(selector)
        if expected_version is not None and (type(expected_version) is not str
                or re.fullmatch(r'[0-9a-f]{64}', expected_version) is None):
            raise SkillError('invalid expected skill version', code='SKILL_VERSION')
        discovery = self.discover()
        matches = [item for item in discovery.skills if item.name == name and (source is None or item.source == source)]
        if not matches:
            raise SkillError(f'skill was not discovered: {selector}', code='SKILL_NOT_FOUND')
        if len(matches) != 1:
            raise SkillError(f'ambiguous skill name; select a source: {selector}', code='SKILL_CONFLICT')
        metadata = matches[0]
        if not metadata.enabled:
            raise SkillError(f'skill is disabled: {metadata.selector}', code='SKILL_DISABLED')
        try:
            with _directory(self._roots[metadata.source], required=True) as root:
                with _skill_file(root, name) as fd:
                    before = _signature(fd)
                    _, _, digest = _header(fd, name)
                    if digest != metadata.metadata_sha256:
                        raise SkillError('skill metadata changed before loading', code='SKILL_CHANGED')
                    os.lseek(fd, 0, os.SEEK_SET)
                    raw = _bounded(fd, MAX_SKILL_BYTES)
                    if _signature(fd) != before:
                        raise SkillError('skill changed while loading', code='SKILL_CHANGED')
        except SkillError:
            raise
        except (OSError, ValueError) as error:
            raise SkillError('skill file is unsafe or unavailable', code='SKILL_PATH') from error
        version = hashlib.sha256(raw).hexdigest()
        if expected_version is not None and version != expected_version:
            raise SkillError('skill content version does not match expected version', code='SKILL_VERSION')
        try:
            content = raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise SkillError('skill body must be UTF-8', code='SKILL_UTF8') from error
        return LoadedSkill(metadata, content, version)
