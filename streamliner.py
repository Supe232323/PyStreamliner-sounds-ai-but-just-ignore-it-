import ast
import sys
import difflib
from pathlib import Path

BAD_NAMES = {"x", "y", "z", "temp", "tmp", "foo", "bar", "baz", "a", "b", "c", "d", "e", "f"}


class PyStreamliner:
    def __init__(self):
        self.report = {
            "unused_imports": [],
            "unused_variables": [],
            "unused_functions": [],
            "bad_variable_names": [],
            "duplicate_lines": [],
            "lines_analyzed": 0
        }

    def analyze_and_clean(self, code: str) -> str:
        self.report["lines_analyzed"] = len(code.splitlines())
        tree = ast.parse(code)
        self._find_unused_variables(tree)
        self._find_unused_functions(tree)
        self._find_bad_variable_names(tree)
        cleaned = self._remove_unused_imports(tree, code)
        cleaned = self._remove_duplicate_lines(cleaned)
        return cleaned

    def _find_unused_variables(self, tree):
        assigned = {}
        assign_lines = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned[target.id] = getattr(target, 'lineno', '?')
                        assign_lines.setdefault(target.id, set()).add(target.lineno)

        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                lineno = getattr(node, 'lineno', None)
                if node.id in assign_lines:
                    if lineno not in assign_lines[node.id]:
                        used.add(node.id)
                else:
                    used.add(node.id)

        for name, lineno in assigned.items():
            if name not in used:
                self.report["unused_variables"].append(
                    f"Line {lineno}: '{name}' is assigned but never used"
                )

    def _find_unused_functions(self, tree):
        defined = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                defined[node.name] = node.lineno

        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)

        for name, lineno in defined.items():
            if name not in called and name != "main":
                self.report["unused_functions"].append(
                    f"Line {lineno}: '{name}' is defined but never called"
                )

    def _find_bad_variable_names(self, tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.lower() in BAD_NAMES:
                        self.report["bad_variable_names"].append(
                            f"Line {target.lineno}: '{target.id}' is a vague variable name, consider renaming it"
                        )

    def _remove_unused_imports(self, tree, code: str) -> str:
        imported_names = {}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name_used = alias.asname if alias.asname else alias.name
                    imported_names[name_used] = alias.name
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name_used = alias.asname if alias.asname else alias.name
                    imported_names[name_used] = alias.name

        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name):
                    used_names.add(node.value.id)

        unused = {local: original for local, original in imported_names.items()
                  if local not in used_names}

        if not unused:
            return code

        lines = code.splitlines()
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            should_remove = False
            for local_name, original_name in unused.items():
                if stripped == f"import {original_name}" or \
                   stripped.startswith(f"import {original_name} as ") or \
                   stripped.endswith(f"import {local_name}") or \
                   stripped.endswith(f"import {original_name} as {local_name}"):
                    should_remove = True
                    self.report["unused_imports"].append(original_name)
                    break
            if not should_remove:
                cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def _remove_duplicate_lines(self, code: str) -> str:
        lines = code.splitlines()
        cleaned_lines = []
        prev_line = None
        blank_count = 0

        for i, line in enumerate(lines):
            stripped = line.strip()

            if stripped == "":
                blank_count += 1
                if blank_count <= 2:
                    cleaned_lines.append(line)
                continue
            else:
                blank_count = 0

            if line == prev_line:
                self.report["duplicate_lines"].append(
                    f"Line {i+1}: Removed consecutive duplicate '{stripped}'"
                )
                continue

            cleaned_lines.append(line)
            prev_line = line

        return '\n'.join(cleaned_lines)

    def show_diff(self, original: str, cleaned: str):
        original_lines = original.splitlines(keepends=True)
        cleaned_lines = cleaned.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            original_lines,
            cleaned_lines,
            fromfile="original",
            tofile="cleaned"
        ))
        if diff:
            print("\n--- Changes ---")
            for line in diff:
                if line.startswith("+") and not line.startswith("+++"):
                    print(f"\033[92m{line}\033[0m", end="")
                elif line.startswith("-") and not line.startswith("---"):
                    print(f"\033[91m{line}\033[0m", end="")
                else:
                    print(line, end="")
            print("\n---------------\n")
        else:
            print("\nNo changes were made to the code.\n")

    def get_report(self) -> str:
        details = ""

        if self.report["unused_imports"]:
            details += "Unused imports removed:\n"
            for imp in self.report["unused_imports"]:
                details += f"  - {imp}\n"

        if self.report["unused_variables"]:
            details += "Unused variables detected:\n"
            for var in self.report["unused_variables"]:
                details += f"  - {var}\n"

        if self.report["unused_functions"]:
            details += "Unused functions detected:\n"
            for fn in self.report["unused_functions"]:
                details += f"  - {fn}\n"

        if self.report["bad_variable_names"]:
            details += "Vague variable names detected:\n"
            for name in self.report["bad_variable_names"]:
                details += f"  - {name}\n"

        if self.report["duplicate_lines"]:
            details += "Duplicate lines removed:\n"
            for dup in self.report["duplicate_lines"]:
                details += f"  - {dup}\n"

        return f"""
PyStreamliner Optimization Report
====================================
Lines analyzed:               {self.report["lines_analyzed"]}
Unused imports removed:       {len(self.report["unused_imports"])}
Unused variables detected:    {len(self.report["unused_variables"])}
Unused functions detected:    {len(self.report["unused_functions"])}
Vague variable names:         {len(self.report["bad_variable_names"])}
Duplicate lines removed:      {len(self.report["duplicate_lines"])}

{details}"""
