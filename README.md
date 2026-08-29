# pystreamliner

[![PyPI version](https://img.shields.io/pypi/v/pystreamliner.svg)](https://pypi.org/project/pystreamliner/)
[![PyPI downloads](https://img.shields.io/pypi/dm/pystreamliner)](https://pypi.org/project/pystreamliner/)

**Automatically clean up messy Python files — without breaking anything.**

pystreamliner uses Python's AST (abstract syntax tree) to safely detect and fix common code issues. It operates on two tiers: things it can fix automatically with zero risk, and things it flags for you to review manually.

Supports single files, multiple files, and recursive directory cleaning with a tight summary mode for large runs.

**Discord:** [https://discord.gg/Z6cXxhSKS](https://discord.gg/Z6cXxhSKS)

---

## What it does

**Auto-fixes (Tier 1 — applied immediately):**
- Removes unused imports, or trims partially unused `from x import y` statements
- Removes consecutive duplicate lines
- Caps excessive blank lines

**Warnings (Tier 2 — reported, never auto-changed):**
- Unused variables
- Unused top-level functions
- Unused classes
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

Directories are walked recursively. Common junk directories (`.git`, `__pycache__`, `venv`, `node_modules`, etc.) are automatically skipped when they appear as *sub*-directories.

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
 pystreamliner summary
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
  pystreamliner report
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

## Limitations / By design

These behaviours are intentional. They keep the tool zero-dependency, fast, and conservative.

### Unused function / class detection is **per-file only**

pystreamliner analyses each file independently using only that file's AST.  
It does **not** follow imports across modules or build a whole-project symbol table.

Consequence: a function or class that is defined in one file and imported + used in another file will be reported as unused when you run the tool on the definition file alone.

This is by design. Full inter-module analysis would require either a much heavier dependency stack or a complete project-wide index, both of which go against the tool's zero-dependency, single-pass philosophy.

**Work-arounds:**
- Put public API names in `__all__` — they are automatically treated as used.
- Use `--ignore unused_function,unused_class` (or the config equivalent).
- Run the tool on the whole project (or the relevant packages) so the definitions and call sites are more likely to be in the same analysis pass when you care about the warnings.

### Directory name collisions with the ignore list

The built-in ignore list contains common junk directories (`__pycache__`, `.git`, `venv`, `coverage`, `htmlcov`, etc.).  
These are only skipped when they appear as *sub-directories* of a path you gave the tool.

If you explicitly pass a directory that happens to be named one of those (e.g. `pystreamliner coverage/`), its contents **are** processed. (This was fixed in 1.19.1.)

Nested junk directories inside that tree are still skipped as expected.

### Summary mode vs detailed reports

When ≥ 5 files are processed (configurable), output switches to a compact summary that shows counts only.  
Detailed per-file reports (with every warning message) appear only for smaller runs. This is intentional so large projects stay readable.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
