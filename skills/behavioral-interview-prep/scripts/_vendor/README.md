# `_vendor/` — generated, do not edit

This folder holds **byte-identical vendored copies** of pure repo-toolkit modules
so the `behavioral-interview-prep` skill stays self-contained (Approach 2): its
scripts import their local copy here instead of reaching into the repo-root toolkit.

| Vendored copy | Canonical source (edit here) |
|---------------|------------------------------|
| `config.py`   | `automation/shared/config.py`   |
| `layout.py`   | `automation/shared/layout.py`   |

`answer_bank.py` needs `config.companies_root()` to file a company-prefixed answer
alias under its company folder. `layout.py` is here only because `config.py`
imports it.

## Rules

- **Never edit files in this folder** (except this README). They are generated.
- To change vendored logic: edit the **canonical source**, then regenerate:

  ```bash
  .venv/bin/python automation/vendoring/sync_vendored.py
  ```

- A drift check keeps the copies honest (run by the pre-commit hook):

  ```bash
  .venv/bin/python automation/vendoring/sync_vendored.py --check
  ```

Skill scripts import the vendored modules locally (the script folder and its
`_vendor/` are on `sys.path`), e.g.:

```python
import config
```
