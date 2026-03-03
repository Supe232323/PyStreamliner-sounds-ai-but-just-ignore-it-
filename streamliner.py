
    
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
        """
        Detects variables that are assigned but never used anywhere else.
        """
        assigned = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned[target.id] = getattr(target, 'lineno', '?')

        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                continue
            if isinstance(node, ast.Name):
                used.add(node.id)

        for name, lineno in assigned.items():
            if name not in used:
                self.report["unused_variables"].append(f"Line {lineno}: '{name}' is assigned but never used")

    def _find_unused_functions(self, tree):
        """
        Detects functions that are defined but never called.
        """
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
                self.report["unused_functions"].append(f"Line {lineno}: '{name}' is defined but never called")

    def _find_bad_variable_names(self, tree):
        """
        Flags variables with vague/meaningless names like x, y, temp, foo, etc.
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.lower() in BAD_NAMES:
                        self.report["bad_variable_names"].append(
                            f"Line {target.lineno}: '{target.id}' is a vague variable name, consider renaming it"
                        )

    def _remove_unused_imports(self, tree, code: str) -> str:
        """
        Properly detects unused imports by checking if the imported name
        is actually referenced anywhere else in the code.
        """
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
        """
        Only removes consecutive duplicate lines.
        """
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
        """
        Shows a diff of what changed between original and cleaned code.
        """
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
                    print(f"\033[92m{line}\033[0m", end="")  # green
                elif line.startswith("-") and not line.startswith("---"):
                    print(f"\033[91m{line}\033[0m", end="")  # red
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


def main():
    if len(sys.argv) < 2:
        print("Usage: python streamliner.py your_messy_code.py")
        print("       The cleaned file will be saved as your_messy_code_cleaned.py")
        return

    file_path = Path(sys.argv[1])

    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return

    if file_path.suffix != ".py":
        print(f"❌ This tool only works on .py files, got: {file_path.suffix}")
        return

    original_code = file_path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(original_code)
    except SyntaxError as e:
        print(f"❌ Your file has a syntax error and can't be parsed: {e}")
        return

    streamliner = PyStreamliner()
    cleaned_code = streamliner.analyze_and_clean(original_code)

    print(streamliner.get_report())
    streamliner.show_diff(original_code, cleaned_code)

    cleaned_path = file_path.with_stem(file_path.stem + "_cleaned")
    confirm = input(f"Save cleaned file as '{cleaned_path.name}'? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled. No files were changed.")
        return

    cleaned_path.write_text(cleaned_code, encoding="utf-8")

    report_path = Path("streamliner_report.txt")
    report_path.write_text(streamliner.get_report(), encoding="utf-8")

    print(f"✅ Cleaned file saved as: {cleaned_path.name}")
    print(f"✅ Full report saved as: streamliner_report.txt")


if __name__ == "__main__":
    main()
