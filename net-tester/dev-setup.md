````
# Dev Setup for net-tester Project (macOS)

This document contains the confirmed working steps to set up the development environment for the `net-tester` project using `uv` and a Python 3.11 venv.

---

## 1. Clean any previous virtual environment

```bash
rm -rf .venv
```

## 2. Ensure uv-managed Python 3.11 is available

```bash
uv python install 3.11.8  # if not already installed
uv python use 3.11.8       # set for this project/session
```

## 3. Create a new venv in the project

```bash
uv venv create .venv --python 3.11.8
source .venv/bin/activate
```

At this point:
```bash
python --version  # should show Python 3.11.8
```

## 4. Upgrade core packaging tools

```bash
uv pip install --upgrade pip wheel setuptools
```

Check versions:
```bash
python -m pip --version
```

## 5. Install project dependencies

```bash
uv pip install rich deepdiff
```

Verify packages installed:
```bash
python -m pip list
```

## 6. Run the project (dry-run recommended first)

```bash
python modnettest.py --dry-run --verbose
```

## 7. Additional uv pip usage notes

- Install new dependency: `uv pip install <package>`
- Upgrade existing: `uv pip install --upgrade <package>`
- Remove a package: `uv pip remove <package>`

---

This sequence ensures a clean, consistent development environment using Python 3.11 and uv, avoiding issues with mismatched system Python versions.
````
