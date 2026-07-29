"""gardener routine: LESSONS.md health report (staleness + near-duplicates).

Durable memory (AGENTS.md "Memory Map" zone (c)) carries lifecycle tags per ``##`` section
(``<!-- added · last_confirmed · status -->``). This routine:

  * flags sections whose ``last_confirmed`` is older than ``lesson_confirm_days``
    (default 180) or that carry no lifecycle tag — candidates for demotion/removal;
  * flags near-duplicate bullets by normalized token overlap, both WITHIN each
    LESSONS.md and BETWEEN a LESSONS.md and its sibling SKILL.md (a bullet already
    covered by the instructions is a promotion/merge candidate).

REPORT-ONLY: there is no ``--apply``. Promotion into SKILL.md and any deletion are
human-reviewed per the self-evolution quality-control contract (README quality box:
"promotion requires a separate human-reviewed commit"). Exits 0 always (it informs,
it does not gate).

Usage:
    .venv/bin/python automation/maintenance/gardener/lessons_report.py
    .venv/bin/python automation/maintenance/gardener/lessons_report.py --threshold 0.7
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

DEFAULT_THRESHOLD = 0.5  # Jaccard similarity (see _common.overlap)


def _skill_bullets(skill_md: Path) -> list[str]:
    if not skill_md.is_file():
        return []
    out: list[str] = []
    for line in skill_md.read_text(encoding="utf-8").splitlines():
        s = line.lstrip()
        if s.startswith("- ") or re.match(r"^\d+\.\s", s):
            out.append(re.sub(r"^\d+\.\s", "", s[2:] if s.startswith("- ") else s).strip())
    return out


def analyze(threshold: float) -> dict:
    policy = C.retention()
    confirm_days = policy["lesson_confirm_days"]
    ref = C.today()
    report: list[dict] = []
    for lessons in C.lessons_files():
        skill_md = lessons.parent / "SKILL.md"
        sections = C.parse_lessons(lessons)
        skill_bullets = [(b, C.tokenize(b)) for b in _skill_bullets(skill_md)]

        stale: list[dict] = []
        untagged: list[str] = []
        for sec in sections:
            if sec["status"] is None:
                untagged.append(sec["heading"])
                continue
            d = C.parse_iso(sec["confirmed"])
            age = (ref - d).days if d else None
            if age is not None and age > confirm_days:
                stale.append({"heading": sec["heading"], "confirmed": sec["confirmed"],
                              "age": age})

        # Bullet-level near-duplicate detection.
        bullets: list[tuple[str, str, set[str]]] = []  # (heading, text, tokens)
        for sec in sections:
            for b in sec["bullets"]:
                bullets.append((sec["heading"], b, C.tokenize(b)))
        intra: list[tuple] = []
        for i in range(len(bullets)):
            for j in range(i + 1, len(bullets)):
                o = C.overlap(bullets[i][2], bullets[j][2])
                if o >= threshold:
                    intra.append((o, bullets[i], bullets[j]))
        cross: list[tuple] = []
        for _, text, toks in bullets:
            for sb_text, sb_toks in skill_bullets:
                o = C.overlap(toks, sb_toks)
                if o >= threshold:
                    cross.append((o, text, sb_text))

        report.append({
            "lessons": lessons, "skill_md": skill_md, "sections": len(sections),
            "stale": stale, "untagged": untagged,
            "intra": sorted(intra, key=lambda x: -x[0]),
            "cross": sorted(cross, key=lambda x: -x[0]),
        })
    return {"confirm_days": confirm_days, "threshold": threshold, "report": report}


def run(threshold: float = DEFAULT_THRESHOLD) -> int:
    C.print_header("lessons-report (report-only)", apply=False)
    res = analyze(threshold)
    print(f"  confirm horizon: {res['confirm_days']}d · "
          f"duplicate overlap threshold: {res['threshold']:.2f}\n")
    tot_stale = tot_untagged = tot_intra = tot_cross = 0
    for r in res["report"]:
        print(f"  {C.rel(r['lessons'])}  ({r['sections']} sections)")
        if r["stale"]:
            tot_stale += len(r["stale"])
            for s in r["stale"]:
                print(f"    STALE   '{s['heading']}' last_confirmed {s['confirmed']} "
                      f"({s['age']}d)")
        if r["untagged"]:
            tot_untagged += len(r["untagged"])
            for h in r["untagged"]:
                print(f"    NO-TAG  '{h}' (add a lifecycle tag)")
        for o, a, b in r["intra"]:
            tot_intra += 1
            print(f"    DUP@{o:.2f} within: [{a[0]}] {a[1][:60]!r} ~ [{b[0]}] {b[1][:60]!r}")
        for o, text, sb in r["cross"]:
            tot_cross += 1
            print(f"    DUP@{o:.2f} vs SKILL: {text[:60]!r} ~ {sb[:60]!r}")
        if not (r["stale"] or r["untagged"] or r["intra"] or r["cross"]):
            print("    ok — tagged, fresh, no near-duplicates")
    print(f"\n  totals: stale {tot_stale} · untagged {tot_untagged} · "
          f"intra-dup {tot_intra} · vs-SKILL-dup {tot_cross}")
    print("  (report-only — promotion/demotion is a separate human-reviewed commit)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"near-duplicate overlap threshold (default {DEFAULT_THRESHOLD})")
    return run(ap.parse_args(argv).threshold)


if __name__ == "__main__":
    raise SystemExit(main())
