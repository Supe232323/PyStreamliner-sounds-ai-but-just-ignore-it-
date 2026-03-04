#!/usr/bin/env python3
"""PyStreamliner — A conservative, single-file, command-line Python source code cleaner.

Two-tier model:
  Tier 1 (Auto-fix):  Provably safe modifications only.
  Tier 2 (Warn-only): Detection + report, zero modification.
"""
from __future__ import annotations

import ast
import dataclasses
import difflib
import re
import sys
import textwrap
from pathlib import Path

# ─── ANSI Color Constants ────────────────────────────────────────────────────

RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_CONSECUTIVE_BLANKS = 2

VAGUE_NAMES: frozenset[str] = frozenset({
    "x", "y", "z", "temp", "tmp", "foo", "bar", "baz",
    "a", "b", "c", "d", "e", "f",
})


# ─── Data Structures ─────────────────────────────────────────────────────────

@dataclasses.dataclass
class ImportFinding:
    """A single import statement with usage information."""

    lineno: int
    original_text: str
    bound_names: list[str]
    unused_names: list[str]
    used_names: list[str]
    is_from_import: bool
    indent: str


@dataclasses.dataclass
class Warning:
    """A Tier 2 warning for manual review."""

    category: str
    name: str
    lineno: int
    message: str


@dataclasses.dataclass
class AnalysisResult:
    """Complete analysis output."""

    unused_imports: list[ImportFinding]
    warnings: list[Warning]
    all_names_in_all: set[str]


@dataclasses.dataclass
class CleaningStats:
    """Counts of auto-fix actions taken."""

    unused_imports_removed: int = 0
    duplicate_lines_removed: int = 0
    blank_lines_reduced: int = 0


@dataclasses.dataclass
class ImportDetail:
    """Detail line for the report."""

    lineno: int
    text: str


# ─── SourceAnalyzer ───────────────────────────────────────────────────────────

class SourceAnalyzer:
    """Analyzes Python source code for issues without modifying it."""

    def __init__(self, source: str, filename: str) -> None:
        self._source = source
        self._filename = filename
        self._tree = ast.parse(source, filename=filename)
        self._lines = source.splitlines(True)
        self._used_names: set[str] | None = None
        self._all_names: set[str] = set()

    def analyze(self) -> AnalysisResult:
        """Run all analysis passes and return combined results."""
        self._used_names = self._collect_all_used_names()
        self._collect_all_list_names()

        unused_imports = self._find_unused_imports()
        warnings: list[Warning] = []
        warnings.extend(self._find_unused_variables())
        warnings.extend(self._find_unused_functions())
        warnings.extend(self._find_vague_names())

        return AnalysisResult(
            unused_imports=unused_imports,
            warnings=warnings,
            all_names_in_all=self._all_names,
        )

    def _collect_all_used_names(self) -> set[str]:
        """Collect every name referenced in Load context across the entire AST."""
        names: set[str] = set()
        for node in ast.walk(self._tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                names.add(node.id)
            if isinstance(node, ast.Attribute):
                val = node.value
                if isinstance(val, ast.Name):
                    names.add(val.id)
        return names

    def _collect_all_list_names(self) -> None:
        """Collect string literals inside __all__ assignments."""
        for node in ast.walk(self._tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not (isinstance(target, ast.Name) and target.id == "__all__"):
                    continue
                if not isinstance(node.value, (ast.List, ast.Tuple)):
                    continue
                for elt in node.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        self._all_names.add(elt.value)

    def _find_unused_imports(self) -> list[ImportFinding]:
        """Detect imports whose bound names are never referenced."""
        assert self._used_names is not None
        findings: list[ImportFinding] = []

        for node in ast.iter_child_nodes(self._tree):
            if isinstance(node, ast.Import):
                findings.extend(self._check_import(node))
            elif isinstance(node, ast.ImportFrom):
                result = self._check_from_import(node)
                if result is not None:
                    findings.append(result)

        return findings

    def _check_import(self, node: ast.Import) -> list[ImportFinding]:
        """Check a plain 'import x' statement."""
        assert self._used_names is not None
        findings: list[ImportFinding] = []
        line_text = self._get_line_text(node.lineno)
        indent = self._get_indent(line_text)

        for alias in node.names:
            bound = alias.asname if alias.asname else alias.name.split(".")[0]
            if bound in self._used_names or bound in self._all_names:
                continue
            findings.append(ImportFinding(
                lineno=node.lineno,
                original_text=line_text.rstrip(),
                bound_names=[bound],
                unused_names=[bound],
                used_names=[],
                is_from_import=False,
                indent=indent,
            ))

        return findings

    def _check_from_import(self, node: ast.ImportFrom) -> ImportFinding | None:
        """Check a 'from x import y' statement."""
        assert self._used_names is not None

        # Never remove from __future__ imports
        if node.module and node.module == "__future__":
            return None

        # Never remove star imports
        if any(alias.name == "*" for alias in node.names):
            return None

        line_text = self._get_line_text(node.lineno)
        indent = self._get_indent(line_text)

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
            original_text=line_text.rstrip(),
            bound_names=bound_names,
            unused_names=unused,
            used_names=used,
            is_from_import=True,
            indent=indent,
        )

    def _find_unused_variables(self) -> list[Warning]:
        """Detect variables assigned but never read."""
        assert self._used_names is not None
        warnings: list[Warning] = []
        assigned = self._collect_assigned_names()

        for name, lineno in assigned:
            if name == "_":
                continue
            if name.startswith("__") and name.endswith("__"):
                continue
            if name in self._all_names:
                continue
            if name in self._used_names:
                continue
            warnings.append(Warning(
                category="unused_variable",
                name=name,
                lineno=lineno,
                message=f"\u26a0 Unused variable '{name}' at line {lineno}",
            ))

        return warnings

    def _collect_assigned_names(self) -> list[tuple[str, int]]:
        """Collect all variable assignment targets with line numbers."""
        assigned: list[tuple[str, int]] = []

        for node in ast.walk(self._tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    self._extract_names_from_target(target, assigned)
            elif isinstance(node, ast.AnnAssign) and node.target:
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

    def _extract_names_from_target(
        self,
        target: ast.expr,
        result: list[tuple[str, int]],
    ) -> None:
        """Recursively extract name targets from assignment LHS."""
        if isinstance(target, ast.Name) and isinstance(target.ctx, ast.Store):
            result.append((target.id, target.lineno))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._extract_names_from_target(elt, result)

    def _find_unused_functions(self) -> list[Warning]:
        """Detect top-level functions that are never called."""
        assert self._used_names is not None
        warnings: list[Warning] = []

        for node in ast.iter_child_nodes(self._tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name == "main":
                continue
            if node.decorator_list:
                continue
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            if node.name in self._used_names:
                continue

            # Check if inside if __name__ block and starts with _
            if node.name.startswith("_"):
                parent_is_name_main = self._is_inside_name_main_block(node)
                if parent_is_name_main:
                    continue

            warnings.append(Warning(
                category="unused_function",
                name=node.name,
                lineno=node.lineno,
                message=f"\u26a0 Unused function '{node.name}()' at line {node.lineno}",
            ))

        return warnings

    def _is_inside_name_main_block(self, node: ast.AST) -> bool:
        """Check if a node is inside an 'if __name__ == ...' block."""
        for top_node in ast.iter_child_nodes(self._tree):
            if not isinstance(top_node, ast.If):
                continue
            test = top_node.test
            if not isinstance(test, ast.Compare):
                continue
            if not isinstance(test.left, ast.Name):
                continue
            if test.left.id != "__name__":
                continue
            for child in ast.walk(top_node):
                if child is node:
                    return True
        return False

    def _find_vague_names(self) -> list[Warning]:
        """Detect vague or single-letter variable names."""
        warnings: list[Warning] = []
        assigned = self._collect_assigned_names()
        seen: set[tuple[str, int]] = set()

        for name, lineno in assigned:
            if (name, lineno) in seen:
                continue
            seen.add((name, lineno))

            # Skip variables inside comprehensions (check parent context)
            if self._is_in_comprehension(lineno):
                continue

            if name.lower() in VAGUE_NAMES:
                warnings.append(Warning(
                    category="vague_name",
                    name=name,
                    lineno=lineno,
                    message=f"\u26a0 Vague variable name '{name}' at line {lineno}",
                ))

        return warnings

    def _is_in_comprehension(self, lineno: int) -> bool:
        """Check if a line is inside a comprehension or lambda."""
        for node in ast.walk(self._tree):
            if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                                 ast.GeneratorExp, ast.Lambda)):
                if hasattr(node, "lineno") and node.lineno == lineno:
                    return True
        return False

    def _get_line_text(self, lineno: int) -> str:
        """Get the original source line by 1-based line number."""
        if lineno < 1 or lineno > len(self._lines):
            return ""
        return self._lines[lineno - 1]

    @staticmethod
    def _get_indent(line: str) -> str:
        """Extract leading whitespace from a line."""
        match = re.match(r"^(\s*)", line)
        return match.group(1) if match else ""


# ─── SourceCleaner ────────────────────────────────────────────────────────────

class SourceCleaner:
    """Applies Tier 1 auto-fixes to source lines."""

    def __init__(self, lines: list[str], analysis: AnalysisResult) -> None:
        self._lines = list(lines)
        self._analysis = analysis
        self._stats = CleaningStats()
        self._import_details: list[ImportDetail] = []

    def clean(self) -> tuple[list[str], CleaningStats, list[ImportDetail]]:
        """Apply all auto-fixes and return cleaned lines with stats."""
        self._remove_unused_imports()
        self._remove_duplicate_lines()
        self._reduce_blank_lines()
        self._ensure_trailing_newline()
        return self._lines, self._stats, self._import_details

    def _remove_unused_imports(self) -> None:
        """Remove or trim unused import statements."""
        lines_to_remove: set[int] = set()
        line_replacements: dict[int, str] = {}

        for imp in self._analysis.unused_imports:
            idx = imp.lineno - 1
            if idx < 0 or idx >= len(self._lines):
                continue

            if not imp.used_names:
                # Remove entire line
                lines_to_remove.add(idx)
                self._import_details.append(ImportDetail(
                    lineno=imp.lineno,
                    text=imp.original_text.strip(),
                ))
                self._stats.unused_imports_removed += len(imp.unused_names)
            elif imp.is_from_import:
                # Partial removal
                original = self._lines[idx]
                match = re.match(r"^(\s*from\s+\S+\s+import\s+)", original)
                if not match:
                    continue
                prefix = match.group(1)
                new_line = prefix + ", ".join(imp.used_names)
                if original.endswith("\n"):
                    new_line += "\n"
                elif original.endswith("\r\n"):
                    new_line += "\r\n"
                line_replacements[idx] = new_line
                kept = ", ".join(f"'{n}'" for n in imp.used_names)
                self._import_details.append(ImportDetail(
                    lineno=imp.lineno,
                    text=f"{imp.original_text.strip()}  (partially cleaned: kept {kept})",
                ))
                self._stats.unused_imports_removed += len(imp.unused_names)

        # Apply changes in reverse order to preserve indices
        new_lines: list[str] = []
        for idx, line in enumerate(self._lines):
            if idx in lines_to_remove:
                continue
            if idx in line_replacements:
                new_lines.append(line_replacements[idx])
            else:
                new_lines.append(line)

        self._lines = new_lines

    def _remove_duplicate_lines(self) -> None:
        """Remove consecutive exact duplicate non-blank lines."""
        if not self._lines:
            return

        result: list[str] = [self._lines[0]]
        for i in range(1, len(self._lines)):
            current = self._lines[i]
            previous = self._lines[i - 1]

            # Skip blank-line dedup — handled by blank-line reducer
            if re.match(r"^\s*$", current.rstrip("\n").rstrip("\r")):
                result.append(current)
                continue

            if current == previous:
                self._stats.duplicate_lines_removed += 1
                continue

            result.append(current)

        self._lines = result

    def _reduce_blank_lines(self) -> None:
        """Cap consecutive blank lines at MAX_CONSECUTIVE_BLANKS."""
        result: list[str] = []
        consecutive = 0

        for line in self._lines:
            stripped = line.rstrip("\n").rstrip("\r")
            if re.match(r"^\s*$", stripped):
                consecutive += 1
                if consecutive <= MAX_CONSECUTIVE_BLANKS:
                    result.append(line)
                else:
                    self._stats.blank_lines_reduced += 1
            else:
                consecutive = 0
                result.append(line)

        self._lines = result

    def _ensure_trailing_newline(self) -> None:
        """Ensure the file ends with exactly one newline."""
        if not self._lines:
            return
        last = self._lines[-1]
        if not last.endswith("\n"):
            self._lines[-1] = last + "\n"


# ─── Report Printer ──────────────────────────────────────────────────────────

class ReportPrinter:
    """Prints the structured PyStreamliner report."""

    BORDER_DOUBLE = "\u2550" * 38
    BORDER_SINGLE = "\u2500" * 38

    def __init__(
        self,
        filename: str,
        lines_analyzed: int,
        stats: CleaningStats,
        warnings: list[Warning],
        import_details: list[ImportDetail],
    ) -> None:
        self._filename = filename
        self._lines_analyzed = lines_analyzed
        self._stats = stats
        self._warnings = warnings
        self._import_details = import_details

    def print_report(self) -> None:
        """Print the full structured report to stdout."""
        unused_vars = [w for w in self._warnings if w.category == "unused_variable"]
        unused_funcs = [w for w in self._warnings if w.category == "unused_function"]
        vague_names = [w for w in self._warnings if w.category == "vague_name"]

        print(f"\n{self.BORDER_DOUBLE}")
        print(f"  PyStreamliner Report")
        print(self.BORDER_DOUBLE)
        print(f"  File:  {self._filename:>30s}")
        print(f"  Lines analyzed:  {self._lines_analyzed:>20d}")
        print()
        print(f"  Auto-fixes applied:")
        print(f"    Unused imports removed:  {self._stats.unused_imports_removed:>10d}")
        print(f"    Duplicate lines removed: {self._stats.duplicate_lines_removed:>10d}")
        print(f"    Blank lines reduced:     {self._stats.blank_lines_reduced:>10d}")
        print()
        print(f"  Warnings (manual review needed):")
        print(f"    Unused variables detected: {len(unused_vars):>8d}")
        print(f"    Unused functions detected: {len(unused_funcs):>8d}")
        print(f"    Vague variable names:      {len(vague_names):>8d}")
        print(self.BORDER_SINGLE)

        # Detail sections
        if self._import_details:
            print()
            print("  Unused imports removed:")
            for detail in self._import_details:
                print(f"    \u2022 line {detail.lineno}:  {detail.text}")

        if unused_vars:
            print()
            print("  Unused variables detected:")
            for w in unused_vars:
                print(f"    \u26a0 line {w.lineno}:  {w.name}")

        if unused_funcs:
            print()
            print("  Unused functions detected:")
            for w in unused_funcs:
                print(f"    \u26a0 line {w.lineno}:  {w.name}()")

        if vague_names:
            print()
            print("  Vague variable names:")
            for w in vague_names:
                print(f"    \u26a0 line {w.lineno}:  {w.name}")

        print(self.BORDER_DOUBLE)
        print()


# ─── Diff Printer ─────────────────────────────────────────────────────────────

def print_diff(original_lines: list[str], cleaned_lines: list[str]) -> bool:
    
