#!/usr/bin/env python3
"""Offline-lint the registry and validate selected company boards are reachable.

By default this validates only ordinary unbatched entries. Large expansions carry
``poll_batch`` and must be checked explicitly with ``--batch`` (or, deliberately,
``--all-batches``).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import sys
from pathlib import Path

import yaml

from registry import Registry, lint_entries
from sources import fetch_company

SKILL_DIR = Path(__file__).resolve().parents[1]


def _fetch(entry: dict) -> tuple[int, str, int | None, str | None]:
    try:
        return 0, entry["name"], len(fetch_company(entry)), None
    except Exception as exc:  # noqa: BLE001
        return 1, entry.get("name", "?"), None, str(exc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lint-only", action="store_true",
                    help="Run deterministic offline schema/identity checks only.")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--batch",
                       help="Comma-separated poll_batch values to validate.")
    group.add_argument("--all-batches", action="store_true",
                       help="Validate every pollable row, including opt-in batches.")
    ap.add_argument("--workers", type=int, default=8,
                    help="Maximum concurrent board requests (default: %(default)s).")
    args = ap.parse_args(argv)

    registry = yaml.safe_load((SKILL_DIR / "companies.yaml").read_text()) or {}
    all_entries = registry.get("companies", [])
    lint_errors = lint_entries(all_entries)
    if lint_errors:
        for error in lint_errors:
            print(f"LINT {error}")
        print(f"\nRegistry lint failed with {len(lint_errors)} error(s).")
        return 1
    print(f"LINT OK   {len(all_entries)} registry entries")
    if args.lint_only:
        return 0

    loaded = Registry(all_entries)
    if args.all_batches:
        companies = [
            c for c in all_entries if isinstance(c, dict) and c.get("ats")
        ]
    else:
        batches = args.batch.split(",") if args.batch else None
        companies = loaded.poll_companies(batches=batches)
    if args.batch and not companies:
        print(f"No pollable companies matched --batch {args.batch!r}.")
        return 1
    skipped = len(all_entries) - len(companies)
    workers = max(1, min(args.workers, 32))
    results: list[tuple[int, str, int | None, str | None] | None] = [
        None
    ] * len(companies)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch, company): index
            for index, company in enumerate(companies)
        }
        for future in concurrent.futures.as_completed(futures):
            results[futures[future]] = future.result()

    bad = 0
    for company, result in zip(companies, results):
        assert result is not None
        failed, name, count, error = result
        if failed:
            bad += 1
            print(f"FAIL {name:<18} {company['ats']}:{company['token']}  {error}")
        else:
            status = "OK  " if count else "EMPTY"
            print(
                f"{status} {name:<18} {company['ats']}:{company['token']}  "
                f"({count} jobs)"
            )
    print(f"\n{len(companies) - bad}/{len(companies)} companies reachable"
          + (f" ({skipped} unselected/identity-only rows skipped)." if skipped else "."))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
