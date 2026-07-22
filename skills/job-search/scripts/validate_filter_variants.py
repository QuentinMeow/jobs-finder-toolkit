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
REPO_ROOT = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from filter_variants import (  # noqa: E402
    CORPUS_PATH,
    audit_postings,
    check_corpus,
    first_reject_census,
    lint_corpus,
    load_corpus,
)
from common import parse_dt  # noqa: E402


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
    parser.add_argument("--census-out", type=Path,
                        help="first-reject census YAML path (default: "
                             "tmp/filter_variant_reports/<snapshot>-census.yaml)")
    parser.add_argument("--census-sample-size", type=int, default=5,
                        help="bounded deterministic sample size per reject family "
                             "(default: 5)")
    parser.add_argument("--max-age-days", type=float,
                        help="replay the production posting-age gate; defaults to "
                             "the profile's max_age_days")
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
        max_age = (args.max_age_days if args.max_age_days is not None
                   else profile.get("max_age_days"))
        snapshot_now = parse_dt(snapshot.get("fetched_at"))
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"SNAPSHOT ERROR: {exc}", file=sys.stderr)
        return 2

    # First-reject census (Decision 3b): report every hard `no_match`, grouped
    # by rule family, with a bounded deterministic sample — the audit below only
    # ever sees `review` rows, so this is the only artifact that speaks to
    # false-negative recall at the hard gates.
    census = first_reject_census(
        postings, profile, sample_size=args.census_sample_size,
        max_age=max_age, now=snapshot_now)
    census_out = args.census_out or (
        REPO_ROOT / "tmp" / "filter_variant_reports"
        / f"{args.snapshot.stem}-census.yaml")
    census_out.parent.mkdir(parents=True, exist_ok=True)
    census_out.write_text(yaml.safe_dump({
        "schema_version": 1,
        "source_snapshot": str(args.snapshot),
        "profile": str(profile_ref),
        "max_age_days": max_age,
        **census,
    }, sort_keys=False, allow_unicode=True, width=120))
    print(
        f"First-reject census: {census['total_rejected']} of {len(postings)} "
        f"postings hard-rejected across {len(census['families'])} rule "
        f"famil{'y' if len(census['families']) == 1 else 'ies'} -> {census_out}",
        file=sys.stderr,
    )

    pending = audit_postings(
        postings, profile, corpus, max_age=max_age, now=snapshot_now)
    if not pending:
        print(f"snapshot audit clean: {len(postings)} postings, no new variants")
        return 0

    out = args.out or _default_report(args.snapshot)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump({
        "schema_version": 1,
        "source_snapshot": str(args.snapshot),
        "profile": str(profile_ref),
        "max_age_days": max_age,
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
