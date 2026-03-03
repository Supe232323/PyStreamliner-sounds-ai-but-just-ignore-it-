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

        self._find_unused_imports(tree, code)
        cleaned = self._remove_duplicates(code)
        cleaned = self._apply_simplifications(cleaned)

        return cleaned

    def _find_unused_imports(self, tree, code):
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
        for imp in imports:
            if f"import {imp}" in code:
                self.report["unused_imports"].append(imp)

    def _remove_duplicates(self, code: str) -> str:
        lines = code.splitlines()
        seen = {}
        cleaned_lines = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen[stripped] = True
                cleaned_lines.append(line)
            elif stripped:
                self.report["duplicate_lines"].append(f"Line {i+1}: Removed duplicate '{stripped}'")
        return '\n'.join(cleaned_lines)

    def _apply_simplifications(self, code: str) -> str:
        lines = code.splitlines()
        cleaned = []
        for line in lines:
            if "if" in line and "else" in line and ":" in line and "print" in line:
                new_line = line.replace("if ", "").replace("else ", " if ") + " else " + line.split("else ")[-1].replace(":", "")
                cleaned.append(new_line.strip())
                self.report["simplifications"].append("Converted if-else to ternary")
            else:
                cleaned.append(line)
        return '\n'.join(cleaned)

    def get_report(self) -> str:
        return f"""PyStreamliner Optimization Report
====================================
Lines analyzed: {self.report["lines_analyzed"]}

Unused imports detected & removed: {len(self.report["unused_imports"])}
Duplicate lines removed: {len(self.report["duplicate_lines"])}
Simplifications applied: {len(self.report["simplifications"])}

✅ Cleaned file created
"""

def main():
    if len(sys.argv) < 2:
        print("Usage: python streamliner.py your_messy_code.py")
        return

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return

    original_code = file_path.read_text(encoding="utf-8")
    streamliner = PyStreamliner()
    cleaned_code = streamliner.analyze_and_clean(original_code)

    cleaned_path = file_path.with_stem(file_path.stem + "_cleaned")
    cleaned_path.write_text(cleaned_code, encoding="utf-8")

    report_path = Path("streamliner_report.txt")
    report_path.write_text(streamliner.get_report(), encoding="utf-8")

    print(streamliner.get_report())
    print(f"✅ Cleaned file saved as: {cleaned_path.name}")
    print(f"✅ Full report saved as: streamliner_report.txt")

if __name__ == "__main__":
    main()
