# pystreamliner

[![PyPI version](https://img.shields.io/pypi/v/pystreamliner.svg)](https://pypi.org/project/pystreamliner/)
[![PyPI downloads](https://img.shields.io/pypi/dm/pystreamliner)](https://pypi.org/project/pystreamliner/)

**Automatically clean up messy Python files — without breaking anything.**

pystreamliner uses Python's AST (abstract syntax tree) to safely detect and fix common code issues. It operates on two tiers: things it can fix automatically with zero risk, and things it flags for you to review manually.

Supports single files, multiple files, and recursive directory cleaning with a tight summary mode for large runs.

---

## What it does

**Auto-fixes (Tier 1 — applied immediately):**
- Removes unused imports, or trims partially unused `from x import y` statements
- Removes consecutive duplicate lines
- Caps excessive blank lines

**Warnings (Tier 2 — reported, never auto-changed):**
- Unused variables
- Unused top-level functions
- Vague variable names (`x`, `tmp`, `foo`, `bar`, etc.)
- Shadowed built-ins
- Dangerous calls (`eval`, `exec`, `pickle`, `os.system`, `subprocess(..., shell=True)`, unsafe `yaml.load`)
- Possible hardcoded secrets
- Assert statements
- Broad `except:` / `except Exception`

pystreamliner never touches code it isn't certain about. If there's any doubt, it warns you instead.

---

## Install

```bash
pip install pystreamliner
```

No dependencies. Runs on Python 3.13+.

---

## Usage

**Single file:**
```bash
pystreamliner your_file.py
```

**Multiple files:**
```bash
pystreamliner file1.py file2.py utils/*.py
```

**Entire project (recursive):**
```bash
pystreamliner .
# or
pystreamliner src/ tests/
```

Directories are walked recursively. Common junk directories (`.git`, `__pycache__`, `venv`, `node_modules`, etc.) are automatically skipped.

**Preview without modifying:**
```bash
pystreamliner --dry-run .
```

**CI mode (exit non-zero on issues):**
```bash
pystreamliner --check --quiet .
```

---

## Big runs / Summary mode

When you process 5 or more files (configurable with `--summary-threshold`), pystreamliner switches to a compact summary instead of dumping a full report for every file:

```
══════════════════════════════════════════════════
 PyStreamliner Summary
══════════════════════════════════════════════════
 Files processed:         47
 Clean (no issues):       39
 Modified:                 6
 Warnings only:            2

 Totals:
 Unused imports removed:      14
 Duplicate lines removed:      3
 Blank lines reduced:         11
 Warnings issued:              8
──────────────────────────────────────────────────

 Files modified:
  ✓ src/utils.py  (3 imports, 2 blanks)
  ✓ src/main.py   (1 imports + 2 warnings)
  ...
══════════════════════════════════════════════════
```

This keeps the output usable even on large codebases.

---

## Example (single-file detailed report)

```
══════════════════════════════════════════
  PyStreamliner Report
══════════════════════════════════════════
  File:                        main.py
  Lines analyzed:                   312

  Auto-fixes applied:
    Unused imports removed:           3
    Duplicate lines removed:          1
    Blank lines reduced:              2

  Warnings (manual review needed):
    Unused variables detected:        2
    Unused functions detected:        1
    Vague variable names:             1
──────────────────────────────────────────

  Unused imports removed:
    • line 4:  import os
    • line 5:  import sys
    • line 7:  from pathlib import Path, PurePath  (partially cleaned: kept 'Path')

  Unused variables:
    ⚠ line 42:  result
    ⚠ line 87:  temp_val

  Vague variable names:
    ⚠ line 23:  tmp
══════════════════════════════════════════
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
