"""Project lint rules: one per defect that a syntactic pattern can catch again.

Each rule names the defect it came from. A defect that no syntactic pattern can
catch gets a regression test instead. Run: `.venv/bin/python scripts/lint_rules.py`;
`tests/test_lint_rules.py` runs the same rules in the suite.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    origin: str
    check: Callable[[Path], Iterator[Violation]]


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _formula_fit_calls(tree: ast.AST) -> Iterator[tuple[ast.Call, str | None]]:
    enclosing: list[str] = []

    def visit(node: ast.AST) -> Iterator[tuple[ast.Call, str | None]]:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            enclosing.append(node.name)
            for child in ast.iter_child_nodes(node):
                yield from visit(child)
            enclosing.pop()
            return
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"ols", "wls"} and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "smf"):
            yield node, enclosing[-1] if enclosing else None
        for child in ast.iter_child_nodes(node):
            yield from visit(child)

    yield from visit(tree)


def ols_fits_go_through_the_omission_path(root: Path) -> Iterator[Violation]:
    runner = root / "backend/workbench/econometrics/runner.py"
    for call, function in _formula_fit_calls(ast.parse(runner.read_text(encoding="utf-8"))):
        if function != "_fit_ols_formula":
            yield Violation("ols-fit-through-omission", _relative(runner, root), call.lineno,
                            "fit OLS/WLS through _fit_ols_formula, so a rank-deficient design omits its "
                            "unidentified terms instead of reporting pseudo-inverse numbers")


def gitignore_names_node_modules_without_a_trailing_slash(root: Path) -> Iterator[Violation]:
    gitignore = root / ".gitignore"
    for number, line in enumerate(gitignore.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip() in {"node_modules/", "/node_modules/"}:
            yield Violation("gitignore-node-modules-symlink", _relative(gitignore, root), number,
                            "write node_modules without a trailing slash: the slash matches only directories, "
                            "so the symlinked node_modules in worktrees is not ignored")


def ols_calls_pass_a_dataset_snapshot(root: Path) -> Iterator[Violation]:
    for path in sorted((root / "backend").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
            if name == "run_ols" and not any(keyword.arg == "dataset_snapshot" for keyword in node.keywords):
                yield Violation("ols-call-dataset-snapshot", _relative(path, root), node.lineno,
                                "pass dataset_snapshot to run_ols: without it the fit fingerprints every cell of the "
                                "whole frame, unused columns included")


def _is_splitlines(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "splitlines"


def _splits_lines(node: ast.AST, split_names: set[str]) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "enumerate" and node.args:
        node = node.args[0]
    return _is_splitlines(node) or (isinstance(node, ast.Name) and node.id in split_names)


def _loads_json(node: ast.AST) -> bool:
    return any(isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "loads"
               and isinstance(call.func.value, ast.Name) and call.func.value.id == "json"
               for call in ast.walk(node))


def splitlines_jsonl_readers(tree: ast.AST) -> Iterator[ast.AST]:
    """Loops and comprehensions that ``json.loads`` items of a ``.splitlines()`` result."""
    # ``lines = text.splitlines()`` and a later loop over ``lines`` count too.
    split_names = {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign) and _is_splitlines(node.value)
                   for target in node.targets if isinstance(target, ast.Name)}
    for node in ast.walk(tree):
        if (isinstance(node, ast.For) and _splits_lines(node.iter, split_names)
                and any(_loads_json(item) for item in node.body)):
            yield node
        elif isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.SetComp, ast.DictComp)):
            if any(_splits_lines(generator.iter, split_names) for generator in node.generators) and _loads_json(node):
                yield node


#: AGENTS.md: scripts/devline_memory.py is legacy migration evidence, not to be rewritten.
_JSONL_RULE_EXEMPT = frozenset({"scripts/devline_memory.py"})


def jsonl_is_split_at_newlines_only(root: Path) -> Iterator[Violation]:
    for folder in ("backend", "scripts"):
        for path in sorted((root / folder).rglob("*.py")):
            if _relative(path, root) in _JSONL_RULE_EXEMPT:
                continue
            for node in splitlines_jsonl_readers(ast.parse(path.read_text(encoding="utf-8"))):
                yield Violation("jsonl-split-at-newline", _relative(path, root), node.lineno,
                                "split JSON Lines with workbench.jsonl_store.jsonl_lines, not str.splitlines(): "
                                "it also splits at U+2028/U+2029/U+0085, which json.dumps(ensure_ascii=False) "
                                "leaves raw inside strings")


#: The one reader that derives the set, and the archive tool that packs results saved before v1.9.1.
_ROW_SET_READERS = frozenset({"backend/workbench/econometrics/ols_contract.py", "scripts/pack_ols_result.py"})


def _reads_row_set(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value == "row_set"
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
            and bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value == "row_set")


def analysis_sample_row_set_is_derived(root: Path) -> Iterator[Violation]:
    for folder in ("backend", "scripts"):
        for path in sorted((root / folder).rglob("*.py")):
            if _relative(path, root) in _ROW_SET_READERS:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if _reads_row_set(node):
                    yield Violation("analysis-sample-row-set-derived", _relative(path, root), node.lineno,
                                    "read the analysis rows through ols_contract.analysis_sample_row_set: results "
                                    "written since v1.9.1 store only row_order")


# Where a formula-free model is tried first and the formula is the fallback.
_FORMULA_FALLBACKS = frozenset({("backend/workbench/econometrics/panel_design.py", "panel_ols_model"),
                                ("backend/workbench/econometrics/panel_iv.py", "run_iv_2sls")})


def _linearmodels_formula_calls(tree: ast.AST) -> Iterator[tuple[ast.Call, str | None]]:
    enclosing: list[str] = []

    def visit(node: ast.AST) -> Iterator[tuple[ast.Call, str | None]]:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            enclosing.append(node.name)
            for child in ast.iter_child_nodes(node):
                yield from visit(child)
            enclosing.pop()
            return
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "from_formula"
                and isinstance(node.func.value, (ast.Attribute, ast.Name))
                and getattr(node.func.value, "attr", getattr(node.func.value, "id", "")) in {"PanelOLS", "IV2SLS"}):
            yield node, enclosing[-1] if enclosing else None
        for child in ast.iter_child_nodes(node):
            yield from visit(child)

    yield from visit(tree)


def linearmodels_fits_skip_formulaic_when_they_can(root: Path) -> Iterator[Violation]:
    for path in sorted((root / "backend/workbench/econometrics").rglob("*.py")):
        relative = _relative(path, root)
        for call, function in _linearmodels_formula_calls(ast.parse(path.read_text(encoding="utf-8"))):
            if (relative, function) not in _FORMULA_FALLBACKS:
                yield Violation("linearmodels-formula-fallback-only", relative, call.lineno,
                                "build PanelOLS through panel_design.panel_ols_model and IV2SLS through the "
                                "formula-free branch of run_iv_2sls; formulaic leaves a copy of the data in "
                                "reference cycles")


@dataclass(frozen=True)
class RestrictedImport:
    """One cross-layer boundary, written like ESLint's ``no-restricted-imports``.

    ``message`` says which public interface to use instead, so the error is the fix.
    """
    files: str
    module: str
    allow: tuple[str, ...]
    message: str
    origin: str


RESTRICTED_IMPORTS: tuple[RestrictedImport, ...] = (
    RestrictedImport(
        files="backend/workbench/agent/", module="workbench.llm.client",
        allow=("backend/workbench/agent/model.py",),
        message="import provider names (LLMRequestBudgetExceeded, LLMUpstreamError, ...) from workbench.agent.model, "
                "the agent layer's provider adapter; only agent/model.py imports workbench.llm.client",
        origin="fa70e117 (2026-11-13): agent/step_observation.py imported LLMRequestBudgetExceeded from llm.client "
               "while turn_loop imported the same class from agent.model"),
)


def _module_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root / "backend").with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _import_from_module(node: ast.ImportFrom, package: str) -> str:
    if not node.level:
        return node.module or ""
    parts = package.split(".")
    base = parts[:len(parts) - (node.level - 1)]
    return ".".join(base + ([node.module] if node.module else []))


def _imported_modules(tree: ast.AST, module: str, is_package: bool) -> Iterator[tuple[int, str]]:
    package = module if is_package else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            source = _import_from_module(node, package)
            yield node.lineno, source
            for alias in node.names:
                yield node.lineno, f"{source}.{alias.name}"


def imports_respect_layer_boundaries(root: Path) -> Iterator[Violation]:
    for boundary in RESTRICTED_IMPORTS:
        for path in sorted((root / boundary.files).rglob("*.py")):
            relative = _relative(path, root)
            if relative in boundary.allow:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            seen = set()
            for line, name in _imported_modules(tree, _module_name(path, root), path.name == "__init__.py"):
                if (name == boundary.module or name.startswith(boundary.module + ".")) and line not in seen:
                    seen.add(line)
                    yield Violation("restricted-imports", relative, line,
                                    f"{boundary.module} is not imported here: {boundary.message}")


_CONTEXT_FILE_READERS = {
    "artifacts_index.json": "read_context_artifact_index",
    "data_profile.json": "read_context_data_profile",
    "run_manifest.json": "read_context_run_manifest",
}


def agent_context_run_files_use_the_compiler(root: Path) -> Iterator[Violation]:
    folder = root / "backend/workbench/agent/context_tools_support"
    for path in sorted(folder.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            filename = Path(node.value).name
            if (reader := _CONTEXT_FILE_READERS.get(filename)) is not None:
                message = f"read {filename} through workbench.agent.context_compiler.{reader}"
                if filename == "artifacts_index.json":
                    message += "; use has_context_artifact_index to test index presence before a legacy fallback"
                yield Violation(
                    "agent-context-run-file-owner", _relative(path, root), node.lineno,
                    message,
                )


def _scope_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    for node in ast.iter_child_nodes(scope):
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _scope_nodes(node)


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute) and (base := _dotted_name(node.value)):
        return f"{base}.{node.attr}"
    return ""


def _absolute_imports(nodes: list[ast.AST]) -> dict[str, str]:
    imports = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                imports[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                imports[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return imports


# The retention helper owns its call. Existing workers accept a fresh output root.
_PERF_PROJECT_FACTORIES = {
    "perf_1m.py": "family_run",
    "perf_agent_turn_replay.py": "run",
    "perf_evidence.py": "create_active_project",
    "perf_fast_iv_cancel.py": "worker",
    "perf_native_io.py": "worker",
}


def _performance_project_calls(scope: ast.AST, inherited_imports: dict[str, str]) -> Iterator[tuple[ast.AST, int]]:
    nodes = list(_scope_nodes(scope))
    imports = inherited_imports | _absolute_imports(nodes)
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _performance_project_calls(node, imports)
        if isinstance(node, ast.Call):
            alias, _, rest = _dotted_name(node.func).partition(".")
            target = ".".join(part for part in (imports.get(alias, ""), rest) if part)
            if target == "workbench.projects.create_project":
                yield scope, node.lineno


def performance_projects_use_retention_owner(root: Path) -> Iterator[Violation]:
    for path in sorted((root / "scripts").glob("perf_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner = _PERF_PROJECT_FACTORIES.get(path.name)
        for scope, line in _performance_project_calls(tree, {}):
            if isinstance(scope, ast.FunctionDef) and scope in tree.body and scope.name == owner:
                owner = None  # One existing creation call per owner.
                continue
            yield Violation(
                "perf-project-retention-owner", _relative(path, root), line,
                "Create projects through perf_evidence.create_active_project in one campaign active tree. "
                "Keep worker logs with perf_evidence.retain_worker_logs and call perf_evidence.finalize_active "
                "to verify and journal each observation before starting another.",
            )


def _monkeypatch_stubs(scope, inherited_imports, inherited_stubs):
    nodes = list(_scope_nodes(scope))
    imports = inherited_imports | _absolute_imports(nodes)
    stubs = inherited_stubs | {node.name: node.args for node in nodes
                              if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from _monkeypatch_stubs(node, imports, stubs)
        if not isinstance(node, ast.Call) or len(node.args) != 3 or _dotted_name(node.func) != "monkeypatch.setattr":
            continue
        owner, attribute, replacement = node.args
        if not isinstance(attribute, ast.Constant) or not isinstance(attribute.value, str):
            continue
        alias, _, rest = _dotted_name(owner).partition(".")
        module = ".".join(part for part in (imports.get(alias, ""), rest) if part)
        if not module.startswith("workbench."):
            continue
        stub = replacement.args if isinstance(replacement, ast.Lambda) else stubs.get(_dotted_name(replacement))
        if stub is not None:
            yield node.lineno, module, attribute.value, stub


def _positional_count(args: ast.arguments) -> int:
    return len(args.posonlyargs) + len(args.args)


def monkeypatch_stub_signatures_match(root: Path) -> Iterator[Violation]:
    @cache
    def functions(module: str) -> dict[str, ast.arguments]:
        base = root / "backend" / Path(*module.split("."))
        for path in (base.with_suffix(".py"), base / "__init__.py"):
            if path.is_file():
                tree = ast.parse(path.read_text(encoding="utf-8"))
                return {node.name: node.args for node in _scope_nodes(tree)
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        return {}

    for path in sorted((root / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, module, name, stub in _monkeypatch_stubs(tree, {}, {}):
            target = functions(module).get(name)
            if target is None or stub.vararg is not None or target.vararg is not None:
                continue
            actual, expected = _positional_count(stub), _positional_count(target)
            if actual != expected:
                yield Violation("monkeypatch-stub-signature", _relative(path, root), line,
                                f"match the signature of {module}.{name}: the replacement has {actual} "
                                f"positional parameters, but the function declares {expected}")


_PRIVATE_IMPORT_BASELINE = "scripts/lint_baselines/private_imports.json"


def _private_import_occurrences(root: Path) -> Iterator[tuple[str, int, str, str]]:
    for path in sorted((root / "backend/workbench").rglob("*.py")):
        module = _module_name(path, root)
        source_layer = module.split(".")[1:2]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, qualified in _imported_modules(tree, module, path.name == "__init__.py"):
            imported_from, _, name = qualified.rpartition(".")
            if (qualified.startswith("workbench.") and qualified.split(".")[1:2] != source_layer
                    and name.startswith("_") and not name.startswith("__")):
                yield _relative(path, root), line, qualified, imported_from


def _private_import_baseline_increases(root: Path, baseline: dict) -> Iterator[str]:
    if not (root / ".git").exists():
        return
    commits = subprocess.check_output(
        ["git", "log", "-2", "--format=%H", "--", _PRIVATE_IMPORT_BASELINE], cwd=root, text=True,
    ).split()
    for commit in commits:
        previous = json.loads(subprocess.check_output(
            ["git", "show", f"{commit}:{_PRIVATE_IMPORT_BASELINE}"], cwd=root, text=True,
        ))
        for path, imports in baseline.items():
            for name, count in imports.items():
                if count > previous.get(path, {}).get(name, 0):
                    yield f"{path} imports {name}"


def private_cross_package_imports_stay_in_baseline(root: Path) -> Iterator[Violation]:
    path = root / _PRIVATE_IMPORT_BASELINE
    baseline = json.loads(path.read_text(encoding="utf-8"))
    for entry in sorted(set(_private_import_baseline_increases(root, baseline))):
        yield Violation("private-cross-package-imports", _PRIVATE_IMPORT_BASELINE, 1,
                        f"the baseline can only shrink ({entry}); export and use a public name")
    seen: Counter[tuple[str, str]] = Counter()
    for caller, line, qualified, module in _private_import_occurrences(root):
        key = (caller, qualified)
        seen[key] += 1
        if seen[key] > baseline.get(caller, {}).get(qualified, 0):
            yield Violation("private-cross-package-imports", caller, line,
                            f"{qualified} is private; export a public name from {module} and import it")


_AGENTS_MD_SHA256 = "971efa74629430dadad299f59778f0e5fbd995382dea2911b3a3eb7aca366d13"


def agents_md_is_pinned(root: Path) -> Iterator[Violation]:
    path = root / "AGENTS.md"
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != _AGENTS_MD_SHA256:
        yield Violation("agents-md-pinned", "AGENTS.md", 1,
                        "encode lessons as lint rules or tests; AGENTS.md changes require user approval "
                        "and an update to the pinned hash")


RULES: tuple[Rule, ...] = (
    Rule("ols-fit-through-omission",
         "QRData 355 (6af0a0da round): a constant column was reported as an effect of 0.00 with standard error 0",
         ols_fits_go_through_the_omission_path),
    Rule("ols-call-dataset-snapshot",
         "v1.9.1 memory scan: the Agent's post-estimation refit and the auto-to-OLS fallback hashed every cell; "
         "1M rows with 30 unused columns added 1.6 GB and 31 s",
         ols_calls_pass_a_dataset_snapshot),
    Rule("gitignore-node-modules-symlink",
         "v1.6.5: node_modules/ in .gitignore missed the worktree symlinks and one merge broke every worktree",
         gitignore_names_node_modules_without_a_trailing_slash),
    Rule("jsonl-split-at-newline",
         "v1.9.1 agent pipeline (2026-11-03): one U+2028 in a message made a whole session log unreadable; "
         "21 more readers had the same split",
         jsonl_is_split_at_newlines_only),
    Rule("analysis-sample-row-set-derived",
         "v1.9.1 native-io merge (2026-11-06): development-build OLS results stored no analysis_sample.row_set "
         "(restored 2026-11-09 for v1.9.0 bytes); a direct reader gets nothing from those results",
         analysis_sample_row_set_is_derived),
    Rule("linearmodels-formula-fallback-only",
         "v1.9.1 footprint gate (2026-11-09): every PanelOLS/IV2SLS formula fit left formulaic's copy of the "
         "data in reference cycles (about 300 MiB for the 1M-row DID event study)",
         linearmodels_fits_skip_formulaic_when_they_can),
    Rule("restricted-imports",
         "2026-11-17: cross-layer imports, one table entry per boundary (RESTRICTED_IMPORTS), each with its origin",
         imports_respect_layer_boundaries),
    Rule("agent-context-run-file-owner",
         "v1.9.1 C4 structural audit found context tools opening run indexes and data profiles directly",
         agent_context_run_files_use_the_compiler),
    Rule("monkeypatch-stub-signature",
         "9516c643 changed native_math._pair_ranks(matrix, ...) to (a, b, ...); the stale statistics stub raised TypeError",
         monkeypatch_stub_signatures_match),
    Rule("private-cross-package-imports",
         "2026-11-17 structure audit: http imported repository.run_repository._read_manifest across packages",
         private_cross_package_imports_stay_in_baseline),
    Rule("perf-project-retention-owner",
         "v1.9.1 storage review: interactive million-row budgets kept a full timestamped project per invocation, "
         "and offline Agent A/B replay retained a separate full project per observation",
         performance_projects_use_retention_owner),
    Rule("agents-md-pinned",
         "2026-11-17 user instruction: encode lessons as executable checks, with explicit approval for AGENTS.md changes",
         agents_md_is_pinned),
)


def run(root: Path = ROOT) -> list[Violation]:
    return [violation for rule in RULES for violation in rule.check(root)]


if __name__ == "__main__":
    found = run()
    for violation in found:
        print(violation)
    print(f"{len(RULES)} rules, {len(found)} violations")
    sys.exit(1 if found else 0)
