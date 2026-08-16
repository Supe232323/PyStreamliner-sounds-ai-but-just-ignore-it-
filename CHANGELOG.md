# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com).

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
