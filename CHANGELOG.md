# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com).

## [1.21.0] - 2026-09-01

### Added
- **`--project`** — opt-in, zero-dependency cross-file unused function/class suppression
  - Builds a name index over every `.py` file in the current run (imports, attribute access, identifier strings, `__all__`)
  - Drops `unused_function` / `unused_class` warnings when the name is referenced in another file
  - Default remains per-file (conservative, cheap, single-pass)
  - Config key: `project = true` under `[tool.pystreamliner]` / `.pystreamliner.toml`
  - Not a full import resolver — name-based only; `import *` and dynamic getattr stay out of scope

### Changed
- README Limitations section now documents `--project` as the opt-in fill for the per-file unused gap

### Fixed
- Removed unused `hashlib` import (cache fingerprint is size+mtime; hashlib was dead)

## [1.20.0] - 2026-08-31

### Added
- **SARIF 2.1.0 output** via `--sarif`
  - Machine-readable results for GitHub Code Scanning, VS Code SARIF viewers, and CI security dashboards
  - Rule IDs under the `PYS/` namespace (e.g. `PYS/dangerous_call`, `PYS/hardcoded_secret`)
  - Severity levels mapped per category (`error` / `warning` / `note`)
  - Locations include `startLine`
- **Mtime cache** via `--cache` / `--cache-file`
  - Skips files whose size + mtime fingerprint matches the last run
  - Default cache file: `.pystreamliner_cache.json`
  - Ideal for repeated local cleans and editor "run on save" workflows
- **`--threads`**
  - Use `ThreadPoolExecutor` instead of processes when `-j` > 1 (lower spawn overhead on many small files)
- Richer **`--json`** payload now includes `import_details` (what was removed or partially cleaned)

### Changed
- **Safer parallel default**: `-j` / `--jobs` now defaults to **1** (sequential)
  - Use `-j 0` for auto parallelism (capped at 4 workers)
  - Avoids ProcessPool spawn tax and hangs on small trees / constrained environments
- **Combined AST walk** in `SourceAnalyzer`
  - Used names, `__all__`, assignments, dangerous calls, secrets, asserts, and broad excepts collected in a single `ast.walk`
  - Fewer full-tree passes → less work per file
- Module docstring and CLI help updated for cache, SARIF, threads, and jobs semantics
- Config keys: `cache`, `cache_file` are now recognized

### Fixed
- Parallel mode no longer defaults to full `cpu_count()` process pool (was a foot-gun on small projects)

## [1.19.1] - 2026-08-29

### Fixed
- **Directory ignore no longer skips an explicitly given path** that happens to be named like a junk directory (e.g. `pystreamliner coverage/`). Only *sub*-directories matching the ignore list are skipped. This fixes the “No Python files found” report when the user intentionally points at a folder named `coverage`, `htmlcov`, etc.
- **Detailed reports again list every warning message** (grouped by category) and the exact unused-import lines that were removed. The previous simplified printer only showed counts.

### Added
- README section **“Limitations / By design”** that clearly documents:
  - Unused function/class detection is strictly per-file (no cross-module analysis). This is intentional.
  - How the directory ignore list interacts with explicitly passed paths.
  - When summary mode vs full reports are used.

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
  - Analysis is fully parallel; file writes remain sequential for safety
- **Unused class detection** (Tier 2, category `unused_class`)
- Attribute name tracking in used-name collection so methods called via `obj.method()` / `self.foo()` are no longer false-positived as unused

### Fixed
- Major false-positive on methods and attribute-accessed callables

### Changed
- Report printer now includes "Unused classes detected" count and detail section
- Module docstring updated to mention parallel support

## [1.17.0] - 2026-08-19

### Added
- **Multi-file and recursive directory support**
- **Tight summary mode for large runs** (`--summary-threshold`, default 5)

### Changed
- CLI argument renamed from `file` to `paths`

## [1.16.0] - 2026-08-15

### Added
- Tier-2 security detectors: dangerous calls, hardcoded secrets, assert, broad except
- Warning categories: `dangerous_call`, `hardcoded_secret`, `assert_used`, `broad_except`

## [1.15.0] - 2026-08-04

### Added
- `--check`, `--quiet`, `--json`, `--fix-only`, `--select` / `--ignore`, `--stdin`, `--aggressive`

## [1.14.0] - 2026-08-04

### Changed
- Raised minimum Python version to 3.13

## [1.13.1] - 2026-07-28

### Added
- `--warn-only` flag

## [1.12.1] - 2026-07-17

### Added
- `[project.urls]` metadata

## [1.12.0] - 2026-07-17

### Added
- Native PyPI Trusted Publishing (OIDC) support

## [1.11.0] - 2026-06-30

### Added
- Install support via git+https

## [1.10.0] - 2026-06-29

### Added
- Core CLI flags and shadowed builtins detection

## [1.0.0] - 2026-03-04

### Added
- Initial release
