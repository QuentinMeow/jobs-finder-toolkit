"""Validate a raw-data-layer store: schemas, blob states, fixture size.

Walks a data root, validates every artifact it recognizes against the matching
JSON Schema (dispatching group vs. member manifests), and reports the four blob
availability states. ``not-synced-here`` (manifest present, blob absent, no
tombstone) is INFORMATIONAL — normal on the owner's multi-laptop, manually-synced
setup — never a failure; only a ``corrupt`` blob or a schema violation fails.

The data root is the positional argument, or (when omitted) ``config.data_root()``;
if neither is available the tool prints "store not configured" and exits 0.

Usage:
    .venv/bin/python automation/store/validate_store.py examples/data
    .venv/bin/python automation/store/validate_store.py examples/data --check-fixture-size
    .venv/bin/python automation/store/validate_store.py            # uses config.data_root()
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

import config  # noqa: E402
from store import blobs as _blobs  # noqa: E402
from store import validation  # noqa: E402


def _resolve_root(arg: str | None) -> Path | None:
    if arg:
        return Path(arg).expanduser().resolve()
    return config.data_root()


def _print_report(report: validation.StoreReport) -> None:
    print("Store validation")
    print(f"  data root:  {report.root}")
    counts = ", ".join(f"{k}: {v}" for k, v in sorted(report.counts.items()))
    print(f"  artifacts:  {counts or '(none recognized)'}")
    if report.blob_states:
        states = ", ".join(f"{k}: {v}" for k, v in sorted(report.blob_states.items()))
        print(f"  blob states: {states}")
        nsh = report.blob_states.get(_blobs.NOT_SYNCED_HERE, 0)
        if nsh:
            print(f"  note: {nsh} blob(s) not-synced-here (informational; "
                  f"manual raw sync remedy)")
    for info in report.infos:
        print(f"  info: {info}")
    if report.ok:
        print("OK: store is valid.")
    else:
        print(f"FAIL: {len(report.errors)} error(s):")
        for err in report.errors:
            print(f"  - {err}")


def _check_size(root: Path) -> None:
    size = validation.check_fixture_size(root)
    kb = size.total_bytes / 1024
    limit_kb = size.limit_bytes / 1024
    if size.over:
        print("=" * 70, file=sys.stderr)
        print(f"WARNING: fixture store {root} is {kb:.1f} KB, over the "
              f"{limit_kb:.0f} KB soft threshold ({size.limit_source}).",
              file=sys.stderr)
        print("  This is a soft threshold, NOT a hard block (exit 0). If the "
              "growth is deliberate,", file=sys.stderr)
        print(f"  a human may raise it via a visible "
              f"{validation.FIXTURE_SIZE_OVERRIDE_FILENAME} file in the data root.",
              file=sys.stderr)
        print("=" * 70, file=sys.stderr)
    else:
        print(f"fixture size OK: {kb:.1f} KB / {limit_kb:.0f} KB soft threshold "
              f"({size.limit_source})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("data_root", nargs="?", default=None,
                        help="store data root (default: config.data_root())")
    parser.add_argument("--check-fixture-size", action="store_true",
                        help="also check the soft size threshold (warn, never fail)")
    args = parser.parse_args(argv)

    root = _resolve_root(args.data_root)
    if root is None:
        print("store not configured (set paths.data_root or JOBHUNT_DATA_ROOT); "
              "nothing to validate.")
        return 0

    report = validation.validate_store(root)
    _print_report(report)
    if args.check_fixture_size:
        _check_size(root)  # soft threshold: warns, never changes the exit code
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
