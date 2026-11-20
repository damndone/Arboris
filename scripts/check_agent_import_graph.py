"""Compare explicit eager dependencies with the v1.9.1 extraction baseline.

Run from the repository root. Function-local and TYPE_CHECKING imports are
excluded; fresh-process tests separately validate initialization. Extracted
owners are collapsed so moving code does not manufacture new legacy coupling.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess


OWNERS = {
    'workbench.agent.planning': 'workbench.agent.notebook.planning_agent',
    'workbench.agent.workflow_contract_parts': 'workbench.agent.workflow_contracts',
    'workbench.agent.workflow_runtime_parts': 'workbench.agent.workflow_runtime',
    'workbench.agent.notebook.execution_results': 'workbench.agent.notebook.service',
    'workbench.agent.protocol': 'workbench.http.agent_routes',
    'workbench.agent.turn_runtime': 'workbench.http.agent_routes',
    'workbench.agent.operation_handlers': 'workbench.agent.orchestrator',
    'workbench.agent.toolsets': 'workbench.agent.orchestrator',
    'workbench.agent.operation_requests': 'workbench.agent.orchestrator',
}


def baseline_sources(revision: str) -> tuple[str, dict[str, str]]:
    commit = subprocess.check_output(
        ['git', 'rev-parse', '--verify', '--end-of-options', revision + '^{commit}'], text=True,
    ).strip()
    paths = subprocess.check_output(
        ['git', 'ls-tree', '-r', '--name-only', commit, 'backend/workbench'], text=True,
    ).splitlines()
    paths = [path for path in paths if path.endswith('.py')]
    objects = subprocess.run(
        ['git', 'cat-file', '--batch'],
        input=''.join(commit + ':' + path + '\n' for path in paths).encode(),
        stdout=subprocess.PIPE, check=True,
    ).stdout
    sources = {}
    offset = 0
    for path in paths:
        end = objects.index(b'\n', offset)
        size = int(objects[offset:end].split()[-1])
        offset = end + 1
        sources[path] = objects[offset:offset + size].decode()
        offset += size + 1
    return commit, sources


def module_name(path: str) -> str:
    return path.removeprefix('backend/').removesuffix('.py').replace('/', '.').removesuffix('.__init__')


def eager_imports(body):
    for node in body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.If):
            if isinstance(node.test, ast.Name) and node.test.id == 'TYPE_CHECKING':
                continue
            if isinstance(node.test, ast.Attribute) and node.test.attr == 'TYPE_CHECKING':
                continue
            yield from eager_imports(node.body)
            yield from eager_imports(node.orelse)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            yield from eager_imports(node.body)
            yield from eager_imports(node.orelse)
            yield from eager_imports(node.finalbody)
            for handler in node.handlers:
                yield from eager_imports(handler.body)
        elif isinstance(node, (ast.With, ast.For, ast.While)):
            yield from eager_imports(node.body)
            yield from eager_imports(getattr(node, 'orelse', ()))


def dependency_graph(sources: dict[str, str]) -> dict[str, set[str]]:
    modules = {module_name(path) for path in sources}
    graph = {name: set() for name in modules}

    def module_target(name):
        while name and name not in modules:
            name = name.rpartition('.')[0]
        return name

    for path, source in sources.items():
        name = module_name(path)
        package = name if path.endswith('/__init__.py') else name.rpartition('.')[0]
        for node in eager_imports(ast.parse(source).body):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            else:
                package_parts = package.split('.')
                prefix = ('.'.join(package_parts[:len(package_parts) - node.level + 1]) + '.') if node.level else ''
                stem = (prefix + (node.module or '')).rstrip('.')
                targets = [stem, *(stem + '.' + alias.name for alias in node.names)]
            for target in targets:
                target = module_target(target)
                if target and target != name:
                    graph[name].add(target)
    return graph


def reachability(graph):
    reachable = {}
    for name, dependencies in graph.items():
        seen = set()
        stack = list(dependencies)
        while stack:
            dependency = stack.pop()
            if dependency in seen:
                continue
            seen.add(dependency)
            stack.extend(graph.get(dependency, ()))
        reachable[name] = seen
    return reachable


def original_owner(name):
    return next((owner for prefix, owner in OWNERS.items()
                 if name == prefix or name.startswith(prefix + '.')), name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='4abbeac0')
    parser.add_argument('--output', type=Path, default=Path('local/v191/m1-import-audit.json'))
    args = parser.parse_args()
    commit, baseline = baseline_sources(args.baseline)
    candidate = {str(path): path.read_text() for path in Path('backend/workbench').rglob('*.py')
                 if '__pycache__' not in path.parts}
    before, after = dependency_graph(baseline), dependency_graph(candidate)
    collapsed = {}
    for name, dependencies in after.items():
        owner = original_owner(name)
        collapsed.setdefault(owner, set()).update(
            original_owner(dependency) for dependency in dependencies if original_owner(dependency) != owner
        )
    old_reachable, new_reachable = reachability(before), reachability(collapsed)
    new_cycles = sorted(
        (left, right) for left in before for right in new_reachable.get(left, ())
        if right in before and left < right and left in new_reachable.get(right, ())
        and not (right in old_reachable.get(left, ()) and left in old_reachable.get(right, ()))
    )
    report = {
        'baseline': commit,
        'definition': 'Explicit eager AST imports, including conditional branches; excludes TYPE_CHECKING and function-local imports. Extracted owners collapsed; cold-import tests are separate.',
        'candidate_source_sha256': hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest(),
        'baseline_modules': len(before), 'candidate_modules': len(after),
        'baseline_edges': sum(map(len, before.values())), 'candidate_edges': sum(map(len, after.values())),
        'new_mutually_dependent_original_pairs': new_cycles, 'owner_mapping': OWNERS,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key not in {'owner_mapping', 'definition'}}))
    return 1 if new_cycles else 0


if __name__ == '__main__':
    raise SystemExit(main())
