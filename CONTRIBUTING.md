# contributing to pystreamliner

thanks for considering a contribution. bug fixes, new detection rules, and documentation improvements are all welcome.

---

## how to contribute

1. **fork the repository**
2. **create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **make your changes**
4. **test against a messy python file** to make sure nothing breaks
5. **open a pull request** with a short description of what you changed and why

---

## what we accept
- new tier 2 detection rules (unused code patterns, naming issues, etc.)
- improvements to existing analysis logic
- bug fixes
- documentation improvements
- performance enhancements

if you're unsure whether something fits, open an issue first and ask.

---

## what we don't accept

- auto-fixes that could change program behavior
- dependencies (pystreamliner is intentionally zero-dependency)
- anything that requires python < 3.13+

---

## code style

- follow PEP 8
- add docstrings to new classes and methods
- if you're adding a new detection rule, include a before/after example in your pr description

---

## questions?

open an issue or ask directly in the pull request. all feedback is appreciated.
