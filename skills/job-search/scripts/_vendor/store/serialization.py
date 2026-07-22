"""The one canonical serializer — sorted keys, pinned floats, LF, UTC ``Z``.

Everything that writes derived/index/state goes through this module so a rebuild
is byte-identical across machines. The determinism pins (from the store-core
determinism contract):

- sorted keys everywhere;
- LF line endings and a trailing newline;
- UTC timestamps formatted ``YYYY-MM-DDTHH:MM:SSZ`` (second precision, ``Z``);
- floats via Python's shortest round-trip ``repr`` (platform-stable) and NaN/Inf
  refused, so a value that cannot be pinned is a loud error, not silent drift.

There is deliberately no wall-clock read here: build-time metadata belongs in the
``state/`` ledger (excluded from determinism comparisons), never in a derived
artifact.
"""
from __future__ import annotations

import datetime as _datetime
import json
from datetime import datetime, timezone
from typing import Any

import yaml

# ── timestamps ───────────────────────────────────────────────
_Z_FMT = "%Y-%m-%dT%H:%M:%SZ"
_COMPACT_FMT = "%Y%m%dT%H%M%SZ"


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_z(dt: datetime) -> str:
    """Format an (aware or naive-as-UTC) datetime as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return _as_utc(dt).strftime(_Z_FMT)


def to_compact(dt: datetime) -> str:
    """Format a datetime as the compact ``YYYYMMDDTHHMMSSZ`` used in fetch ids."""
    return _as_utc(dt).strftime(_COMPACT_FMT)


def parse_z(text: str) -> datetime:
    """Parse a canonical ``...Z`` timestamp back to an aware UTC datetime."""
    return datetime.strptime(text, _Z_FMT).replace(tzinfo=timezone.utc)


def now_z() -> str:
    """Current UTC time as a canonical ``...Z`` string."""
    return to_z(datetime.now(timezone.utc))


# ── canonical dumps ──────────────────────────────────────────
def _check_finite(obj: Any) -> None:
    """Refuse NaN/Inf anywhere in ``obj`` (they have no pinned representation)."""
    if isinstance(obj, float):
        if obj != obj or obj in (float("inf"), float("-inf")):
            raise ValueError("non-finite float cannot be serialized canonically")
    elif isinstance(obj, dict):
        for v in obj.values():
            _check_finite(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _check_finite(v)


def dumps_json(obj: Any) -> str:
    """Pretty canonical JSON (sorted keys, 2-space indent, trailing LF)."""
    _check_finite(obj)
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2,
                      allow_nan=False) + "\n"


def dumps_jsonl_line(obj: Any) -> str:
    """A single compact canonical JSONL line (sorted keys, LF-terminated)."""
    _check_finite(obj)
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False) + "\n"


def loads_json(text: str) -> Any:
    return json.loads(text)


class _CanonicalDumper(yaml.SafeDumper):
    """SafeDumper that keeps our determinism pins explicit."""


def _represent_str(dumper: yaml.Dumper, data: str):
    # Force block scalars off; keep plain/quoted decision to PyYAML but never emit
    # aliases (handled below). Multi-line strings still serialize deterministically.
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_CanonicalDumper.add_representer(str, _represent_str)


def dumps_yaml(obj: Any) -> str:
    """Canonical YAML: sorted keys, block style, no aliases, unicode kept, LF."""
    _check_finite(obj)
    text = yaml.dump(
        obj,
        Dumper=_CanonicalDumper,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
    )
    # PyYAML always ends with a newline; normalize just in case.
    if not text.endswith("\n"):
        text += "\n"
    return text


def loads_yaml(text: str) -> Any:
    return yaml.safe_load(text)


# Aliases must never appear (they would make output depend on object sharing).
_CanonicalDumper.ignore_aliases = lambda self, data: True  # type: ignore[assignment]
