"""Pre-render one-page layout estimator for tailored resumes.

Predicts how tall a tailored.yaml will render — BEFORE running render.py /
LibreOffice — so the agent can size bullets to one page in a single shot instead
of discovering a 2-page overflow only after rendering.

WHY THIS EXISTS
---------------
Rendering a resume (DOCX -> PDF via LibreOffice) costs several seconds and the
only definitive page-count signal used to come from check.py AFTER rendering.
That produced slow "render -> 2 pages -> trim -> re-render" loops. This module
reconstructs the reference template's real geometry and estimates the rendered
height directly from the YAML, closing the loop up front.

THE MODEL (calibrated on the shipped Arial-10 reference.docx; see LESSONS.md)
----------------------------------------------------------------------------
The template is single-column with three sections (Summary / Education & Skills /
Experience) and one or more employer blocks. Measured facts (US Letter,
LibreOffice render):

  * content width  = pgSz.w - L - R  (default 525.6pt / 7.30in)
  * content height = pgSz.h - T - B  (default 734.4pt / 10.20in)  <- one-page budget
  * body text      = Arial 10pt; name/section headers 16pt; employer header 12pt
  * a full BULLET body line holds ~110 chars; a full PLAIN line (skills/education,
    no hanging indent) ~115 chars
  * body line pitch (bullets)     = 1.15 * font_pt = 11.5pt  (rendered single-spaced)
  * skills/education line pitch   = 1.32 * font_pt = 13.2pt  (276 "auto" = 1.15^2)
  * each bullet paragraph adds    = 2.0pt  space-after (w:spacing after="40")
  * each project title adds       = 10.0pt space-before (w:spacing before="200")
  * fixed overhead (name + contact + 3 section headers + first employer header +
    spacers + section breaks)     = ~140pt
  * each extra employer header    = ~16pt at 10pt body size

Everything is parametrized off the *font size* and *content width* actually found
in the reference DOCX, so the three "levers" the layout responds to fall straight
out of the same calculation:

  1. font size   -> scales char width AND line pitch (both ~linear in font_pt)
  2. margins     -> change content width -> chars-per-line
  3. line spacing-> the 1.15 / 1.32 pitch factors
  4. chars<->line-> content_width / avg_char_width

ACCURACY / SAFETY MARGIN
------------------------
Height for a *known* line count is accurate to ~±2pt. The irreducible error is
word-wrap at a line boundary: char-count alone can't tell whether a ~110-char
bullet lands on 1 or 2 lines, so the estimate carries ~±1 line (~12pt) of noise
near the boundary. Validation over 150+ rendered resumes ranks 1- vs 2-page with
zero mis-rankings at the 734pt line, but two real layouts at est≈727 landed on
opposite sides. So AIM FOR A ONE-LINE SAFETY MARGIN: target est <= ~715pt for a
confident one-shot single page; 715-734 is "tight, trim ~1 line"; >734 will spill.

Usage (accepts the app folder, or the source/tailored.yaml path):
    python skills/resume-writer/scripts/estimate_layout.py applications/6_drafted/<slug>/
    python skills/resume-writer/scripts/estimate_layout.py .../source/tailored.yaml --reference path/to/ref.docx

Exit code 0 = predicted to fit one page (SAFE/OK/TIGHT); 1 = predicted OVERFLOW.
"""

import argparse
import math
import re
import sys
from pathlib import Path

import yaml

# Self-contained skill: put this folder + its _vendor/ on sys.path so `import
# config` / `from layout import ...` resolve to the vendored toolkit copies and
# sibling scripts import directly (same bootstrap as check.py / render.py).
_HERE = Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "_vendor"):
    if str(_p) not in sys.path and _p.is_dir():
        sys.path.insert(0, str(_p))

import config  # noqa: E402
from layout import application_dir, tailored_path  # noqa: E402
from resume_schema import ResumeSchemaError, normalize_resume  # noqa: E402

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# ── Calibrated ratios (measured on the Arial-10 reference.docx) ────────────
# These are template-family constants, not per-application. They are expressed
# as ratios of the *font size* / *content width* so the estimate auto-adapts
# when the template's margins or body font size change (the layout "levers").
CHAR_W_PER_PT = 0.457      # avg Arial glyph advance as a fraction of font pt
BULLET_INDENT_PT = 22.9    # hanging indent that narrows a bulleted line vs a plain line
LINE_FACTOR_BODY = 1.15    # bullet/summary line pitch  = factor * font_pt
LINE_FACTOR_SKILLS = 1.32  # education/skills line pitch = factor * font_pt (276 "auto")
BULLET_AFTER_PT = 2.0      # space-after on each bullet/summary paragraph (after="40")
TITLE_BEFORE_PT = 10.0     # space-before on each project title (before="200")
FIXED_PT_AT_10 = 140.0     # name+contact+3 headers+employer header+spacers+section breaks
EXTRA_EMPLOYER_PT_AT_10 = 16.0  # additional 12pt header + inter-employer breathing room

# Template defaults (US Letter, 0.4in T/B, 0.6in L/R) — used only if the
# reference DOCX can't be read.
DEFAULT_CONTENT_WIDTH_PT = 525.6
DEFAULT_CONTENT_HEIGHT_PT = 734.4
DEFAULT_BODY_PT = 10.0

# ── Verdict thresholds (points below the one-page budget) ──────────────────
TIGHT_MARGIN_PT = 19.0     # est within this of the budget -> "tight, trim ~1 line"
SPARSE_MARGIN_PT = 75.0    # est more than this below the budget -> risk check.py "too blank"


def _plain(text: str) -> str:
    return BOLD_RE.sub(r"\1", text or "")


def read_template_metrics(ref_path: Path) -> dict:
    """Extract (content_width_pt, content_height_pt, body_pt) from the reference DOCX.

    Falls back to the calibrated defaults for any value it can't read, so the
    estimator still works if python-docx is unavailable or the template shifts.
    """
    m = {
        "content_width_pt": DEFAULT_CONTENT_WIDTH_PT,
        "content_height_pt": DEFAULT_CONTENT_HEIGHT_PT,
        "body_pt": DEFAULT_BODY_PT,
        "source": "defaults",
    }
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        return m
    try:
        doc = Document(str(ref_path))
        body = doc.element.body
        sect = body.find(qn("w:sectPr"))
        pg_sz, pg_mar = sect.find(qn("w:pgSz")), sect.find(qn("w:pgMar"))

        def tw(el, a):
            return float(el.get(qn(a)))

        w = tw(pg_sz, "w:w") - tw(pg_mar, "w:left") - tw(pg_mar, "w:right")
        h = tw(pg_sz, "w:h") - tw(pg_mar, "w:top") - tw(pg_mar, "w:bottom")
        m["content_width_pt"] = w / 20.0    # twips -> pt
        m["content_height_pt"] = h / 20.0
        # Body font size: the most common explicit run size among body paragraphs
        # (sz is in half-points). Section headers/name are larger; take the mode.
        sizes = []
        for p in body.findall(qn("w:p")):
            r = p.find(qn("w:r"))
            if r is None:
                continue
            rpr = r.find(qn("w:rPr"))
            sz = rpr.find(qn("w:sz")) if rpr is not None else None
            if sz is not None:
                sizes.append(float(sz.get(qn("w:val"))) / 2.0)
        if sizes:
            m["body_pt"] = min(set(sizes), key=lambda s: (-sizes.count(s), s))
        m["source"] = ref_path.name
    except Exception:
        pass
    return m


def derived_params(metrics: dict) -> dict:
    """Turn raw template metrics into the per-line geometry the model needs."""
    body_pt = metrics["body_pt"]
    width = metrics["content_width_pt"]
    char_w = CHAR_W_PER_PT * body_pt
    return {
        "cpl_plain": max(1, int(width / char_w)),
        "cpl_bullet": max(1, int((width - BULLET_INDENT_PT) / char_w)),
        "pitch_body": LINE_FACTOR_BODY * body_pt,
        "pitch_skills": LINE_FACTOR_SKILLS * body_pt,
        "fixed_pt": FIXED_PT_AT_10 * (body_pt / 10.0),
        "extra_employer_pt": EXTRA_EMPLOYER_PT_AT_10 * (body_pt / 10.0),
        "budget_pt": metrics["content_height_pt"],
        "body_pt": body_pt,
    }


def _lines(text: str, cpl: int) -> int:
    return max(1, math.ceil(len(_plain(text)) / cpl))


def _employers(data: dict) -> list:
    try:
        return normalize_resume(data)["employers"]
    except ResumeSchemaError:
        return []


def estimate(data: dict, params: dict) -> dict:
    """Estimate rendered height (pt) with a per-element breakdown."""
    data = normalize_resume(data)
    cpl_b, cpl_p = params["cpl_bullet"], params["cpl_plain"]
    pb, ps = params["pitch_body"], params["pitch_skills"]

    summary = education = skills = experience = 0.0
    line_count = 0

    for b in data.get("summary_bullets", []):
        n = _lines(b, cpl_b)
        summary += n * pb + BULLET_AFTER_PT
        line_count += n

    n = _lines("Education: " + data.get("education_line", ""), cpl_p)
    education += n * ps
    line_count += n
    for entry in data.get("skills", []):
        n = _lines(f"{entry.get('label', '')}: {entry.get('items', '')}", cpl_p)
        education += n * ps
        line_count += n

    employers = _employers(data)
    extra_headers = max(0, len(employers) - 1) * params["extra_employer_pt"]
    experience += extra_headers
    line_count += max(0, len(employers) - 1)
    for emp in employers:
        for b in emp.get("bullets", []):
            n = _lines(b, cpl_b)
            experience += n * pb + BULLET_AFTER_PT
            line_count += n
        for proj in emp.get("projects", []):
            if proj.get("title"):
                experience += TITLE_BEFORE_PT + _lines(proj["title"], cpl_p) * pb
                line_count += 1
            for b in proj.get("bullets", []):
                n = _lines(b, cpl_b)
                experience += n * pb + BULLET_AFTER_PT
                line_count += n

    total = params["fixed_pt"] + summary + education + experience
    return {
        "total_pt": total,
        "fixed_pt": params["fixed_pt"],
        "summary_pt": summary,
        "education_pt": education,
        "experience_pt": experience,
        "line_count": line_count,
        "budget_pt": params["budget_pt"],
    }


def verdict(total: float, budget: float, pitch_body: float) -> tuple[str, str]:
    """Classify the estimate and give an actionable next step."""
    tight = budget - TIGHT_MARGIN_PT
    sparse = budget - SPARSE_MARGIN_PT
    if total > budget:
        over = total - (budget - TIGHT_MARGIN_PT)  # trim back below the tight line
        n = max(1, math.ceil(over / (pitch_body + BULLET_AFTER_PT)))
        s = "line" if n == 1 else "lines"
        return "OVERFLOW", (f"predicted 2 pages (est {total:.0f}pt > {budget:.0f}pt budget). "
                            f"Cut ~{n} bullet {s} — shorten the longest bullets / summary.")
    if total > tight:
        n = max(1, math.ceil((total - tight) / (pitch_body + BULLET_AFTER_PT)))
        s = "line" if n == 1 else "lines"
        return "TIGHT", (f"likely 1 page but within model error (est {total:.0f}pt, budget "
                         f"{budget:.0f}pt). Trim ~{n} {s} to be safe (target <= {tight:.0f}pt).")
    if total < sparse:
        return "SPARSE", (f"page may look too blank at the bottom (est {total:.0f}pt < "
                          f"{sparse:.0f}pt). Lengthen bullets with real detail (~2 lines each).")
    return "OK", f"predicted 1 page with healthy margin (est {total:.0f}pt, budget {budget:.0f}pt)."


def run(yaml_path: Path, ref_path: Path) -> bool:
    try:
        with open(yaml_path) as f:
            data = normalize_resume(yaml.safe_load(f))
    except (OSError, yaml.YAMLError) as exc:
        print(f"Error: could not read {yaml_path}: {exc}", file=sys.stderr)
        return False
    except ResumeSchemaError as exc:
        print(f"Error: invalid resume schema: {exc}", file=sys.stderr)
        return False
    metrics = read_template_metrics(ref_path)
    params = derived_params(metrics)
    est = estimate(data, params)
    status, msg = verdict(est["total_pt"], est["budget_pt"], params["pitch_body"])

    print(f"  Layout estimate (template: {metrics['source']}, "
          f"body {params['body_pt']:.0f}pt, "
          f"{params['cpl_bullet']}/{params['cpl_plain']} chars per bullet/plain line):")
    print(f"    fixed={est['fixed_pt']:.0f}  summary={est['summary_pt']:.0f}  "
          f"edu&skills={est['education_pt']:.0f}  experience={est['experience_pt']:.0f}")
    print(f"    TOTAL est {est['total_pt']:.0f}pt / {est['budget_pt']:.0f}pt budget "
          f"({est['line_count']} content lines)")
    print(f"  {status}: {msg}")
    return status != "OVERFLOW"


def main():
    ap = argparse.ArgumentParser(description="Pre-render one-page layout estimator")
    ap.add_argument("yaml_path", help="Application folder, or the source/tailored.yaml path")
    ap.add_argument("--reference", "-r", default=None,
                    help="Reference DOCX (default: config.paths.reference_docx)")
    args = ap.parse_args()

    inp = Path(args.yaml_path)
    yaml_path = inp if inp.is_file() else tailored_path(application_dir(inp))
    if not yaml_path.exists():
        print(f"Error: tailored.yaml not found for {inp}", file=sys.stderr)
        sys.exit(2)
    ref_path = Path(args.reference) if args.reference else config.reference_docx_path()
    ok = run(yaml_path, ref_path)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
