# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Supe232323
#!/usr/bin/env python3
"""PyStreamliner — A conservative, single-file, command-line Python source code cleaner.
Two-tier model:
  Tier 1 (Auto-fix): Provably safe modifications only.
  Tier 2 (Warn-only): Detection + report, zero modification.
"""
from __future__ import annotations

import argparse
import ast
import dataclasses
import difflib
import json
import re
import shutil
import sys
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
        warnings.extend(self._find_vague_names())
        warnings.extend(self._find_shadowed_builtins())
        return AnalysisResult(
            unused_imports=unused_imports,
            warnings=warnings,
            all_names_in_all=self._all_names,
        )

    def _collect_all_used_names(self) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
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
                # Fully unused → delete the whole statement
                if is_multiline:
                    range_removals.append((start_idx, end_idx))
                else:
                    lines_to_remove.add(start_idx)
                self._import_details.append(ImportDetail(lineno=imp.lineno, text=imp.original_text.strip()))
                self._stats.unused_imports_removed += len(imp.unused_names)
            else:
                # Partial cleanup (works for both plain import and from-import)
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
        vague_names = [w for w in self._warnings if w.category == "vague_name"]
        shadowed = [w for w in self._warnings if w.category == "shadowed_builtin"]
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
        print(f" Vague variable names: {len(vague_names):>8d}")
        print(f" Shadowed built-ins: {len(shadowed):>8d}")
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
        print(self._c(CYAN, self.BORDER_DOUBLE))
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

# ─── CLI ──────────────────────────────────────────────────────────────────────
def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pystreamliner",
        description=(
            "PyStreamliner - A conservative, zero-dependency Python source cleaner.\n\n"
            "Tier 1 auto-fixes are applied in-place (unless --dry-run is given).\n"
            "Tier 2 issues are reported as warnings for manual review."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", nargs="?", default=None,
                        help="Path to the Python source file. Omit when using --stdin.")
    parser.add_argument("-d", "--dry-run", action="store_true",
                        help="Preview changes without modifying the file.")
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
    else:
        if args.file is None:
            parser.error("the following arguments are required: file (or use --stdin)")
        filepath = Path(args.file)
        if not filepath.exists():
            sys.stderr.write(f"Error: file not found: {filepath}\n")
            return 1
        if not filepath.is_file():
            sys.stderr.write(f"Error: not a regular file: {filepath}\n")
            return 1
        try:
            source = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            sys.stderr.write(f"Error reading {filepath}: {exc}\n")
            return 1
        original_lines = source.splitlines(True)

    try:
        ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        sys.stderr.write(f"Syntax error in {filepath}: {exc}\n")
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

    if args.stdin:
        if not args.json:
            sys.stdout.write("".join(cleaned_lines))
    elif not (args.dry_run or args.warn_only):
        cleaned_source = "".join(cleaned_lines)
        if cleaned_source != source:
            if args.backup:
                backup_path = filepath.with_suffix(filepath.suffix + ".bak")
                try:
                    shutil.copy2(str(filepath), str(backup_path))
                except OSError as exc:
                    sys.stderr.write(f"Error creating backup {backup_path}: {exc}\n")
                    return 1
                if not args.quiet:
                    msg = f"Backup saved to {backup_path}"
                    print(f"{DIM}{msg}{RESET}" if use_color else msg)
            try:
                filepath.write_text(cleaned_source, encoding="utf-8")
            except OSError as exc:
                sys.stderr.write(f"Error writing {filepath}: {exc}\n")
                return 1

    if args.check:
        has_changes = (
            stats.unused_imports_removed
            or stats.duplicate_lines_removed
            or stats.blank_lines_reduced
        )
        if has_changes or analysis.warnings:
            return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
