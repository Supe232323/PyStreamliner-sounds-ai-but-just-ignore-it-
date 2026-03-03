# PyStreamliner

**Automated Python Code Optimization Tool**

PyStreamliner performs static analysis on Python source code to:
- Detect and remove unused imports and variables
- Identify duplicate expressions and redundant logic
- Simplify complex statements (if-else → ternary, loops → comprehensions where safe)
- Generate a cleaned version with a detailed optimization report

Designed for developers who want faster, cleaner, more maintainable code.

## Features
- Pure Python (no external dependencies for core functionality)
- AST-based analysis for accuracy and safety
- Detailed before/after report
- Command-line interface
- Ready for GitHub Actions CI (optional)

## Installation
```bash
git clone https://github.com/YOUR-USERNAME/PyStreamliner.git
cd PyStreamliner
pip install -r requirements.txt
