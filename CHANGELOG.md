# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com).

## [1.19.0] - 2026-08-20

### Added
- **Config file support** (zero dependencies)
  - Reads from `pyproject.toml` under `[tool.pystreamliner]`
  - Or a dedicated `.pystreamliner.toml` in the current directory
  - Supported keys: `aggressive`, `ignore`, `select`, `summary_threshold`, `jobs`, `exclude` (list of globs), `fix_only`, `warn_only`
  - CLI flags always override config values
- **Path / glob excludes**
  - New `--exclude-path` (repeatable) for glob patterns, e.g. `--exclude-path 'tests/**' --exclude-path '**/migrations/*'`
  - Also configurable via `exclude = ["tests/**", "**/migrations/*"]` in the config file
  - Uses only the standard library (`fnmatch`)

### Changed
- `_collect_python_files` now respects exclude globs in addition to the built-in junk directory list

## [1.18.0] - 2026-08-19

### Added
- **Parallel processing** via `-j` / `--jobs N`
  - Uses `ProcessPoolExecutor` for multi-core speed on large directories
  - `0` (default) = auto (based on CPU count, capped)
  - `1` = force sequential
  - Analysis is fully parallel; file writes remain sequential for safety
- **Unused class detection** (Tier 2, category `unused_class`)
  - Reports classes that appear unused (skips dunder names, decorated classes, and those referenced in `__all__` or the module)
- Attribute name tracking in used-name collection so methods called via `obj.method()` / `self.foo()` are no longer false-positived as unused

### Fixed
- Major false-positive on methods and attribute-accessed callables (previously every method was reported unused unless called as a bare name)

### Changed
- Report printer now includes "Unused classes detected" count and detail section
- Module docstring updated to mention parallel support

## [1.17.0] - 2026-08-19

### Added
- **Multi-file and recursive directory support**
  - Accept multiple files and/or directories on the command line
  - Directories are walked recursively for `*.py` files
  - Automatically skips common junk directories: `.git`, `__pycache__`, `venv`, `.venv`, `env`, `node_modules`, `dist`, `build`, `.tox`, `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, etc.
- **Tight summary mode for large runs**
  - When processing 5 or more files (configurable via `--summary-threshold`), switches from per-file detailed reports to a compact summary
  - Summary shows: files processed / clean / modified / warnings-only / errors, aggregate stats, and a short list of files that actually changed or had warnings
- New CLI argument: `--summary-threshold N` (default: 5)

### Changed
- CLI argument renamed from `file` to `paths` (still accepts a single file for backward compatibility)
- README updated with multi-file usage examples and summary mode documentation

## [1.16.0] - 2026-08-15

### Added
- Tier-2 security detectors:
  - Dangerous calls: `eval`, `exec`, `compile`, `pickle`/`marshal`/`shelve` load/dump, `os.system`/`os.popen`, `subprocess` with `shell=True`, `yaml.load` without SafeLoader
  - Possible hardcoded secrets (assignments of string literals to names like password, secret, token, api_key, etc.)
  - Use of `assert` (stripped under `-O`; not for security checks)
  - Broad `except:` and `except Exception:`
- New warning categories: `dangerous_call`, `hardcoded_secret`, `assert_used`, `broad_except`
- Report now includes counts and details for the new security warnings

## [1.15.0] - 2026-08-04

### Added
- `--check` / `-c` — exit non-zero if Tier-1 changes or Tier-2 warnings exist (CI-friendly)
- `--quiet` / `-q` — suppress the structured report
- `--json` — machine-readable JSON output
- `--fix-only` — apply only Tier-1 fixes, suppress all Tier-2 warnings
- `--select` / `--ignore` — filter warning categories
- `--stdin` — read from stdin, write cleaned source to stdout
- `--aggressive` — more aggressive blank-line collapsing (max 1 consecutive blank line)

## [1.14.0] - 2026-08-04

### Changed
- Raised minimum Python version to 3.13
- Modernized all type annotations to native generics and union syntax
- Removed unnecessary `typing` imports

## [1.13.1] - 2026-07-28

### Added
- `--warn-only` flag

### Changed
- Codebase refactor

## [1.12.1] - 2026-07-17

### Added
- `[project.urls]` metadata (Homepage, Repository, Documentation)

## [1.12.0] - 2026-07-17

### Added
- Native PyPI Trusted Publishing (OIDC) support
- `skip-existing: true` in the publish pipeline
- Explicit package discovery constraints in `pyproject.toml`

### Fixed
- Pipeline deployment crash caused by legacy authentication
- `setuptools` flat-layout build issues (excluded `test_messy`)

## [1.11.0] - 2026-06-30

### Added
- Install support via `pip install git+https://github.com/Supe232323/pystreamliner.git`

## [1.10.0] - 2026-06-29

### Added
- `--warn-only`, `--diff`, `--backup`, `--dry-run`, `--no-color`
- Shadowed builtins detection (Tier 2)
- Robust `argparse` CLI
- Pre-flight `ast.parse()` safety check

### Fixed
- Fragile comprehension/lambda detection → parent-tree mapping
- False positives on pure type annotations
- Multiline `from x import y` handling
- Blank-line logic and file I/O error handling
- ANSI color consistency

### Changed
- Minimum Python version set to 3.10 (later raised)

## [1.0.0] - 2026-03-04

### Added
- Initial release
