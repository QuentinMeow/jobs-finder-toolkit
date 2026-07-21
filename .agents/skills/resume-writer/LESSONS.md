# Lessons — Resume Writer

Curated operational lessons from real usage — the hard-won engineering memory (DOCX/render
internals + calibrated layout constants) that lives nowhere else. General ATS guidance,
deliverable/multi-role rules, and the schema live in SKILL.md / reference.md / application-tracker.

Last reviewed: 2026-07-19

Lifecycle tags: each `##` section carries `<!-- added: <first-seen> · last_confirmed: <date> · status: active -->`
(gardener `lessons_report` parses these; `added` = the section's first git appearance, `last_confirmed` = last review date).

## Rendering / layout (DOCX internals)
<!-- added: 2026-04-16 · last_confirmed: 2026-07-19 · status: active -->
- Employer header must be `Company – Role` (left) + `dates | location` **right-aligned to
  the right margin**. `render.py` (`_build_emp_header`/`_right_tab_pos`) does this with a
  right tab stop at the content width (pgSz.w − pgMar.left − pgMar.right, e.g. 10512 twips),
  emitting runs: left text → `<w:tab/>` → right text. Do NOT align with space padding —
  spaces drift toward the middle in a proportional font. The reference DOCX still has legacy
  hard spaces in its employer line; the renderer ignores them and rebuilds the row.
- `w:tabs` must precede `w:spacing`/`w:rPr` inside `w:pPr` (CT_PPr child order) or strict
  parsers (LibreOffice) can drop it — insert tabs at index 0 of pPr.
- Rendered files use the configured resume stem (`config.resume_stem()`, e.g.
  `Jordan_Rivers_Software_Engineer_Resume`) (.docx/.pdf), defined by `RESUME_STEM` in
  `check.py` and imported by `render.py`. The resume DOCX + cover-letter DOCX live in the app
  folder's `source/`; the resume PDF + cover PDF(s) + bundled `..._Application_<job title>.txt`
  file(s) + `meta.yaml` stay at the root. Quote paths in shell (parens).
- `check.application_roles()` reads the role list from `meta.yaml` (a `jobs:` list, else the
  single top-level `role`); `render.py`/`cover_letter.py` render one letter per role and
  `check.py` validates each. The `<job title>` slug comes from `check.slugify_label`
  (underscores). A labeled lookup (`find_application_txt(folder, role)`) matches its OWN file
  exactly and never falls back to another role's bundle, so every role's
  `..._Application_<role>.txt` must exist. The cover letter is authored inside that bundle's
  COVER LETTER section (title + `===` underline), NOT a standalone `.txt`; the rendered letter
  starts with name + contact then the salutation — NO company/role subject line (hard requirement).
- Optional `target_position: "<Role>"` in `tailored.yaml` (or `render.py --label`) appends a
  slug to the resume stem, e.g. `..._Resume_Frontend_Engineer.{docx,pdf}`. `check.py` resolves
  the labeled resume PDF from `target_position`; `status.py` globs for artifacts. Only for the
  divergent multi-role split (Path B); cover letters/bundles are always per-JD labeled.
- Layout resolution lives in `check.py` (`application_dir`/`source_dir`/`tailored_path`);
  `render.py`/`check.py`/`status.py` all accept the app folder OR the `source/tailored.yaml`
  path.
- Quick visual check after render: `sips -s format png "<...Resume.pdf>" --out /tmp/preview.png`
  (or `pdftoppm`) and eyeball the employer row alignment.

## Pre-render layout budget — calibrated constants
<!-- added: 2026-04-16 · last_confirmed: 2026-07-19 · status: active -->
`estimate_layout.py` predicts rendered height from `tailored.yaml` BEFORE rendering (Step 5.5),
so the page is sized in one shot instead of "render → 2 pages → trim → re-render".

**Calibrated template geometry** (measured on the shipped Arial-10 reference DOCX, LibreOffice
render; all read live from the DOCX so the numbers self-adjust if the template changes):
- Page US Letter; margins T/B = 576 twips (0.4in), L/R = 864 twips (0.6in).
- **Content width = 525.6pt (7.30in); content height = 734.4pt (10.20in) = the one-page budget.**
- Body = Arial **10pt** (sz=20); name/section headers 16pt (sz=32); employer header 12pt (sz=24).
- **Wrap width: ~110 chars per bulleted line, ~115 per plain line** (skills/education have no
  hanging indent so fit ~5 more chars). avg Arial glyph ≈ 0.457 × font-pt ≈ 4.57pt at 10pt.
- **Line pitch: bullets render single-spaced ≈ 11.5pt (1.15×pt); skills/education lines use
  276 "auto" ≈ 13.2pt (1.15²×pt).** Each bullet paragraph adds 2.0pt space-after (after=40);
  each project title adds 10.0pt space-before (before=200).
- **Fixed overhead ≈ 140pt** (name + contact + 3 section headers + the first employer header +
  spacers + section breaks). Each additional employer header + inter-employer spacing costs
  approximately **16pt at 10pt body size**.
- Model: `height = 140 + 16×extra_employers + Σ(lines×pitch + spacing)`; direct role bullets
  and project bullets use the same body-line model; `lines = ceil(plain_len / chars_per_line)`.

**Verdict bands:** OK ~660–~715pt · TIGHT 715–734 (trim ~1 line) · OVERFLOW > 734 (2 pages) ·
SPARSE < ~660 (risks check.py "too blank"). **Aim est ≤ ~715pt** (≈ one rendered line of margin)
for a confident one-shot single page. Height for a KNOWN line count is ±~2pt; the irreducible
error is word-wrap at a line boundary (±1 line ≈ ±12pt), so honor the one-line safety margin —
check.py's post-render page count stays the authoritative gate.

**The three levers** (all re-derived from the DOCX, so tweaking the template updates the estimate):
1. **Font size** — scales glyph width (chars/line) and line pitch, ~linear. 10pt→9.5pt buys
   ~5% more chars/line and ~5% shorter lines (small end for a resume).
2. **Margins** — L/R 0.6in→0.5in widens content ~30pt → ~+6 chars/line; T/B 0.4in→0.35in adds
   ~7pt of vertical budget. Safest lever, small visual impact.
3. **Line spacing** — tightening bullets toward 1.0× reclaims ~1.5pt/line (~45pt over 30 lines)
   but looks denser.
Prefer sizing CONTENT to the existing budget (trim bullets to ≤2 lines) over changing the
approved template; only touch margins/spacing/font with the user's ok.

## Environment
<!-- added: 2026-04-16 · last_confirmed: 2026-07-19 · status: active -->
- Use the repo venv `.venv/bin/python` (uv-managed) — system pythons may be too old/blocked.
- PDF conversion uses LibreOffice (`pdf_convert.py` probes `~/Applications/LibreOffice.app`
  then `/Applications/LibreOffice.app`). If Word/docx2pdf isn't available, rely on LibreOffice.
- If `render.py` prints "PDF: skipped" (transient LibreOffice lock/first-run), convert manually
  then re-run check.py: `soffice --headless --convert-to pdf --outdir <folder> "<folder>/<RESUME_STEM>.docx"`.
- `**text**` markers in `tailored.yaml` render as bold runs; the baseline uses them for key phrases.
- Always save the full JD text, not just the URL — postings get taken down. Review the
  `tailored.yaml` diff against the profile to catch drift or fabrication.
