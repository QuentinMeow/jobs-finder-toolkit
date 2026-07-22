# `_vendor/` — generated, do not edit

This folder holds **byte-identical vendored copies** of pure repo-toolkit modules
so the `resume-writer` skill stays self-contained (Approach 2): its scripts import
their local copy here instead of reaching into the repo-root toolkit.

| Vendored copy | Canonical source (edit here) |
|---------------|------------------------------|
| `config.py`   | `automation/shared/config.py`   |
| `layout.py`   | `automation/shared/layout.py`   |
| `location.py` | `automation/shared/location.py` |
| `job_metadata.py` | `automation/shared/job_metadata.py` |

## Rules

- **Never edit files in this folder** (except this README and `__init__.py`). They
  are generated.
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
from layout import application_dir, find_jd_files
from location import classify_locations, is_match
```
