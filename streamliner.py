
    import ast
import sys
from pathlib import Path


class PyStreamliner:
    def __init__(self):
        self.report = {
            "unused_imports": [],
            "duplicate_lines": [],
            "simplifications": [],
            "lines_analyzed": 0
        }

    def analyze_and_clean(self, code: str) -> str:
        self.report["lines_analyzed"] = len(code.splitlines())
        tree = ast.parse(code)
        cleaned = self._remove_unused_imports(tree, code)
        cleaned = self._remove_duplicate_lines(cleaned)
        return cleaned

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

    def get_report(self) -> str:
        details = ""

        if self.report["unused_imports"]:
            details += "Unused imports removed:\n"
            for imp in self.report["unused_imports"]:
                details += f"  - {imp}\n"

        if self.report["duplicate_lines"]:
            details += "Duplicate lines removed:\n"
            for dup in self.report["duplicate_lines"]:
                details += f"  - {dup}\n"

        return f"""PyStreamliner Optimization Report
====================================
Lines analyzed:               {self.report["lines_analyzed"]}
Unused imports removed:       {len(self.report["unused_imports"])}
Duplicate lines removed:      {len(self.report["duplicate_lines"])}

{details}✅ Cleaned file created
"""


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

    cleaned_path = file_path.with_stem(file_path.stem + "_cleaned")
    print(streamliner.get_report())

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
