"""gardener routine: cross-validate baseline-resume skills against the profile.

The resume-writer treats the profile markdown's ``## Skills`` section (its
``### Approved`` / ``### Weak`` / ``### Never`` subsections) as the CANONICAL skill
vocabulary, and ``check.py`` gates every tailored resume against it at render time.
The baseline resume (``config.paths.baseline_yaml``) is the master a tailored resume
is derived from, but its Skills-section tokens are hand-maintained and can drift out
of the canonical spelling — e.g. "Distributed System" vs the canonical "Distributed
Systems". A non-canonical baseline spelling then only surfaces mid-render, wasting a
render cycle.

This routine reads the baseline's skill tokens and flags any whose spelling is not
in the profile's canonical Skills lists, so the drift is caught during upkeep
instead of at render time.

REPORT-ONLY (no ``--apply``): fixing the spelling — in the baseline or by adding the
skill to the profile lists — is a human edit, not the gardener's. Exits 0 always (it
informs; ``verify-links`` remains the ``--all`` gate). Degrades gracefully: with the
baseline or profile file absent (e.g. no overlay mounted), it reports "nothing to
check" and still exits 0.

Usage:
    .venv/bin/python automation/gardener/skill_drift.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

try:
    import config  # noqa: E402  (bootstrapped onto sys.path by _common)
except ImportError:  # pragma: no cover
    config = C.config

# The profile's '## Skills' vocabulary is parsed in exactly ONE place. This module
# and the render-time gate (skills/resume-writer/scripts/check.py, through its
# vendored copy) used to carry their own section regexes, and the two boundaries
# differed — check.py's lacked the ``\Z`` alternative, so it read an EMPTY
# vocabulary from any profile whose '## Skills' was the last '##' section while
# this routine reported the same bytes as fine. See automation/shared/profile_skills.py.
from profile_skills import (canonical_keys,  # noqa: E402,F401  (re-exported)
                            norm_spelling as _norm, split_items as _split_items)


def baseline_tokens(baseline_text: str) -> list[tuple[str, str]]:
    """(label, token) pairs from a baseline resume YAML's ``skills:`` entries."""
    try:
        data = yaml.safe_load(baseline_text) or {}
    except yaml.YAMLError:
        return []
    out: list[tuple[str, str]] = []
    for entry in (data.get("skills") or []):
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("label", "")).strip()
        for tok in _split_items(str(entry.get("items", ""))):
            out.append((label, tok))
    return out


def find_drift(baseline_path: Path, profile_path: Path) -> dict:
    """Compare baseline skill tokens to the profile's canonical spellings.

    Pure and path-injected so it is testable without the config layer. ``drift`` is
    the baseline tokens whose normalized spelling is not in the canonical set.
    """
    result = {
        "baseline": baseline_path,
        "profile": profile_path,
        "baseline_exists": baseline_path.is_file(),
        "profile_exists": profile_path.is_file(),
        "canonical_available": False,
        "checked": 0,
        "drift": [],
    }
    if not (result["baseline_exists"] and result["profile_exists"]):
        return result
    canon = canonical_keys(profile_path.read_text(encoding="utf-8"))
    result["canonical_available"] = bool(canon)
    tokens = baseline_tokens(baseline_path.read_text(encoding="utf-8"))
    result["checked"] = len(tokens)
    if not canon:
        return result
    result["drift"] = [
        {"label": label, "token": tok}
        for label, tok in tokens
        if _norm(tok) not in canon
    ]
    return result


def analyze() -> dict:
    return find_drift(config.baseline_path(), config.profile_md_path())


def run(apply: bool = False) -> int:
    C.print_header("skill-drift (report-only)", apply=False)
    res = analyze()
    print(f"  baseline: {C.rel(res['baseline'])}")
    print(f"  profile:  {C.rel(res['profile'])}")
    missing = [name for name, ok in (("baseline", res["baseline_exists"]),
                                     ("profile", res["profile_exists"])) if not ok]
    if missing:
        print(f"  {', '.join(missing)} not available — nothing to check.")
        return 0
    if not res["canonical_available"]:
        print("  profile has no '## Skills' canonical lists — nothing to validate.")
        return 0
    if res["drift"]:
        print(f"  DRIFT: {len(res['drift'])} baseline skill token(s) are not in the "
              "profile's canonical Skills lists (non-canonical spelling?):")
        for d in res["drift"]:
            label = f"{d['label']}: " if d["label"] else ""
            print(f"    DRIFT  {label}{d['token']!r}")
        print("  (report-only — fix the baseline spelling to match the profile, or "
              "add the skill to the profile's Skills lists.)")
    else:
        print(f"  clean — all {res['checked']} baseline skill token(s) are canonical.")
    return 0


def main(argv=None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
