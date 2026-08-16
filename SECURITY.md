# Security Policy

## Supported Versions

Only the latest release is supported. Older versions do not receive security updates.

| Version   | Supported          |
| --------- | ------------------ |
| v1.16.0   | :white_check_mark: |
| < v1.16.0 | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, **do not open a public issue**.

Please report it privately by contacting the maintainer directly. Include:

- A clear description of the issue
- Steps to reproduce
- Potential impact

Once notified, the repository may be temporarily made private while a fix is prepared. Always use the latest release.

## Scope

pystreamliner is a local, zero-dependency source code analysis tool. It does not make network requests, execute analyzed code, or process untrusted input beyond reading the files you explicitly point it at. The main risks are the normal ones associated with any CLI tool that can rewrite files (use `--dry-run` when unsure).
