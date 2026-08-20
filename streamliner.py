# SPDX-License-Identifier: SSPL-1.0
# Copyright (c) 2026 Supe232323
#!/usr/bin/env python3
"""PyStreamliner — A conservative, zero-dependency Python source code cleaner.
Two-tier model:
  Tier 1 (Auto-fix): Provably safe modifications only.
  Tier 2 (Warn-only): Detection + report, zero modification.
Supports single files, multiple files, recursive directory cleaning,
and parallel processing via --jobs.
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import difflib
import json
import os
import re
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# ─── ANSI Color Constants ────────────────────────────────────────────────────
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"

# ─── Constants ────────────────────────────────────────────────────────────────
MAX_CONSECUTIVE_BLANKS = 2
MAX_CONSECUTIVE_BLANKS_AGGRESSIVE = 1
SUMMARY_THRESHOLD = 5  # switch to tight summary when processing this many files or more

IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", "__pycache__", "venv", ".venv", "env", ".env",
    "node_modules", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "eggs", ".eggs", ".idea",
    ".vscode", "htmlcov", "coverage",
})

VAGUE_NAMES: frozenset[str] = frozenset({
    "x", "y", "z", "temp", "tmp", "foo", "bar", "baz",
    "a", "b", "c", "d", "e", "f",
})

# ─── Data Structures ─────────────────────────────────────────────────────────
@dataclasses.dataclass
class ImportFinding:
    lineno: int
    end_lineno: int
    original_text: str
    bound_names: list[str]
    unused_names: list[str]
    used_names: list[str]
    is_from_import: bool
    indent: str
    module: str | None = None

@dataclasses.dataclass
class Warning:
    category: str
    name: str
    lineno: int
    message: str

@dataclasses.dataclass
class AnalysisResult:
    unused_imports: list[ImportFinding]
    warnings: list[Warning]
    all_names_in_all: set[str]

@dataclasses.dataclass
class CleaningStats:
    unused_imports_removed: int = 0
    duplicate_lines_removed: int = 0
    blank_lines_reduced: int = 0

@dataclasses.dataclass
class ImportDetail:
    lineno: int
    text: str

@dataclasses.dataclass
class FileResult:
    path: Path
    lines_analyzed: int
    stats: CleaningStats
    warnings: list[Warning]
    import_details: list[ImportDetail]
    had_changes: bool
    original_source: str
    cleaned_source: str
    error: str | None = None

# ─── Helpers ──────────────────────────────────────────────────────────────────
def _build_parent_map(tree: ast.AST) -> dict[int, ast.AST]:
    parent_map: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[id(child)] = node
    return parent_map

def _parse_exclude(exclude: str | None) -> set[int]:
    if not exclude:
        return set()
    lines: set[int] = set()
    for part in exclude.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s), int(end_s)
                lines.update(range(start, end + 1))
            except ValueError:
                continue
        else:
            try:
                lines.add(int(part))
            except ValueError:
                continue
    return lines

def _filter_warnings(
    warnings: list[Warning],
    select: str | None,
    ignore: str | None,
    excluded_lines: set[int],
) -> list[Warning]:
    selected = {s.strip() for s in select.split(",")} if select else None
    ignored = {i.strip() for i in ignore.split(",")} if ignore else set()
    result: list[Warning] = []
    for w in warnings:
        if w.lineno in excluded_lines:
            continue
        if selected is not None and w.category not in selected:
            continue
        if w.category in ignored:
            continue
        result.append(w)
    return result

def _collect_python_files(paths: list[Path]) -> list[Path]:
    """Collect all .py files from given paths (files or directories)."""
    files: list[Path] = []
    seen: set[Path] = set()

    def should_skip_dir(name: str) -> bool:
        return name in IGNORE_DIRS or name.endswith(".egg-info")

    for path in paths:
        path = path.resolve()
        if not path.exists():
            sys.stderr.write(f"Warning: path not found, skipping: {path}\n")
            continue
        if path.is_file():
            if path.suffix == ".py" and path not in seen:
                files.append(path)
                seen.add(path)
        elif path.is_dir():
            for p in path.rglob("*.py"):
                if any(should_skip_dir(part) for part in p.parts):
                    continue
                if p not in seen:
                    files.append(p)
                    seen.add(p)
    return sorted(files)

# ─── SourceAnalyzer ───────────────────────────────────────────────────────────
class SourceAnalyzer:
    def __init__(self, source: str, filename: str) -> None:
        self._source = source
        self._filename = filename
        self._tree = ast.parse(source, filename=filename)
        self._lines = source.splitlines(True)
        self._used_names: set[str] | None = None
        self._all_names: set[str] = set()
        self._parent_map: dict[int, ast.AST] = _build_parent_map(self._tree)

    def analyze(self) -> AnalysisResult:
        self._used_names = self._collect_all_used_names()
        self._collect_all_list_names()
        unused_imports = self._find_unused_imports()
        warnings: list[Warning] = []
        warnings.extend(self._find_unused_variables())
        warnings.extend(self._find_unused_functions())
        warnings.extend(self._find_unused_classes())
        warnings.extend(self._find_vague_names())
        warnings.extend(self._find_shadowed_builtins())
        warnings.extend(self._find_dangerous_calls())
        warnings.extend(self._find_hardcoded_secrets())
        warnings.extend(self._find_assert_used())
        warnings.extend(self._find_broad_excepts())
        return AnalysisResult(
            unused_imports=unused_imports,
            warnings=warnings,
            all_names_in_all=self._all_names,
        )

    def _collect_all_used_names(self) -> set[str]:
        """Collect names that appear to be used (Load context + attribute names)."""
        names: set[str] = set()
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                # Record the attribute name itself so methods / attr access count as used
                names.add(node.attr)
                # Also record the root if it is a simple Name
                if isinstance(node.value, ast.Name):
                    names.add(node.value.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                candidate = node.value.strip()
                if candidate.isidentifier():
                    names.add(candidate)
        return names

    def _collect_all_list_names(self) -> None:
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                self._all_names.add(elt.value)

    def _find_unused_imports(self) -> list[ImportFinding]:
        assert self._used_names is not None
        findings: list[ImportFinding] = []
        for node in ast.iter_child_nodes(self._tree):
            if isinstance(node, ast.Import):
                result = self._check_import(node)
                if result is not None:
                    findings.append(result)
            elif isinstance(node, ast.ImportFrom):
                result = self._check_from_import(node)
                if result is not None:
                    findings.append(result)
        return findings

    def _check_import(self, node: ast.Import) -> ImportFinding | None:
        assert self._used_names is not None
        line_text = self._get_line_text(node.lineno)
        indent = self._get_indent(line_text)
        end_lineno = getattr(node, "end_lineno", node.lineno) or node.lineno
        if end_lineno > node.lineno:
            original_text = "".join(self._lines[node.lineno - 1:end_lineno]).rstrip()
        else:
            original_text = line_text.rstrip()

        bound_names: list[str] = []
        unused: list[str] = []
        used: list[str] = []
        for alias in node.names:
            bound = alias.asname if alias.asname else alias.name.split(".")[0]
            bound_names.append(bound)
            if bound in self._used_names or bound in self._all_names:
                if alias.asname:
                    used.append(f"{alias.name} as {alias.asname}")
                else:
                    used.append(alias.name)
            else:
                unused.append(bound)
        if not unused:
            return None
        return ImportFinding(
            lineno=node.lineno,
            end_lineno=end_lineno,
            original_text=original_text,
            bound_names=bound_names,
            unused_names=unused,
            used_names=used,
            is_from_import=False,
            indent=indent,
        )

    def _check_from_import(self, node: ast.ImportFrom) -> ImportFinding | None:
        assert self._used_names is not None
        if node.module == "__future__":
            return None
        if any(alias.name == "*" for alias in node.names):
            return None
        line_text = self._get_line_text(node.lineno)
        indent = self._get_indent(line_text)
        end_lineno = getattr(node, "end_lineno", node.lineno) or node.lineno
        if end_lineno > node.lineno:
            original_text = "".join(self._lines[node.lineno - 1:end_lineno]).rstrip()
        else:
            original_text = line_text.rstrip()
        bound_names: list[str] = []
        unused: list[str] = []
        used: list[str] = []
        for alias in node.names:
            bound = alias.asname if alias.asname else alias.name
            bound_names.append(bound)
            if bound in self._used_names or bound in self._all_names:
                used.append(alias.name if not alias.asname else f"{alias.name} as {alias.asname}")
            else:
                unused.append(bound)
        if not unused:
            return None
        return ImportFinding(
            lineno=node.lineno,
            end_lineno=end_lineno,
            original_text=original_text,
            bound_names=bound_names,
            unused_names=unused,
            used_names=used,
            is_from_import=True,
            indent=indent,
            module=node.module,
        )

    def _find_unused_variables(self) -> list[Warning]:
        assert self._used_names is not None
        warnings: list[Warning] = []
        for name, lineno in self._collect_assigned_names():
            if name == "_" or (name.startswith("__") and name.endswith("__")):
                continue
            if name in self._all_names or name in self._used_names:
                continue
            warnings.append(Warning(
                category="unused_variable",
                name=name,
                lineno=lineno,
                message=f"⚠ Unused variable '{name}' at line {lineno}",
            ))
        return warnings

    def _collect_assigned_names(self) -> list[tuple[str, int]]:
        assigned: list[tuple[str, int]] = []
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    self._extract_names_from_target(target, assigned)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                self._extract_names_from_target(node.target, assigned)
            elif isinstance(node, ast.For):
                self._extract_names_from_target(node.target, assigned)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if item.optional_vars:
                        self._extract_names_from_target(item.optional_vars, assigned)
            elif isinstance(node, ast.NamedExpr):
                self._extract_names_from_target(node.target, assigned)
        return assigned

    def _extract_names_from_target(self, target: ast.expr, result: list[tuple[str, int]]) -> None:
        if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
            result.append((target.id, target.lineno))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._extract_names_from_target(elt, result)

    def _find_unused_functions(self) -> list[Warning]:
        assert self._used_names is not None
        warnings: list[Warning] = []
        for node in ast.walk(self._tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if name == "main" or node.decorator_list or (name.startswith("__") and name.endswith("__")):
                continue
            if name in self._used_names or name in self._all_names:
                continue
            if self._is_inside_name_main_block(node):
                continue
            parent = self._parent_map.get(id(node))
            kind = "method" if isinstance(parent, ast.ClassDef) else "function"
            warnings.append(Warning(
                category="unused_function",
                name=name,
                lineno=node.lineno,
                message=f"⚠ Unused {kind} '{name}()' at line {node.lineno}",
            ))
        return warnings

    def _find_unused_classes(self) -> list[Warning]:
        """Detect classes that appear unused (conservative)."""
        assert self._used_names is not None
        warnings: list[Warning] = []
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = node.name
            if name.startswith("__") and name.endswith("__"):
                continue
            if name in self._used_names or name in self._all_names:
                continue
            if self._is_inside_name_main_block(node):
                continue
            # Skip decorated classes (dataclasses, attrs, etc. are commonly "used" by framework)
            if node.decorator_list:
                continue
            warnings.append(Warning(
                category="unused_class",
                name=name,
                lineno=node.lineno,
                message=f"⚠ Unused class '{name}' at line {node.lineno}",
            ))
        return warnings

    def _is_inside_name_main_block(self, node: ast.AST) -> bool:
        for top in ast.iter_child_nodes(self._tree):
            if not isinstance(top, ast.If):
                continue
            test = top.test
            if (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"):
                for child in ast.walk(top):
                    if child is node:
                        return True
        return False

    def _find_vague_names(self) -> list[Warning]:
        warnings: list[Warning] = []
        seen: set[tuple[str, int]] = set()
        for name, lineno in self._collect_assigned_names():
            if (name, lineno) in seen:
                continue
            seen.add((name, lineno))
            if self._is_in_comprehension_or_lambda(name, lineno):
                continue
            if name.lower() in VAGUE_NAMES:
                warnings.append(Warning(
                    category="vague_name",
                    name=name,
                    lineno=lineno,
                    message=f"⚠ Vague variable name '{name}' at line {lineno}",
                ))
        return warnings

    def _is_in_comprehension_or_lambda(self, name: str, lineno: int) -> bool:
        comp_types = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Lambda)
        for node in ast.walk(self._tree):
            if (isinstance(node, ast.Name)
                    and node.id == name
                    and node.lineno == lineno
                    and isinstance(node.ctx, ast.Store)):
                current: ast.AST = node
                while True:
                    parent = self._parent_map.get(id(current))
                    if parent is None:
                        break
                    if isinstance(parent, comp_types):
                        return True
                    current = parent
        return False

    def _find_shadowed_builtins(self) -> list[Warning]:
        SHADOWED = frozenset({
            "id", "type", "list", "dict", "set", "tuple", "str", "int",
            "float", "bool", "input", "open", "range", "len", "map",
            "filter", "sum", "min", "max", "next", "iter", "hash",
            "format", "print", "object", "bytes", "complex", "frozenset",
            "property", "staticmethod", "classmethod", "super",
        })
        warnings: list[Warning] = []
        seen: set[tuple[str, int]] = set()
        for name, lineno in self._collect_assigned_names():
            if (name, lineno) in seen:
                continue
            seen.add((name, lineno))
            if name in SHADOWED:
                warnings.append(Warning(
                    category="shadowed_builtin",
                    name=name,
                    lineno=lineno,
                    message=f"⚠ Variable '{name}' shadows a built-in at line {lineno}",
                ))
        return warnings

    def _find_dangerous_calls(self) -> list[Warning]:
        warnings: list[Warning] = []
        DANGEROUS_NAMES = frozenset({"eval", "exec", "compile"})
        PICKLE_FUNCS = frozenset({"loads", "load", "dumps", "dump"})
        OS_DANGEROUS = frozenset({"system", "popen", "popen2", "popen3", "popen4"})
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in DANGEROUS_NAMES:
                warnings.append(Warning(
                    category="dangerous_call",
                    name=node.func.id,
                    lineno=node.lineno,
                    message=f"⚠ Dangerous call '{node.func.id}()' at line {node.lineno}",
                ))
                continue
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if isinstance(node.func.value, ast.Name):
                    mod = node.func.value.id
                    if mod in {"pickle", "marshal", "shelve"} and attr in PICKLE_FUNCS:
                        warnings.append(Warning(
                            category="dangerous_call",
                            name=f"{mod}.{attr}",
                            lineno=node.lineno,
                            message=f"⚠ Dangerous call '{mod}.{attr}()' at line {node.lineno}",
                        ))
                        continue
                    if mod == "os" and attr in OS_DANGEROUS:
                        warnings.append(Warning(
                            category="dangerous_call",
                            name=f"os.{attr}",
                            lineno=node.lineno,
                            message=f"⚠ Dangerous call 'os.{attr}()' at line {node.lineno}",
                        ))
                        continue
                    if mod == "yaml" and attr == "load":
                        has_safe = False
                        for kw in node.keywords:
                            if kw.arg in {"Loader", "loader"} and isinstance(kw.value, ast.Attribute):
                                if kw.value.attr in {"SafeLoader", "CSafeLoader"}:
                                    has_safe = True
                        if not has_safe:
                            warnings.append(Warning(
                                category="dangerous_call",
                                name="yaml.load",
                                lineno=node.lineno,
                                message=f"⚠ Dangerous call 'yaml.load()' without SafeLoader at line {node.lineno}",
                            ))
                        continue
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                    for kw in node.keywords:
                        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            warnings.append(Warning(
                                category="dangerous_call",
                                name=f"subprocess.{attr}",
                                lineno=node.lineno,
                                message=f"⚠ subprocess.{attr}() called with shell=True at line {node.lineno}",
                            ))
                            break
                if isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name):
                    if node.func.value.value.id == "subprocess":
                        for kw in node.keywords:
                            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                warnings.append(Warning(
                                    category="dangerous_call",
                                    name="subprocess",
                                    lineno=node.lineno,
                                    message=f"⚠ subprocess call with shell=True at line {node.lineno}",
                                ))
                                break
        return warnings

    def _find_hardcoded_secrets(self) -> list[Warning]:
        SECRET_NAMES = frozenset({
            "password", "passwd", "pwd", "secret", "api_key", "apikey",
            "token", "access_token", "auth_token", "private_key", "secret_key",
            "client_secret", "aws_secret", "db_password",
        })
        warnings: list[Warning] = []
        seen: set[tuple[str, int]] = set()
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        name_lower = target.id.lower()
                        if name_lower in SECRET_NAMES or any(s in name_lower for s in ("password", "secret", "token", "api_key")):
                            key = (target.id, target.lineno)
                            if key not in seen:
                                seen.add(key)
                                warnings.append(Warning(
                                    category="hardcoded_secret",
                                    name=target.id,
                                    lineno=target.lineno,
                                    message=f"⚠ Possible hardcoded secret in '{target.id}' at line {target.lineno}",
                                ))
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                if isinstance(node.target, ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    name_lower = node.target.id.lower()
                    if name_lower in SECRET_NAMES or any(s in name_lower for s in ("password", "secret", "token", "api_key")):
                        key = (node.target.id, node.target.lineno)
                        if key not in seen:
                            seen.add(key)
                            warnings.append(Warning(
                                category="hardcoded_secret",
                                name=node.target.id,
                                lineno=node.target.lineno,
                                message=f"⚠ Possible hardcoded secret in '{node.target.id}' at line {node.target.lineno}",
                            ))
        return warnings

    def _find_assert_used(self) -> list[Warning]:
        warnings: list[Warning] = []
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Assert):
                warnings.append(Warning(
                    category="assert_used",
                    name="assert",
                    lineno=node.lineno,
                    message=f"⚠ assert used at line {node.lineno} (stripped with -O; do not use for security checks)",
                ))
        return warnings

    def _find_broad_excepts(self) -> list[Warning]:
        warnings: list[Warning] = []
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                warnings.append(Warning(
                    category="broad_except",
                    name="except:",
                    lineno=node.lineno,
                    message=f"⚠ Bare 'except:' at line {node.lineno}",
                ))
            elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                warnings.append(Warning(
                    category="broad_except",
                    name="except Exception",
                    lineno=node.lineno,
                    message=f"⚠ Broad 'except Exception' at line {node.lineno}",
                ))
        return warnings

    def _get_line_text(self, lineno: int) -> str:
        if 1 <= lineno <= len(self._lines):
            return self._lines[lineno - 1]
        return ""

    @staticmethod
    def _get_indent(line: str) -> str:
        match = re.match(r"^(\s*)", line)
        return match.group(1) if match else ""

# ─── SourceCleaner ────────────────────────────────────────────────────────────
class SourceCleaner:
    def __init__(
        self,
        lines: list[str],
        analysis: AnalysisResult,
        aggressive: bool = False,
        excluded_lines: set[int] | None = None,
    ) -> None:
        self._lines = list(lines)
        self._analysis = analysis
        self._stats = CleaningStats()
        self._import_details: list[ImportDetail] = []
        self._max_blanks = MAX_CONSECUTIVE_BLANKS_AGGRESSIVE if aggressive else MAX_CONSECUTIVE_BLANKS
        self._excluded = excluded_lines or set()

    def clean(self) -> tuple[list[str], CleaningStats, list[ImportDetail]]:
        self._remove_unused_imports()
        self._remove_duplicate_lines()
        self._reduce_blank_lines()
        self._ensure_trailing_newline()
        return self._lines, self._stats, self._import_details

    def _remove_unused_imports(self) -> None:
        lines_to_remove: set[int] = set()
        line_replacements: dict[int, str] = {}
        range_removals: list[tuple[int, int]] = []

        for imp in self._analysis.unused_imports:
            if imp.lineno in self._excluded:
                continue
            start_idx = imp.lineno - 1
            end_idx = imp.end_lineno - 1
            if start_idx < 0 or end_idx >= len(self._lines):
                continue
            is_multiline = end_idx > start_idx
            if not imp.used_names:
                if is_multiline:
                    range_removals.append((start_idx, end_idx))
                else:
                    lines_to_remove.add(start_idx)
                self._import_details.append(ImportDetail(lineno=imp.lineno, text=imp.original_text.strip()))
                self._stats.unused_imports_removed += len(imp.unused_names)
            else:
                if imp.is_from_import:
                    module = imp.module or ""
                    new_line = f"{imp.indent}from {module} import {', '.join(imp.used_names)}"
                else:
                    new_line = f"{imp.indent}import {', '.join(imp.used_names)}"
                last = self._lines[end_idx]
                if last.endswith("\r\n"):
                    new_line += "\r\n"
                elif last.endswith("\n"):
                    new_line += "\n"
                if is_multiline:
                    line_replacements[start_idx] = new_line
                    for idx in range(start_idx + 1, end_idx + 1):
                        lines_to_remove.add(idx)
                else:
                    line_replacements[start_idx] = new_line
                kept = ", ".join(f"'{n}'" for n in imp.used_names)
                self._import_details.append(ImportDetail(
                    lineno=imp.lineno,
                    text=f"{imp.original_text.strip()} (partially cleaned: kept {kept})",
                ))
                self._stats.unused_imports_removed += len(imp.unused_names)

        for start, end in range_removals:
            for idx in range(start, end + 1):
                lines_to_remove.add(idx)

        new_lines: list[str] = []
        for idx, line in enumerate(self._lines):
            if idx in lines_to_remove:
                continue
            new_lines.append(line_replacements.get(idx, line))
        self._lines = new_lines

    def _remove_duplicate_lines(self) -> None:
        if not self._lines:
            return
        result: list[str] = [self._lines[0]]
        for i in range(1, len(self._lines)):
            current = self._lines[i]
            if current.strip() == "":
                result.append(current)
                continue
            if current == self._lines[i - 1]:
                self._stats.duplicate_lines_removed += 1
                continue
            result.append(current)
        self._lines = result

    def _reduce_blank_lines(self) -> None:
        result: list[str] = []
        consecutive = 0
        for line in self._lines:
            if line.strip() == "":
                consecutive += 1
                if consecutive <= self._max_blanks:
                    result.append(line)
                else:
                    self._stats.blank_lines_reduced += 1
            else:
                consecutive = 0
                result.append(line)
        self._lines = result

    def _ensure_trailing_newline(self) -> None:
        if self._lines and not self._lines[-1].endswith("\n"):
            self._lines[-1] += "\n"

# ─── Report Printer ──────────────────────────────────────────────────────────
class ReportPrinter:
    BORDER_DOUBLE = "═" * 38
    BORDER_SINGLE = "─" * 38

    def __init__(
        self,
        filename: str,
        lines_analyzed: int,
        stats: CleaningStats,
        warnings: list[Warning],
        import_details: list[ImportDetail],
        use_color: bool = True,
    ) -> None:
        self._filename = filename
        self._lines_analyzed = lines_analyzed
        self._stats = stats
        self._warnings = warnings
        self._import_details = import_details
        self._use_color = use_color

    def _c(self, code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if self._use_color else text

    def print_report(self) -> None:
        unused_vars = [w for w in self._warnings if w.category == "unused_variable"]
        unused_funcs = [w for w in self._warnings if w.category == "unused_function"]
        unused_classes = [w for w in self._warnings if w.category == "unused_class"]
        vague_names = [w for w in self._warnings if w.category == "vague_name"]
        shadowed = [w for w in self._warnings if w.category == "shadowed_builtin"]
        dangerous = [w for w in self._warnings if w.category == "dangerous_call"]
        secrets = [w for w in self._warnings if w.category == "hardcoded_secret"]
        asserts = [w for w in self._warnings if w.category == "assert_used"]
        broad = [w for w in self._warnings if w.category == "broad_except"]
        print()
        print(self._c(CYAN, self.BORDER_DOUBLE))
        print(self._c(BOLD, " PyStreamliner Report"))
        print(self._c(CYAN, self.BORDER_DOUBLE))
        print(f" File: {self._c(BOLD, self._filename):>44s}")
        print(f" Lines analyzed: {self._lines_analyzed:>20d}")
        print()
        print(self._c(BOLD, " Auto-fixes applied:"))
        print(f" Unused imports removed: {self._stats.unused_imports_removed:>10d}")
        print(f" Duplicate lines removed: {self._stats.duplicate_lines_removed:>10d}")
        print(f" Blank lines reduced: {self._stats.blank_lines_reduced:>10d}")
        print()
        print(self._c(BOLD, " Warnings (manual review needed):"))
        print(f" Unused variables detected: {len(unused_vars):>8d}")
        print(f" Unused functions detected: {len(unused_funcs):>8d}")
        print(f" Unused classes detected: {len(unused_classes):>8d}")
        print(f" Vague variable names: {len(vague_names):>8d}")
        print(f" Shadowed built-ins: {len(shadowed):>8d}")
        print(f" Dangerous calls: {len(dangerous):>8d}")
        print(f" Possible hardcoded secrets: {len(secrets):>8d}")
        print(f" Assert statements: {len(asserts):>8d}")
        print(f" Broad except clauses: {len(broad):>8d}")
        print(self._c(CYAN, self.BORDER_SINGLE))
        if self._import_details:
            print()
            print(self._c(BOLD, " Unused imports removed:"))
            for d in self._import_details:
                print(f" • line {d.lineno}: {self._c(DIM, d.text)}")
        if unused_vars:
            print()
            print(self._c(BOLD, " Unused variables detected:"))
            for w in unused_vars:
                print(f" {self._c(YELLOW, '⚠')} line {w.lineno}: {w.name}")
        if unused_funcs:
            print()
            print(self._c(BOLD, " Unused functions detected:"))
            for w in unused_funcs:
                print(f" {self._c(YELLOW, '⚠')} line {w.lineno}: {w.name}()")
        if unused_classes:
            print()
            print(self._c(BOLD, " Unused classes detected:"))
            for w in unused_classes:
                print(f" {self._c(YELLOW, '⚠')} line {w.lineno}: {w.name}")
        if vague_names:
            print()
            print(self._c(BOLD, " Vague variable names:"))
            for w in vague_names:
                print(f" {self._c(YELLOW, '⚠')} line {w.lineno}: {w.name}")
        if shadowed:
            print()
            print(self._c(BOLD, " Shadowed built-in names:"))
            for w in shadowed:
                print(f" {self._c(YELLOW, '⚠')} line {w.lineno}: {w.name}")
        if dangerous:
            print()
            print(self._c(BOLD, " Dangerous calls:"))
            for w in dangerous:
                print(f" {self._c(YELLOW, '⚠')} line {w.lineno}: {w.message}")
        if secrets:
            print()
            print(self._c(BOLD, " Possible hardcoded secrets:"))
            for w in secrets:
                print(f" {self._c(YELLOW, '⚠')} line {w.lineno}: {w.name}")
        if asserts:
            print()
            print(self._c(BOLD, " Assert statements:"))
            for w in asserts:
                print(f" {self._c(YELLOW, '⚠')} line {w.lineno}: assert")
        if broad:
            print()
            print(self._c(BOLD, " Broad except clauses:"))
            for w in broad:
                print(f" {self._c(YELLOW, '⚠')} line {w.lineno}: {w.name}")
        print(self._c(CYAN, self.BORDER_DOUBLE))
        print()

def print_summary(results: list[FileResult], use_color: bool = True) -> None:
    def c(code: str, text: str) -> str:
        return f"{code}{text}{RESET}" if use_color else text

    total_files = len(results)
    ok_files = [r for r in results if r.error is None]
    error_files = [r for r in results if r.error is not None]
    changed = [r for r in ok_files if r.had_changes]
    warned = [r for r in ok_files if r.warnings]
    clean = [r for r in ok_files if not r.had_changes and not r.warnings]

    total_imports = sum(r.stats.unused_imports_removed for r in ok_files)
    total_dups = sum(r.stats.duplicate_lines_removed for r in ok_files)
    total_blanks = sum(r.stats.blank_lines_reduced for r in ok_files)
    total_warnings = sum(len(r.warnings) for r in ok_files)

    print()
    print(c(CYAN, "═" * 50))
    print(c(BOLD, " PyStreamliner Summary"))
    print(c(CYAN, "═" * 50))
    print(f" Files processed:     {total_files:>6d}")
    print(f" Clean (no issues):   {len(clean):>6d}")
    print(f" Modified:            {len(changed):>6d}")
    print(f" Warnings only:       {len([r for r in warned if not r.had_changes]):>6d}")
    if error_files:
        print(f" Errors:              {len(error_files):>6d}")
    print()
    print(c(BOLD, " Totals:"))
    print(f" Unused imports removed:  {total_imports:>6d}")
    print(f" Duplicate lines removed: {total_dups:>6d}")
    print(f" Blank lines reduced:     {total_blanks:>6d}")
    print(f" Warnings issued:         {total_warnings:>6d}")
    print(c(CYAN, "─" * 50))

    if changed:
        print()
        print(c(BOLD, " Files modified:"))
        for r in changed:
            s = r.stats
            parts = []
            if s.unused_imports_removed:
                parts.append(f"{s.unused_imports_removed} imports")
            if s.duplicate_lines_removed:
                parts.append(f"{s.duplicate_lines_removed} dups")
            if s.blank_lines_reduced:
                parts.append(f"{s.blank_lines_reduced} blanks")
            detail = ", ".join(parts) if parts else "changed"
            warn_note = f" + {len(r.warnings)} warnings" if r.warnings else ""
            print(f"  {c(GREEN, '✓')} {r.path}  ({detail}{warn_note})")

    pure_warn = [r for r in warned if not r.had_changes]
    if pure_warn:
        print()
        print(c(BOLD, " Files with warnings only:"))
        for r in pure_warn:
            print(f"  {c(YELLOW, '⚠')} {r.path}  ({len(r.warnings)} warnings)")

    if error_files:
        print()
        print(c(BOLD, " Errors:"))
        for r in error_files:
            print(f"  {c(RED, '✗')} {r.path}: {r.error}")

    print(c(CYAN, "═" * 50))
    print()

def print_diff(
    original_lines: list[str],
    cleaned_lines: list[str],
    filename: str = "source",
    use_color: bool = True,
) -> bool:
    diff = list(difflib.unified_diff(
        original_lines, cleaned_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm="",
    ))
    if not diff:
        return False
    for line in diff:
        if use_color:
            if line.startswith(("+++", "---")):
                sys.stdout.write(f"{BOLD}{line}{RESET}\n")
            elif line.startswith("@@"):
                sys.stdout.write(f"{CYAN}{line}{RESET}\n")
            elif line.startswith("+"):
                sys.stdout.write(f"{GREEN}{line}{RESET}\n")
            elif line.startswith("-"):
                sys.stdout.write(f"{RED}{line}{RESET}\n")
            else:
                sys.stdout.write(f"{DIM}{line}{RESET}\n")
        else:
            sys.stdout.write(line + "\n")
    return True

# ─── Core processing ─────────────────────────────────────────────────────────
def process_file(
    filepath: Path,
    args: argparse.Namespace,
    excluded_lines: set[int],
) -> FileResult:
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return FileResult(
            path=filepath, lines_analyzed=0, stats=CleaningStats(),
            warnings=[], import_details=[], had_changes=False,
            original_source="", cleaned_source="", error=str(exc),
        )

    try:
        ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return FileResult(
            path=filepath, lines_analyzed=0, stats=CleaningStats(),
            warnings=[], import_details=[], had_changes=False,
            original_source=source, cleaned_source=source, error=f"Syntax error: {exc}",
        )

    original_lines = source.splitlines(True)
    analyzer = SourceAnalyzer(source, str(filepath))
    analysis = analyzer.analyze()

    if args.fix_only:
        analysis.warnings = []
    else:
        analysis.warnings = _filter_warnings(
            analysis.warnings, args.select, args.ignore, excluded_lines
        )

    if args.warn_only:
        cleaned_lines = list(original_lines)
        stats = CleaningStats()
        import_details: list[ImportDetail] = []
    else:
        cleaner = SourceCleaner(
            original_lines, analysis,
            aggressive=args.aggressive,
            excluded_lines=excluded_lines,
        )
        cleaned_lines, stats, import_details = cleaner.clean()

    cleaned_source = "".join(cleaned_lines)
    had_changes = cleaned_source != source

    return FileResult(
        path=filepath,
        lines_analyzed=len(original_lines),
        stats=stats,
        warnings=analysis.warnings,
        import_details=import_details,
        had_changes=had_changes,
        original_source=source,
        cleaned_source=cleaned_source,
    )


def _process_file_worker(payload: tuple[str, dict, list[int]]) -> FileResult:
    """Picklable worker for ProcessPoolExecutor."""
    filepath_str, args_dict, excluded_list = payload
    filepath = Path(filepath_str)
    # Reconstruct a minimal Namespace
    args = argparse.Namespace(**args_dict)
    excluded_lines = set(excluded_list)
    return process_file(filepath, args, excluded_lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────
def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pystreamliner",
        description=(
            "PyStreamliner - A conservative, zero-dependency Python source cleaner.\n\n"
            "Tier 1 auto-fixes are applied in-place (unless --dry-run is given).\n"
            "Tier 2 issues are reported as warnings for manual review.\n\n"
            "Accepts one or more files and/or directories. Directories are walked recursively.\n"
            "Use --jobs / -j for parallel processing on large trees."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*", default=[],
                        help="Python files or directories to clean. Directories are scanned recursively.")
    parser.add_argument("-d", "--dry-run", action="store_true",
                        help="Preview changes without modifying files.")
    parser.add_argument("-b", "--backup", action="store_true",
                        help="Create a .bak copy before modifying.")
    parser.add_argument("-v", "--diff", action="store_true",
                        help="Show a unified diff (implied by --dry-run).")
    parser.add_argument("-n", "--no-color", action="store_true",
                        help="Strip ANSI codes.")
    parser.add_argument("-w", "--warn-only", action="store_true",
                        help="Passive scanner only. No modifications.")
    parser.add_argument("-c", "--check", action="store_true",
                        help="Exit non-zero if changes or warnings exist (CI).")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress the structured report.")
    parser.add_argument("--json", action="store_true",
                        help="Emit machine-readable JSON.")
    parser.add_argument("--fix-only", action="store_true",
                        help="Tier 1 only. Suppress all Tier 2 warnings.")
    parser.add_argument("--aggressive", action="store_true",
                        help="Slightly less conservative blank-line collapsing.")
    parser.add_argument("--stdin", action="store_true",
                        help="Read from stdin, write cleaned source to stdout.")
    parser.add_argument("--select", type=str, default=None,
                        help="Comma-separated warning categories to show.")
    parser.add_argument("--ignore", type=str, default=None,
                        help="Comma-separated warning categories to suppress.")
    parser.add_argument("--exclude", type=str, default=None,
                        help="Comma-separated line numbers/ranges to skip (e.g. 10,25-40).")
    parser.add_argument("--summary-threshold", type=int, default=SUMMARY_THRESHOLD,
                        help=f"Use tight summary when processing this many files or more (default: {SUMMARY_THRESHOLD}).")
    parser.add_argument("-j", "--jobs", type=int, default=0,
                        help="Number of parallel workers (0 = auto based on CPU count, 1 = sequential).")
    return parser

def main() -> int:
    parser = _build_argument_parser()
    args = parser.parse_args()
    use_color = not args.no_color
    excluded_lines = _parse_exclude(args.exclude)

    if args.stdin:
        source = sys.stdin.read()
        filepath = Path("<stdin>")
        original_lines = source.splitlines(True)

        try:
            ast.parse(source, filename=str(filepath))
        except SyntaxError as exc:
            sys.stderr.write(f"Syntax error in <stdin>: {exc}\n")
            return 1

        analyzer = SourceAnalyzer(source, str(filepath))
        analysis = analyzer.analyze()

        if args.fix_only:
            analysis.warnings = []
        else:
            analysis.warnings = _filter_warnings(
                analysis.warnings, args.select, args.ignore, excluded_lines
            )

        if args.warn_only:
            cleaned_lines = list(original_lines)
            stats = CleaningStats()
            import_details: list[ImportDetail] = []
        else:
            cleaner = SourceCleaner(
                original_lines, analysis,
                aggressive=args.aggressive,
                excluded_lines=excluded_lines,
            )
            cleaned_lines, stats, import_details = cleaner.clean()

        if args.json:
            payload = {
                "file": str(filepath),
                "lines_analyzed": len(original_lines),
                "stats": {
                    "unused_imports_removed": stats.unused_imports_removed,
                    "duplicate_lines_removed": stats.duplicate_lines_removed,
                    "blank_lines_reduced": stats.blank_lines_reduced,
                },
                "warnings": [
                    {"category": w.category, "name": w.name, "lineno": w.lineno, "message": w.message}
                    for w in analysis.warnings
                ],
                "import_details": [{"lineno": d.lineno, "text": d.text} for d in import_details],
            }
            print(json.dumps(payload, indent=2))
        elif not args.quiet:
            ReportPrinter(
                filename=str(filepath),
                lines_analyzed=len(original_lines),
                stats=stats,
                warnings=analysis.warnings,
                import_details=import_details,
                use_color=use_color,
            ).print_report()

        show_diff = args.diff or args.dry_run
        if show_diff and not args.json:
            had_diff = print_diff(
                [l.rstrip("\n").rstrip("\r") for l in original_lines],
                [l.rstrip("\n").rstrip("\r") for l in cleaned_lines],
                filename=str(filepath),
                use_color=use_color,
            )
            if not had_diff and not args.quiet:
                print("No changes." if not use_color else f"{DIM}No changes.{RESET}")

        if not args.json:
            sys.stdout.write("".join(cleaned_lines))

        if args.check:
            has_changes = (
                stats.unused_imports_removed
                or stats.duplicate_lines_removed
                or stats.blank_lines_reduced
            )
            if has_changes or analysis.warnings:
                return 1
        return 0

    if not args.paths:
        parser.error("the following arguments are required: paths (or use --stdin)")

    paths = [Path(p) for p in args.paths]
    files = _collect_python_files(paths)

    if not files:
        sys.stderr.write("No Python files found.\n")
        return 1

    # Determine worker count
    if args.jobs <= 0:
        # Auto: use CPU count, but cap reasonably and avoid oversubscription
        cpu = os.cpu_count() or 4
        max_workers = min(32, max(1, cpu))
    else:
        max_workers = max(1, args.jobs)

    # Prepare serializable args for workers (Namespace is not always cleanly picklable across all attrs)
    args_dict = {
        "fix_only": args.fix_only,
        "select": args.select,
        "ignore": args.ignore,
        "warn_only": args.warn_only,
        "aggressive": args.aggressive,
        "dry_run": args.dry_run,
        "backup": args.backup,
        "diff": args.diff,
        "no_color": args.no_color,
        "check": args.check,
        "quiet": args.quiet,
        "json": args.json,
        "summary_threshold": args.summary_threshold,
    }
    excluded_list = sorted(excluded_lines)

    results: list[FileResult] = []

    if max_workers == 1 or len(files) <= 1:
        # Sequential path (also used for tiny runs)
        for fp in files:
            results.append(process_file(fp, args, excluded_lines))
    else:
        # Parallel path
        payloads = [(str(fp), args_dict, excluded_list) for fp in files]
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(_process_file_worker, payload): payload[0]
                for payload in payloads
            }
            for future in as_completed(future_to_path):
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001
                    path_str = future_to_path[future]
                    results.append(FileResult(
                        path=Path(path_str),
                        lines_analyzed=0,
                        stats=CleaningStats(),
                        warnings=[],
                        import_details=[],
                        had_changes=False,
                        original_source="",
                        cleaned_source="",
                        error=f"Worker error: {exc}",
                    ))

    # Deterministic order
    results.sort(key=lambda r: str(r.path))

    # Apply writes (sequential, after all analysis is done)
    for result in results:
        if (result.error is None
                and result.had_changes
                and not args.dry_run
                and not args.warn_only):
            if args.backup:
                backup_path = result.path.with_suffix(result.path.suffix + ".bak")
                try:
                    shutil.copy2(str(result.path), str(backup_path))
                except OSError as exc:
                    sys.stderr.write(f"Error creating backup {backup_path}: {exc}\n")
                    continue
            try:
                result.path.write_text(result.cleaned_source, encoding="utf-8")
            except OSError as exc:
                sys.stderr.write(f"Error writing {result.path}: {exc}\n")
                result.error = str(exc)

    use_summary = len(results) >= args.summary_threshold

    if args.json:
        payload = []
        for r in results:
            entry = {
                "file": str(r.path),
                "lines_analyzed": r.lines_analyzed,
                "error": r.error,
                "had_changes": r.had_changes,
                "stats": {
                    "unused_imports_removed": r.stats.unused_imports_removed,
                    "duplicate_lines_removed": r.stats.duplicate_lines_removed,
                    "blank_lines_reduced": r.stats.blank_lines_reduced,
                },
                "warnings": [
                    {"category": w.category, "name": w.name, "lineno": w.lineno, "message": w.message}
                    for w in r.warnings
                ],
                "import_details": [{"lineno": d.lineno, "text": d.text} for d in r.import_details],
            }
            payload.append(entry)
        print(json.dumps(payload, indent=2))
    elif not args.quiet:
        if use_summary:
            print_summary(results, use_color=use_color)
        else:
            for r in results:
                if r.error:
                    sys.stderr.write(f"Error in {r.path}: {r.error}\n")
                    continue
                ReportPrinter(
                    filename=str(r.path),
                    lines_analyzed=r.lines_analyzed,
                    stats=r.stats,
                    warnings=r.warnings,
                    import_details=r.import_details,
                    use_color=use_color,
                ).print_report()

                show_diff = args.diff or args.dry_run
                if show_diff:
                    original_lines = r.original_source.splitlines(True)
                    cleaned_lines = r.cleaned_source.splitlines(True)
                    had_diff = print_diff(
                        [l.rstrip("\n").rstrip("\r") for l in original_lines],
                        [l.rstrip("\n").rstrip("\r") for l in cleaned_lines],
                        filename=str(r.path),
                        use_color=use_color,
                    )
                    if not had_diff:
                        print("No changes." if not use_color else f"{DIM}No changes.{RESET}")

    if args.check:
        for r in results:
            if r.error:
                return 1
            has_changes = (
                r.stats.unused_imports_removed
                or r.stats.duplicate_lines_removed
                or r.stats.blank_lines_reduced
            )
            if has_changes or r.warnings:
                return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
