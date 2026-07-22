# `_vendor/` — generated, do not edit

This folder holds **byte-identical vendored copies** of pure repo-toolkit modules
so the `job-search` skill stays self-contained (Approach 2): its scripts import
their local copy here instead of reaching into the repo-root toolkit.

| Vendored copy | Canonical source (edit here) |
|---------------|------------------------------|
| `location.py` | `scripts/shared/location.py` |
| `config.py` | `scripts/shared/config.py` |
| `layout.py` | `scripts/shared/layout.py` |
| `job_metadata.py` | `scripts/shared/job_metadata.py` |
| `metadata_editor.py` | `scripts/shared/metadata_editor.py` |
| `store/` (directory) | `scripts/shared/store/` |

The `store/` entry is a whole **directory** mirror (the raw-data-layer store
library, imported as `from _vendor.store import ...`); the sync mirrors it
recursively, byte-identical per file, dropping `__pycache__`/`*.pyc`.

## Rules

- **Never edit files in this folder** (except this README and `__init__.py`). They
  are generated.
- To change vendored logic: edit the **canonical source**, then regenerate:

  ```bash
  .venv/bin/python scripts/vendoring/sync_vendored.py
  ```

- A drift check keeps the copies honest (run by the pre-commit hook):

  ```bash
  .venv/bin/python scripts/vendoring/sync_vendored.py --check
  ```

Skill scripts import the vendored module locally, e.g.:

```python
from _vendor.location import classify_location, is_match
```
