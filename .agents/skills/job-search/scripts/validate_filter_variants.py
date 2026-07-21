"""Validate labeled filter variants and audit a private posting snapshot.

Known corpus cases are deterministic and AI-free. Snapshot audit exits nonzero
when new signal-bearing shapes need a human/agent label; normal search itself
continues and preserves those rows in its review report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from filter_variants import (  # noqa: E402
    CORPUS_PATH,
    audit_postings,
    check_corpus,
    lint_corpus,
    load_corpus,
)


def _profile_path(value: str) -> Path:
    direct = Path(value)
    if direct.is_file():
        return direct
    candidate = HERE.parent / "profiles" / (
        value if value.endswith(".yaml") else f"{value}.yaml")
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"profile not found: {value}")


def _load_profile(value: str) -> dict:
    data = yaml.safe_load(_profile_path(value).read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"profile must be a mapping: {value}")
    return data


def _default_report(snapshot_path: Path) -> Path:
    return (
        REPO_ROOT / "tmp" / "filter_variant_reports"
        / f"{snapshot_path.stem}-unknown.yaml"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--lint-only", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="run every labeled corpus case (default without snapshot)")
    parser.add_argument("--snapshot", type=Path,
                        help="audit a full private pre-filter snapshot")
    parser.add_argument("--profile",
                        help="profile label/path; defaults to snapshot.profile")
    parser.add_argument("--out", type=Path,
                        help="pending YAML path (default: tmp/filter_variant_reports/)")
    args = parser.parse_args(argv)

    corpus = load_corpus(args.corpus)
    errors = lint_corpus(corpus)
    if not args.lint_only:
        errors = check_corpus(corpus)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    if args.lint_only:
        print(f"filter variant corpus lint clean: {len(corpus['variants'])} cases")
        return 0

    print(f"filter variant corpus clean: {len(corpus['variants'])} cases")
    if args.snapshot is None:
        return 0

    try:
        snapshot = json.loads(args.snapshot.read_text())
        postings = snapshot.get("postings")
        if not isinstance(postings, list):
            raise ValueError("snapshot.postings must be a list")
        profile_ref = args.profile or snapshot.get("profile")
        if not profile_ref:
            raise ValueError("provide --profile; snapshot has no profile")
        profile = _load_profile(str(profile_ref))
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"SNAPSHOT ERROR: {exc}", file=sys.stderr)
        return 2

    pending = audit_postings(postings, profile, corpus)
    if not pending:
        print(f"snapshot audit clean: {len(postings)} postings, no new variants")
        return 0

    out = args.out or _default_report(args.snapshot)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump({
        "schema_version": 1,
        "source_snapshot": str(args.snapshot),
        "profile": str(profile_ref),
        "unknown_count": len(pending),
        "pending": pending,
    }, sort_keys=False, allow_unicode=True, width=120))
    for item in pending:
        print(
            f"UNKNOWN {item['domain']} {item['signature']} "
            f"x{item['count']}: {item['id']}",
            file=sys.stderr,
        )
    print(
        f"Snapshot has {len(pending)} unlabeled structural variant(s); "
        f"review -> {out}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
