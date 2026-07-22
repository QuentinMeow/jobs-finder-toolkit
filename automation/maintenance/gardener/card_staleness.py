"""gardener routine: flag a stale tailoring card (derived artifact vs its sources).

The resume-writer skill compiles a distilled *tailoring card* at
``<applications_root>/0_profile/tailoring-card.md`` from the profile, baseline, and
story bank (``build_tailoring_card.py``). The card is a DERIVED artifact: its header
records each source's SHA-256, so it can silently go stale when a source changes.

This routine recomputes the current source hashes and compares them to the hashes the
card recorded, flagging the card when any source has drifted. It mirrors the build
script's own ``--check`` (same hashing + header format) so the two never disagree.

REPORT-ONLY (no ``--apply``): rebuilding the card is the skill's job, not the gardener's
— a stale flag is surfaced for the human to rebuild with
``build_tailoring_card.py --force``. Exits 0 always (it informs; ``verify-links`` remains
the ``--all`` gate).

Usage:
    .venv/bin/python automation/maintenance/gardener/card_staleness.py
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    import config  # noqa: E402  (bootstrapped onto sys.path by _common)
except ImportError:  # pragma: no cover
    config = C.config

STORY_BANK_REL = "interviews/behavioral-story-bank"
CARD_REL = "0_profile/tailoring-card.md"
BUILD_CMD = "skills/resume-writer/scripts/build_tailoring_card.py"
SOURCE_LINE_RE = re.compile(r"- `([^`]+)` sha256:([0-9a-f]{64})")


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes() if path.is_file() else b"").hexdigest()


def _story_bank_hash(story_dir: Path) -> str:
    h = hashlib.sha256()
    files = sorted(story_dir.glob("*.md")) if story_dir.is_dir() else []
    for f in files:
        h.update(f.name.encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _display(p: Path, config_dir: Path) -> str:
    p = p.resolve()
    for base in (config_dir.resolve(), C.REPO_ROOT.resolve()):
        try:
            return p.relative_to(base).as_posix()
        except ValueError:
            continue
    return p.name


def analyze() -> dict:
    config_dir = config.config_path().parent
    profile = config.profile_md_path()
    baseline = config.baseline_path()
    # Resolve the story bank from the overlay root (applications_root().parent), NOT the
    # config file's directory — config.yaml sits at the repo root in the real deployment
    # while the overlay is mounted at private/. This mirrors build_tailoring_card.py so
    # the two never disagree on which story bank the card was built from.
    story_dir = config.applications_root().parent / STORY_BANK_REL
    card = config.applications_root() / CARD_REL

    current = {
        _display(profile, config_dir): _file_sha(profile),
        _display(baseline, config_dir): _file_sha(baseline),
        STORY_BANK_REL + "/": _story_bank_hash(story_dir),
    }
    result = {"card": card, "config_dir": config_dir, "exists": card.is_file(),
              "changed": []}
    if not card.is_file():
        return result
    recorded = {m.group(1): m.group(2)
                for m in SOURCE_LINE_RE.finditer(card.read_text(encoding="utf-8"))}
    changed = [d for d, sha in current.items() if recorded.get(d) != sha]
    changed += [d for d in recorded if d not in current]
    result["changed"] = sorted(set(changed))
    return result


def run(apply: bool = False) -> int:
    C.print_header("card-staleness (report-only)", apply=False)
    res = analyze()
    print(f"  card: {C.rel(res['card'])}")
    if not res["exists"]:
        print("  not built yet — nothing to check (build with build_tailoring_card.py).")
        return 0
    if res["changed"]:
        print(f"  STALE: {len(res['changed'])} source(s) changed since the card was built:")
        for d in res["changed"]:
            print(f"    STALE  {d}")
        print(f"  (report-only — rebuild with `{BUILD_CMD} --force` after review)")
    else:
        print("  current — card matches its recorded source hashes.")
    return 0


def main(argv=None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
