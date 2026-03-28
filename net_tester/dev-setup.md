# Dev setup

Run `dev-setup` from the repo root. This creates `net_tester.venv` and installs pre-commit hooks.

```bash
./dev-setup
cd net_tester && uv run python coordinator.py [--dry-run] [--verbose]
```
